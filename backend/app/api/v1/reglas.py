"""Reglas de auto-categorización (§3.11, F-27).

El motor de evaluación es `app/services/reglas.py`: `aplicar_reglas()` y
`aplicar_a_lote()`. Aquí solo se traduce entre el vocabulario del contrato (en
inglés) y el del motor, cosa que ya hace `CondicionRegla.a_condicion()`.

`categorization_rules` guarda dos representaciones de la misma regla: `text_form`
es lo que el usuario lee y `conditions` es lo que se ejecuta. El compilador va
siempre de una a la otra en la misma escritura, así que la regla mostrada y la
ejecutada no pueden divergir; `text_form` se genera aquí a partir de las
condiciones y es además la clave de unicidad de una regla activa.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, verificar_csrf
from app.api.v1.transacciones import (
    contar,
    contexto_de,
    del_hogar,
    respuesta_transaccion,
    tematica_del_hogar,
    texto_plano,
)
from app.core.config import settings
from app.core.errors import Conflicto, NoEncontrado
from app.models.categoria import Category
from app.models.comercio import Payee
from app.models.cuenta import Account
from app.models.regla import CategorizationRule
from app.models.transaccion import Tag, Transaction
from app.schemas.comun import Pagina
from app.schemas.regla import (
    AccionesRegla,
    CampoRegla,
    CondicionRegla,
    OperadorRegla,
    ReglaActualizar,
    ReglaAplicadaRespuesta,
    ReglaAplicarCrear,
    ReglaAplicarResultadoRespuesta,
    ReglaCrear,
    ReglaFiltro,
    ReglaProbarCrear,
    ReglaProbarRespuesta,
    ReglaReordenarCrear,
    ReglaRespuesta,
)
from app.schemas.transaccion import TipoMovimiento
from app.services.reglas import MovimientoEvaluable, Regla, aplicar_a_lote

# Las rutas llevan su prefijo completo (`/rules`), así que el agregador
# incluye este router sin `prefix`. `verificar_csrf` va en el router porque no
# hace nada en GET, HEAD ni OPTIONS: así no se puede olvidar en un endpoint.
router = APIRouter(tags=["rules"], dependencies=[Depends(verificar_csrf)])

#: RN-56: una regla solo actúa sobre lo que no categorizó una persona.
CATEGORIZACION_AUTOMATICA = ("rule", "import", "payee")

#: Tope de transacciones que se evalúan de una vez en `test` y `apply`.
LOTE_MAXIMO = 5_000

_TEXTO_CAMPO = {
    CampoRegla.PAYEE: "comercio",
    CampoRegla.DESCRIPTION: "concepto",
    CampoRegla.NOTE: "nota",
    CampoRegla.AMOUNT: "importe",
    CampoRegla.ACCOUNT: "cuenta",
    CampoRegla.DATE: "fecha",
}

_TEXTO_OPERADOR = {
    OperadorRegla.CONTAINS: "contiene",
    OperadorRegla.NOT_CONTAINS: "no contiene",
    OperadorRegla.EQUALS: "es",
    OperadorRegla.STARTS_WITH: "empieza por",
    OperadorRegla.ENDS_WITH: "termina en",
    OperadorRegla.REGEX: "coincide con",
    OperadorRegla.GT: "mayor que",
    OperadorRegla.LT: "menor que",
    OperadorRegla.BETWEEN: "entre",
}


def _texto_de(condiciones: list[CondicionRegla], modo: str) -> str:
    """Compila las condiciones a su forma legible («si concepto contiene "x"»).

    Es también la clave de unicidad de una regla activa: dos reglas activas con
    las mismas condiciones harían el resultado dependiente del orden, que es justo
    lo que RN-55 evita. Las acciones quedan fuera del texto a propósito: llevan
    identificadores, y un nombre congelado se quedaría obsoleto al renombrar la
    temática (F-05).
    """
    partes = []
    for condicion in condiciones:
        texto = (
            f"{_TEXTO_CAMPO[condicion.field]} {_TEXTO_OPERADOR[condicion.operator]} "
            f'"{condicion.value}"'
        )
        if condicion.operator is OperadorRegla.BETWEEN and condicion.value_to:
            texto += f' y "{condicion.value_to}"'
        partes.append(texto)
    union = " y " if modo == "all" else " o "
    return f"si {union.join(partes)}"


def _acciones_de(fila: CategorizationRule) -> AccionesRegla:
    return AccionesRegla(
        set_category_id=fila.set_category_id,
        set_payee_id=fila.set_payee_id,
        add_tag_ids=list(fila.add_tag_ids or []),
        set_note=fila.set_notes,
        # `mark_as_transfer` no tiene columna propia: una regla no puede convertir
        # un movimiento en transferencia (haría falta la segunda pata), así que se
        # guarda como «fuera de informes», que es su efecto real.
        mark_as_transfer=bool(fila.set_excluded_from_reports),
        stop_processing=fila.stop_processing,
    )


def _condiciones_de(fila: CategorizationRule) -> list[CondicionRegla]:
    return [CondicionRegla.model_validate(condicion) for condicion in fila.conditions]


def _respuesta(fila: CategorizationRule, *, motivo: str | None = None) -> ReglaRespuesta:
    return ReglaRespuesta(
        id=fila.id,
        created_at=fila.created_at,
        updated_at=fila.updated_at,
        name=fila.name or fila.text_form,
        match=fila.match_mode,  # type: ignore[arg-type]
        conditions=_condiciones_de(fila),
        actions=_acciones_de(fila),
        priority=fila.priority,
        is_active=fila.is_active,
        apply_to_imports=True,
        apply_to_invoices=fila.applies_to in ("invoice_line", "both"),
        applied_count=fila.match_count,
        last_applied_at=fila.last_matched_at,
        disabled_reason=motivo,
    )


def _a_regla_servicio(
    identificador: str,
    nombre: str,
    condiciones: list[CondicionRegla],
    acciones: AccionesRegla,
    modo: str,
    prioridad: int,
) -> Regla:
    return Regla(
        regla_id=identificador,
        nombre=nombre,
        condiciones=[condicion.a_condicion() for condicion in condiciones],
        categoria_id=str(acciones.set_category_id) if acciones.set_category_id else None,
        comercio_id=str(acciones.set_payee_id) if acciones.set_payee_id else None,
        etiquetas=[str(t) for t in acciones.add_tag_ids] or None,
        prioridad=prioridad,
        exigir_todas=modo == "all",
    )


async def _validar_acciones(alcance: AlcanceHogar, acciones: AccionesRegla) -> None:
    """RN-59: una regla no asigna una temática archivada ni inexistente."""
    if acciones.set_category_id:
        await tematica_del_hogar(alcance, acciones.set_category_id)
    if acciones.set_payee_id:
        await del_hogar(alcance, Payee, acciones.set_payee_id, mensaje="El comercio no existe.")
    for etiqueta_id in acciones.add_tag_ids:
        await del_hogar(alcance, Tag, etiqueta_id, mensaje="La etiqueta no existe.")


async def _texto_libre(alcance: AlcanceHogar, texto: str, excluir: uuid.UUID | None) -> None:
    consulta = select(CategorizationRule.id).where(
        CategorizationRule.household_id == alcance.household_id,
        func.lower(CategorizationRule.text_form) == texto.lower(),
        CategorizationRule.is_active.is_(True),
    )
    if excluir is not None:
        consulta = consulta.where(CategorizationRule.id != excluir)
    if (await alcance.sesion.scalar(consulta)) is not None:
        raise Conflicto("Ya tienes una regla activa idéntica.", codigo="nombre_duplicado")


async def _motivos(alcance: AlcanceHogar, filas: list[CategorizationRule]) -> dict[uuid.UUID, str]:
    """RN-59: si la temática se archivó después, la regla se informa como inservible."""
    ids = {fila.set_category_id for fila in filas if fila.set_category_id}
    if not ids:
        return {}
    archivadas = set(
        await alcance.sesion.scalars(
            select(Category.id).where(Category.id.in_(ids), Category.archived_at.is_not(None))
        )
    )
    return {
        fila.id: "La temática que asigna está archivada."
        for fila in filas
        if fila.set_category_id in archivadas
    }


@router.get("/rules", summary="Reglas por orden de prioridad")
async def listar_reglas(
    alcance: Alcance,
    filtro: Annotated[ReglaFiltro, Query()],
) -> Pagina[ReglaRespuesta]:
    consulta = select(CategorizationRule).where(
        CategorizationRule.household_id == alcance.household_id
    )
    if filtro.is_active is not None:
        consulta = consulta.where(CategorizationRule.is_active.is_(filtro.is_active))
    if filtro.category_id:
        consulta = consulta.where(CategorizationRule.set_category_id == filtro.category_id)
    if filtro.q:
        aguja = f"%{filtro.q.lower()}%"
        consulta = consulta.where(texto_plano(CategorizationRule.text_form).like(aguja))

    total = await contar(alcance, consulta)
    columnas = {
        "priority": CategorizationRule.priority,
        "name": CategorizationRule.name,
        "applied_count": CategorizationRule.match_count,
        "created_at": CategorizationRule.created_at,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is not None:
            consulta = consulta.order_by(
                columna.desc().nulls_last() if descendente else columna.asc().nulls_last()
            )
    consulta = consulta.order_by(CategorizationRule.id.asc())

    filas = list(
        (await alcance.sesion.execute(consulta.offset(filtro.desplazamiento).limit(filtro.size)))
        .scalars()
        .all()
    )
    motivos = await _motivos(alcance, filas)
    items = [_respuesta(fila, motivo=motivos.get(fila.id)) for fila in filas]
    return Pagina.crear(items, page=filtro.page, size=filtro.size, total=total)


@router.post("/rules", status_code=status.HTTP_201_CREATED, summary="Crea una regla")
async def crear_regla(
    alcance: AlcanceEscritura, datos: ReglaCrear, respuesta: Response
) -> ReglaRespuesta:
    await _validar_acciones(alcance, datos.actions)
    # Construir la regla del motor valida operadores y expresiones regulares.
    _a_regla_servicio("", datos.name, datos.conditions, datos.actions, datos.match, datos.priority)
    texto = _texto_de(datos.conditions, datos.match)
    await _texto_libre(alcance, texto, None)

    fila = CategorizationRule(
        household_id=alcance.household_id,
        name=datos.name,
        conditions=[condicion.model_dump(mode="json") for condicion in datos.conditions],
        text_form=texto,
        match_mode=datos.match,
        set_category_id=datos.actions.set_category_id,
        set_payee_id=datos.actions.set_payee_id,
        add_tag_ids=list(datos.actions.add_tag_ids) or None,
        set_notes=datos.actions.set_note,
        set_excluded_from_reports=True if datos.actions.mark_as_transfer else None,
        priority=datos.priority,
        stop_processing=datos.actions.stop_processing,
        applies_to="both" if datos.apply_to_invoices else "transaction",
        is_active=datos.is_active,
    )
    alcance.sesion.add(fila)
    await alcance.sesion.commit()
    await alcance.sesion.refresh(fila)
    respuesta.headers["Location"] = f"{settings.api_prefix}/rules/{fila.id}"
    return _respuesta(fila)


@router.post("/rules/reorder", summary="Reordena la prioridad de evaluación")
async def reordenar_reglas(
    alcance: AlcanceEscritura, datos: ReglaReordenarCrear
) -> list[ReglaRespuesta]:
    """RN-55: el orden de la lista es el orden de evaluación."""
    filas = {
        fila.id: fila
        for fila in await alcance.sesion.scalars(
            select(CategorizationRule).where(
                CategorizationRule.household_id == alcance.household_id,
                CategorizationRule.id.in_(datos.ids),
            )
        )
    }
    if len(filas) != len(datos.ids):
        raise NoEncontrado("Alguna de las reglas no existe.")
    for posicion, identificador in enumerate(datos.ids, start=1):
        filas[identificador].priority = posicion * 10
    await alcance.sesion.commit()
    ordenadas = [filas[identificador] for identificador in datos.ids]
    return [_respuesta(fila) for fila in ordenadas]


async def _candidatas(
    alcance: AlcanceHogar,
    *,
    todas: bool,
    desde: date | None = None,
    hasta: date | None = None,
    cuenta_id: uuid.UUID | None = None,
    limite: int = LOTE_MAXIMO,
) -> list[Transaction]:
    """Transacciones sobre las que una regla puede actuar (RN-56, RN-57)."""
    consulta = select(Transaction).where(
        Transaction.household_id == alcance.household_id,
        # RN-57: ni patas de transferencia ni ajustes de conciliación.
        Transaction.kind != TipoMovimiento.TRANSFER.value,
        Transaction.reconciliation_id.is_(None),
        Transaction.split_count == 0,
    )
    if not todas:
        consulta = consulta.where(
            Transaction.categorized_by.in_(CATEGORIZACION_AUTOMATICA),
        )
    if desde is not None:
        consulta = consulta.where(Transaction.booked_on >= desde)
    if hasta is not None:
        consulta = consulta.where(Transaction.booked_on <= hasta)
    if cuenta_id is not None:
        consulta = consulta.where(Transaction.account_id == cuenta_id)
    consulta = consulta.order_by(Transaction.booked_on.desc(), Transaction.id.desc()).limit(limite)
    return list((await alcance.sesion.execute(consulta)).scalars().all())


async def _evaluables(alcance: AlcanceHogar, filas: list[Transaction]) -> list[MovimientoEvaluable]:
    """Prepara los movimientos para el motor con dos consultas, no con 2·N."""
    ids_comercio = {fila.payee_id for fila in filas if fila.payee_id}
    ids_cuenta = {fila.account_id for fila in filas}
    comercios = (
        {
            comercio.id: comercio.name
            for comercio in await alcance.sesion.scalars(
                select(Payee).where(Payee.id.in_(ids_comercio))
            )
        }
        if ids_comercio
        else {}
    )
    cuentas = {
        cuenta.id: cuenta.name
        for cuenta in await alcance.sesion.scalars(
            select(Account).where(Account.id.in_(ids_cuenta))
        )
    }
    return [
        MovimientoEvaluable(
            descripcion=fila.description,
            comercio=comercios.get(fila.payee_id) if fila.payee_id else None,
            importe=abs(fila.amount),
            cuenta=cuentas.get(fila.account_id),
        )
        for fila in filas
    ]


@router.post("/rules/test", summary="Prueba una regla sin guardarla")
async def probar_regla(alcance: Alcance, datos: ReglaProbarCrear) -> ReglaProbarRespuesta:
    """Devuelve qué casaría, contra un texto de ejemplo y contra el histórico."""
    regla = _a_regla_servicio(
        "prueba",
        datos.rule.name,
        datos.rule.conditions,
        datos.rule.actions,
        datos.rule.match,
        datos.rule.priority,
    )
    casa_ejemplo = None
    if datos.sample_text is not None:
        casa_ejemplo = regla.coincide(MovimientoEvaluable(descripcion=datos.sample_text))

    if not datos.against_history:
        return ReglaProbarRespuesta(matches=0, sample_matched=casa_ejemplo)

    filas = await _candidatas(alcance, todas=True)
    evaluables = await _evaluables(alcance, filas)
    casan = [
        fila
        for fila, movimiento in zip(filas, evaluables, strict=True)
        if regla.coincide(movimiento)
    ]
    muestra = casan[: datos.limit]
    if muestra:
        # Los splits ya se sabe que están vacíos (`split_count = 0`), pero el
        # serializador los recorre: se cargan en bloque para no hacer N+1.
        muestra = list(
            (
                await alcance.sesion.execute(
                    select(Transaction)
                    .where(Transaction.id.in_([fila.id for fila in muestra]))
                    .options(selectinload(Transaction.splits))
                )
            )
            .unique()
            .scalars()
        )
    incluir = frozenset({"account", "category", "payee"})
    contexto = await contexto_de(alcance, muestra, incluir)
    return ReglaProbarRespuesta(
        matches=len(casan),
        sample_matched=casa_ejemplo,
        transactions=[respuesta_transaccion(fila, contexto, incluir) for fila in muestra],
    )


@router.post("/rules/apply", summary="Aplica reglas al histórico; `dry_run` no toca nada")
async def aplicar_al_historico(
    alcance: AlcanceEscritura, datos: ReglaAplicarCrear
) -> ReglaAplicarResultadoRespuesta:
    """RN-55 y RN-56: gana la de menor prioridad y no se pisa lo categorizado a mano."""
    consulta = select(CategorizationRule).where(
        CategorizationRule.household_id == alcance.household_id,
        CategorizationRule.is_active.is_(True),
    )
    if datos.rule_ids:
        consulta = consulta.where(CategorizationRule.id.in_(datos.rule_ids))
    filas_regla = list((await alcance.sesion.execute(consulta)).scalars().all())
    if datos.rule_ids and len(filas_regla) != len(set(datos.rule_ids)):
        raise NoEncontrado("Alguna de las reglas no existe o no está activa.")
    if not filas_regla:
        return ReglaAplicarResultadoRespuesta(
            dry_run=datos.dry_run, evaluated=0, matched=0, updated=0
        )

    reglas = [
        _a_regla_servicio(
            str(fila.id),
            fila.name or fila.text_form,
            _condiciones_de(fila),
            _acciones_de(fila),
            fila.match_mode,
            fila.priority,
        )
        for fila in filas_regla
    ]
    por_id = {str(fila.id): fila for fila in filas_regla}
    # Los nombres se copian antes de tocar la transacción: un `rollback` expira los
    # objetos del ORM y leerlos después haría una consulta fuera de contexto.
    nombres = {clave: fila.name or fila.text_form for clave, fila in por_id.items()}

    candidatas = await _candidatas(
        alcance,
        todas=datos.scope == "all",
        desde=datos.date_from,
        hasta=datos.date_to,
        cuenta_id=datos.account_id,
    )
    evaluables = await _evaluables(alcance, candidatas)
    asignaciones = aplicar_a_lote(evaluables, reglas)

    contadores: dict[str, dict[str, int]] = {
        clave: {"matched": 0, "updated": 0} for clave in por_id
    }
    casan = 0
    actualizadas = 0
    manuales_respetadas = 0
    ahora = datetime.now(UTC)

    for transaccion, asignacion in zip(candidatas, asignaciones, strict=True):
        if asignacion is None:
            continue
        casan += 1
        contadores[asignacion.regla_id]["matched"] += 1
        if transaccion.categorized_by == "user":
            manuales_respetadas += 1
            continue
        nueva = uuid.UUID(asignacion.categoria_id) if asignacion.categoria_id else None
        if nueva is None or nueva == transaccion.category_id:
            continue
        contadores[asignacion.regla_id]["updated"] += 1
        actualizadas += 1
        if datos.dry_run:
            continue
        transaccion.category_id = nueva
        transaccion.categorized_by = "rule"
        transaccion.applied_rule_id = uuid.UUID(asignacion.regla_id)
        fila = por_id[asignacion.regla_id]
        fila.match_count += 1
        fila.last_matched_at = ahora

    if datos.dry_run:
        await alcance.sesion.rollback()
    else:
        await alcance.sesion.commit()

    return ReglaAplicarResultadoRespuesta(
        dry_run=datos.dry_run,
        evaluated=len(candidatas),
        matched=casan,
        updated=actualizadas,
        manual_preserved=manuales_respetadas,
        by_rule=[
            ReglaAplicadaRespuesta(
                rule_id=uuid.UUID(clave),
                name=nombres[clave],
                matched=cuentas["matched"],
                updated=cuentas["updated"],
            )
            for clave, cuentas in contadores.items()
            if cuentas["matched"]
        ],
    )


@router.get("/rules/{regla_id}", summary="Detalle con contador de aplicaciones")
async def obtener_regla(alcance: Alcance, regla_id: uuid.UUID) -> ReglaRespuesta:
    fila = await del_hogar(alcance, CategorizationRule, regla_id, mensaje="La regla no existe.")
    motivos = await _motivos(alcance, [fila])
    return _respuesta(fila, motivo=motivos.get(fila.id))


@router.patch("/rules/{regla_id}", summary="Edita condiciones, acciones o prioridad")
async def editar_regla(
    alcance: AlcanceEscritura, regla_id: uuid.UUID, datos: ReglaActualizar
) -> ReglaRespuesta:
    fila = await del_hogar(alcance, CategorizationRule, regla_id, mensaje="La regla no existe.")
    campos = datos.model_dump(exclude_unset=True)
    condiciones = datos.conditions if datos.conditions is not None else _condiciones_de(fila)
    acciones = datos.actions if datos.actions is not None else _acciones_de(fila)
    modo = datos.match or fila.match_mode

    if datos.actions is not None:
        await _validar_acciones(alcance, acciones)
    _a_regla_servicio(
        str(fila.id), datos.name or fila.name or "", condiciones, acciones, modo, fila.priority
    )

    if datos.conditions is not None or datos.actions is not None or datos.match is not None:
        texto = _texto_de(condiciones, modo)
        await _texto_libre(alcance, texto, fila.id)
        fila.text_form = texto
        fila.conditions = [condicion.model_dump(mode="json") for condicion in condiciones]
        fila.match_mode = modo
        fila.set_category_id = acciones.set_category_id
        fila.set_payee_id = acciones.set_payee_id
        fila.add_tag_ids = list(acciones.add_tag_ids) or None
        fila.set_notes = acciones.set_note
        fila.set_excluded_from_reports = True if acciones.mark_as_transfer else None
        fila.stop_processing = acciones.stop_processing

    if datos.name:
        fila.name = datos.name
    if datos.priority is not None:
        fila.priority = datos.priority
    if datos.is_active is not None:
        fila.is_active = datos.is_active
    if "apply_to_invoices" in campos and datos.apply_to_invoices is not None:
        fila.applies_to = "both" if datos.apply_to_invoices else "transaction"

    await alcance.sesion.commit()
    await alcance.sesion.refresh(fila)
    return _respuesta(fila)


@router.delete(
    "/rules/{regla_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra la regla; lo ya categorizado no cambia",
)
async def borrar_regla(alcance: AlcanceEscritura, regla_id: uuid.UUID) -> Response:
    fila = (
        await alcance.sesion.execute(
            select(CategorizationRule).where(
                CategorizationRule.household_id == alcance.household_id,
                CategorizationRule.id == regla_id,
            )
        )
    ).scalar_one_or_none()
    if fila is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await alcance.sesion.delete(fila)
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
