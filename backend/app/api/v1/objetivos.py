"""Fondos objetivo (§3.15, F-31).

«Vacaciones: 2.400 € para julio». El importe acumulado **no se guarda**: es
`starting_amount` más la suma de las aportaciones, y `required_monthly` se
recalcula en cada lectura (RN-51). Así no hay dos verdades que puedan
desincronizarse.

Una aportación con cuenta es una transferencia real de dinero (RN-53), así que se
crea con las dos patas de `/transfers` y queda sujeta a RN-21 a RN-24: no cuenta
como gasto ni como ingreso.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import (
    Alcance,
    AlcanceEscritura,
    AlcanceHogar,
    PaginacionActual,
    verificar_csrf,
)
from app.api.v1.transacciones import (
    contar,
    cuenta_del_hogar,
    del_hogar,
    ref_tematica,
    tematica_del_hogar,
    texto_plano,
)
from app.api.v1.transferencias import crear_patas
from app.core.config import settings
from app.core.errors import Conflicto, ReglaDeNegocio
from app.models.categoria import Category
from app.models.objetivo import Goal, GoalContribution
from app.models.transaccion import Transaction
from app.schemas.comun import Pagina
from app.schemas.objetivo import (
    MovimientoObjetivoCrear,
    MovimientoObjetivoRespuesta,
    ObjetivoActualizar,
    ObjetivoCrear,
    ObjetivoFiltro,
    ObjetivoRespuesta,
    TipoMovimientoObjetivo,
)
from app.services.normalizacion import sin_acentos

# Las rutas llevan su prefijo completo (`/goals`), así que el agregador
# incluye este router sin `prefix`. `verificar_csrf` va en el router porque no
# hace nada en GET, HEAD ni OPTIONS: así no se puede olvidar en un endpoint.
router = APIRouter(tags=["goals"], dependencies=[Depends(verificar_csrf)])

CERO = Decimal("0.00")
CENTIMO = Decimal("0.01")


def _meses_hasta(objetivo: date | None, hoy: date) -> int | None:
    if objetivo is None:
        return None
    meses = (objetivo.year - hoy.year) * 12 + (objetivo.month - hoy.month)
    return max(meses, 0)


def _respuesta(
    fondo: Goal, acumulado: Decimal, tematica: Category | None, hoy: date | None = None
) -> ObjetivoRespuesta:
    hoy = hoy or date.today()
    restante = max(fondo.target_amount - acumulado, CERO)
    meses = _meses_hasta(fondo.target_date, hoy)
    necesario = None
    if restante > CERO and meses is not None:
        # Con el mes objetivo ya encima, lo que falta hay que ponerlo este mes.
        necesario = (restante / Decimal(max(meses, 1))).quantize(CENTIMO, rounding=ROUND_HALF_UP)
    completado = acumulado >= fondo.target_amount
    return ObjetivoRespuesta(
        id=fondo.id,
        created_at=fondo.created_at,
        updated_at=fondo.updated_at,
        name=fondo.name,
        target_amount=fondo.target_amount,
        current_amount=acumulado,
        remaining=restante,
        progress_pct=float(
            (acumulado / fondo.target_amount * 100).quantize(CENTIMO, rounding=ROUND_HALF_UP)
        )
        if fondo.target_amount
        else 0.0,
        target_date=fondo.target_date,
        months_left=meses,
        required_monthly=necesario,
        monthly_contribution=fondo.monthly_contribution,
        is_on_track=completado
        or necesario is None
        or (fondo.monthly_contribution is not None and fondo.monthly_contribution >= necesario),
        is_completed=completado,
        category=ref_tematica(tematica),
        account_id=fondo.account_id,
        note=fondo.notes,
    )


async def _acumulados(alcance: AlcanceHogar, fondos: list[Goal]) -> dict[uuid.UUID, Decimal]:
    """`starting_amount` más la suma de aportaciones, en una sola consulta."""
    if not fondos:
        return {}
    filas = await alcance.sesion.execute(
        select(
            GoalContribution.goal_id,
            func.coalesce(func.sum(GoalContribution.amount), 0),
        )
        .where(GoalContribution.goal_id.in_([fondo.id for fondo in fondos]))
        .group_by(GoalContribution.goal_id)
    )
    sumas = {clave: Decimal(valor) for clave, valor in filas}
    return {fondo.id: fondo.starting_amount + sumas.get(fondo.id, CERO) for fondo in fondos}


async def _tematicas_de(alcance: AlcanceHogar, fondos: list[Goal]) -> dict[uuid.UUID, Category]:
    ids = {fondo.category_id for fondo in fondos if fondo.category_id}
    if not ids:
        return {}
    return {
        categoria.id: categoria
        for categoria in await alcance.sesion.scalars(select(Category).where(Category.id.in_(ids)))
    }


async def _nombre_libre(alcance: AlcanceHogar, nombre: str, excluir: uuid.UUID | None) -> None:
    consulta = select(Goal.id).where(
        Goal.household_id == alcance.household_id,
        func.lower(Goal.name) == nombre.lower(),
        Goal.status != "cancelled",
    )
    if excluir is not None:
        consulta = consulta.where(Goal.id != excluir)
    if (await alcance.sesion.scalar(consulta)) is not None:
        raise Conflicto(f"Ya tienes un fondo llamado «{nombre}».", codigo="nombre_duplicado")


async def _una_respuesta(alcance: AlcanceHogar, fondo: Goal) -> ObjetivoRespuesta:
    acumulados = await _acumulados(alcance, [fondo])
    tematicas = await _tematicas_de(alcance, [fondo])
    # `updated_at` queda pendiente de leer tras cualquier UPDATE (su `onupdate` es
    # una expresión SQL), así que se refresca antes de serializar.
    await alcance.sesion.refresh(fondo)
    return _respuesta(
        fondo,
        acumulados[fondo.id],
        tematicas.get(fondo.category_id) if fondo.category_id else None,
    )


async def _marcar_alcanzado(alcance: AlcanceHogar, fondo: Goal, acumulado: Decimal) -> None:
    """RN-54: se marca al llegar al objetivo, pero sigue aceptando movimientos.

    Se llama solo desde los endpoints que mueven dinero: `is_completed` de la
    respuesta es derivado, así que una lectura no necesita escribir nada.
    """
    alcanzado = acumulado >= fondo.target_amount
    if alcanzado and fondo.status == "active":
        fondo.status = "reached"
        fondo.reached_at = datetime.now(UTC)
        await alcance.sesion.commit()
    elif not alcanzado and fondo.status == "reached":
        fondo.status = "active"
        fondo.reached_at = None
        await alcance.sesion.commit()


@router.get("/goals", summary="Fondos con lo acumulado, lo que falta y el ritmo necesario")
async def listar_objetivos(
    alcance: Alcance,
    filtro: Annotated[ObjetivoFiltro, Query()],
) -> Pagina[ObjetivoRespuesta]:
    consulta = select(Goal).where(
        Goal.household_id == alcance.household_id, Goal.status != "cancelled"
    )
    if filtro.category_id:
        consulta = consulta.where(Goal.category_id == filtro.category_id)
    if filtro.account_id:
        consulta = consulta.where(Goal.account_id == filtro.account_id)
    if filtro.is_completed is not None:
        consulta = consulta.where(
            Goal.status == "reached" if filtro.is_completed else Goal.status != "reached"
        )
    if filtro.q:
        consulta = consulta.where(texto_plano(Goal.name).like(f"%{sin_acentos(filtro.q).lower()}%"))

    total = await contar(alcance, consulta)
    columnas = {
        "name": Goal.name,
        "target_date": Goal.target_date,
        "target_amount": Goal.target_amount,
        "progress_pct": Goal.target_amount,
        "created_at": Goal.created_at,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is not None:
            consulta = consulta.order_by(
                columna.desc().nulls_last() if descendente else columna.asc().nulls_last()
            )
    consulta = consulta.order_by(Goal.id.desc())

    filas = list(
        (await alcance.sesion.execute(consulta.offset(filtro.desplazamiento).limit(filtro.size)))
        .scalars()
        .all()
    )
    acumulados = await _acumulados(alcance, filas)
    tematicas = await _tematicas_de(alcance, filas)
    items = [
        _respuesta(
            fila,
            acumulados[fila.id],
            tematicas.get(fila.category_id) if fila.category_id else None,
        )
        for fila in filas
    ]
    return Pagina.crear(items, page=filtro.page, size=filtro.size, total=total)


@router.post("/goals", status_code=status.HTTP_201_CREATED, summary="Crea un fondo objetivo")
async def crear_objetivo(
    alcance: AlcanceEscritura, datos: ObjetivoCrear, respuesta: Response
) -> ObjetivoRespuesta:
    await _nombre_libre(alcance, datos.name, None)
    tematica = await tematica_del_hogar(alcance, datos.category_id) if datos.category_id else None
    cuenta = await cuenta_del_hogar(alcance, datos.account_id) if datos.account_id else None
    fondo = Goal(
        household_id=alcance.household_id,
        name=datos.name,
        category_id=tematica.id if tematica else None,
        account_id=cuenta.id if cuenta else None,
        target_amount=datos.target_amount,
        target_date=datos.target_date,
        monthly_contribution=datos.monthly_contribution,
        starting_amount=datos.initial_amount,
        notes=datos.note,
        status="active",
    )
    alcance.sesion.add(fondo)
    await alcance.sesion.commit()
    await alcance.sesion.refresh(fondo)
    respuesta.headers["Location"] = f"{settings.api_prefix}/goals/{fondo.id}"
    return await _una_respuesta(alcance, fondo)


@router.get("/goals/{objetivo_id}", summary="Detalle con proyección")
async def obtener_objetivo(alcance: Alcance, objetivo_id: uuid.UUID) -> ObjetivoRespuesta:
    fondo = await del_hogar(alcance, Goal, objetivo_id, mensaje="El fondo no existe.")
    return await _una_respuesta(alcance, fondo)


@router.patch("/goals/{objetivo_id}", summary="Cambia importe objetivo, fecha o temática")
async def editar_objetivo(
    alcance: AlcanceEscritura, objetivo_id: uuid.UUID, datos: ObjetivoActualizar
) -> ObjetivoRespuesta:
    fondo = await del_hogar(alcance, Goal, objetivo_id, mensaje="El fondo no existe.")
    campos = datos.model_dump(exclude_unset=True)
    if datos.name:
        await _nombre_libre(alcance, datos.name, fondo.id)
        fondo.name = datos.name
    if datos.target_amount is not None:
        fondo.target_amount = datos.target_amount
    if "target_date" in campos:
        fondo.target_date = datos.target_date
    if "category_id" in campos:
        fondo.category_id = (
            (await tematica_del_hogar(alcance, datos.category_id)).id if datos.category_id else None
        )
    if "account_id" in campos:
        fondo.account_id = (
            (await cuenta_del_hogar(alcance, datos.account_id)).id if datos.account_id else None
        )
    if "monthly_contribution" in campos:
        fondo.monthly_contribution = datos.monthly_contribution
    if "note" in campos:
        fondo.notes = datos.note
    await alcance.sesion.commit()
    return await _una_respuesta(alcance, fondo)


@router.delete(
    "/goals/{objetivo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra el fondo; las aportaciones se conservan",
)
async def borrar_objetivo(
    alcance: AlcanceEscritura,
    objetivo_id: uuid.UUID,
    delete_movements: Annotated[bool, Query()] = False,
) -> Response:
    """Las transferencias de aportación sobreviven salvo `?delete_movements=true`."""
    fondo = (
        await alcance.sesion.execute(
            select(Goal)
            .where(Goal.household_id == alcance.household_id, Goal.id == objetivo_id)
            .options(selectinload(Goal.contributions))
        )
    ).scalar_one_or_none()
    if fondo is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if delete_movements:
        grupos = set(
            await alcance.sesion.scalars(
                select(Transaction.transfer_group_id).where(
                    Transaction.household_id == alcance.household_id,
                    Transaction.goal_id == fondo.id,
                    Transaction.transfer_group_id.is_not(None),
                )
            )
        )
        if grupos:
            await alcance.sesion.execute(
                delete(Transaction).where(
                    Transaction.household_id == alcance.household_id,
                    Transaction.transfer_group_id.in_(grupos),
                )
            )
    await alcance.sesion.delete(fondo)
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _mover(
    alcance: AlcanceHogar,
    fondo: Goal,
    datos: MovimientoObjetivoCrear,
    *,
    entrada: bool,
) -> None:
    """Aporta (`entrada`) o retira del fondo, con transferencia real si hay cuenta."""
    acumulados = await _acumulados(alcance, [fondo])
    actual = acumulados[fondo.id]
    if not entrada and datos.amount > actual:
        raise ReglaDeNegocio(
            f"No puedes retirar {datos.amount:.2f} €: el fondo tiene {actual:.2f} €.",
            codigo="saldo_insuficiente",
        )

    transaccion_id: uuid.UUID | None = None
    if datos.account_id is not None:
        if fondo.account_id is None:
            raise ReglaDeNegocio(
                "Este fondo no tiene cuenta donde guardar el dinero: asígnale una primero."
            )
        contraria = await cuenta_del_hogar(alcance, datos.account_id)
        propia = await cuenta_del_hogar(alcance, fondo.account_id)
        origen, destino = (contraria, propia) if entrada else (propia, contraria)
        grupo = await crear_patas(
            alcance,
            origen=origen,
            destino=destino,
            fecha=datos.date,
            importe=datos.amount,
            moneda=propia.currency,
            descripcion=f"{'Aportación a' if entrada else 'Retirada de'} {fondo.name}",
            nota=datos.note,
            objetivo_id=fondo.id,
        )
        # La aportación se cuelga de la pata que entra (o sale) de la cuenta del
        # fondo: es la que representa el movimiento del dinero del fondo.
        transaccion_id = await alcance.sesion.scalar(
            select(Transaction.id).where(
                Transaction.transfer_group_id == grupo,
                Transaction.account_id == propia.id,
            )
        )

    alcance.sesion.add(
        GoalContribution(
            household_id=alcance.household_id,
            goal_id=fondo.id,
            transaction_id=transaccion_id,
            amount=datos.amount if entrada else -datos.amount,
            occurred_on=datos.date,
            note=datos.note,
        )
    )
    await alcance.sesion.commit()

    # El estado del fondo se recalcula aquí, con el dinero ya movido (RN-54).
    acumulados = await _acumulados(alcance, [fondo])
    await _marcar_alcanzado(alcance, fondo, acumulados[fondo.id])


@router.post("/goals/{objetivo_id}/contribute", summary="Aporta al fondo")
async def aportar(
    alcance: AlcanceEscritura, objetivo_id: uuid.UUID, datos: MovimientoObjetivoCrear
) -> ObjetivoRespuesta:
    """Con `account_id` genera una transferencia real a la cuenta del fondo (RN-53)."""
    fondo = await del_hogar(alcance, Goal, objetivo_id, mensaje="El fondo no existe.")
    await _mover(alcance, fondo, datos, entrada=True)
    return await _una_respuesta(alcance, fondo)


@router.post("/goals/{objetivo_id}/withdraw", summary="Retira del fondo")
async def retirar(
    alcance: AlcanceEscritura, objetivo_id: uuid.UUID, datos: MovimientoObjetivoCrear
) -> ObjetivoRespuesta:
    """RN-52: una retirada no puede dejar el fondo en negativo."""
    fondo = await del_hogar(alcance, Goal, objetivo_id, mensaje="El fondo no existe.")
    await _mover(alcance, fondo, datos, entrada=False)
    return await _una_respuesta(alcance, fondo)


@router.get("/goals/{objetivo_id}/movements", summary="Aportaciones y retiradas del fondo")
async def listar_movimientos(
    alcance: Alcance, objetivo_id: uuid.UUID, paginacion: PaginacionActual
) -> Pagina[MovimientoObjetivoRespuesta]:
    fondo = await del_hogar(alcance, Goal, objetivo_id, mensaje="El fondo no existe.")
    consulta = select(GoalContribution).where(GoalContribution.goal_id == fondo.id)
    total = int(
        await alcance.sesion.scalar(
            select(func.count()).select_from(consulta.order_by(None).subquery())
        )
        or 0
    )
    # Se recorren todas en orden cronológico para poder dar el saldo tras cada
    # movimiento, que es lo que hace legible el histórico.
    todas = list(
        (
            await alcance.sesion.execute(
                consulta.order_by(GoalContribution.occurred_on, GoalContribution.id)
            )
        )
        .scalars()
        .all()
    )
    saldo = fondo.starting_amount
    items: list[MovimientoObjetivoRespuesta] = []
    for fila in todas:
        saldo += fila.amount
        items.append(
            MovimientoObjetivoRespuesta(
                id=fila.id,
                goal_id=fila.goal_id,
                kind=TipoMovimientoObjetivo.CONTRIBUTION
                if fila.amount > 0
                else TipoMovimientoObjetivo.WITHDRAWAL,
                amount=abs(fila.amount),
                date=fila.occurred_on,
                account_id=fondo.account_id,
                transaction_id=fila.transaction_id,
                balance_after=saldo,
                note=fila.note,
                created_at=fila.created_at,
            )
        )
    items.reverse()
    pagina = items[paginacion.offset : paginacion.offset + paginacion.limit]
    return Pagina.crear(pagina, page=paginacion.page, size=paginacion.size, total=total)


__all__ = ["router"]
