"""Comercios y proveedores (§3.9, F-37 y F-38).

El comercio es una entidad estable, no texto libre: es lo que hace posibles el
ranking de gasto, la comparación entre proveedores y el reconocimiento del emisor
de una factura. Las cifras de gasto salen de `vw_movement_lines`, así que un
traspaso entre cuentas propias nunca cuenta como gasto de un comercio (RN-21).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select, text, update

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, verificar_csrf
from app.api.v1.presupuestos import periodo_de, periodo_valido, primer_dia, rango_de
from app.api.v1.transacciones import contar, del_hogar, ref_tematica, texto_plano
from app.core.config import settings
from app.core.errors import Conflicto, ReglaDeNegocio
from app.models.categoria import Category
from app.models.comercio import Payee
from app.models.factura import Invoice
from app.models.fusion import MergeOperation
from app.models.recurrente import RecurringRule
from app.models.regla import CategorizationRule
from app.models.transaccion import Transaction
from app.schemas.comercio import (
    ComercioActualizar,
    ComercioCrear,
    ComercioEstadisticasRespuesta,
    ComercioFiltro,
    ComercioFusionCrear,
    ComercioFusionResultadoRespuesta,
    ComercioPeriodoRespuesta,
    ComercioRefRespuesta,
    ComercioRespuesta,
    ComercioSugerenciaFiltro,
    ComercioSugerenciaRespuesta,
    ComercioTematicaRespuesta,
)
from app.schemas.comun import Pagina
from app.services.normalizacion import similitud, sin_acentos

# Las rutas llevan su prefijo completo (`/payees`), así que el agregador
# incluye este router sin `prefix`. `verificar_csrf` va en el router porque no
# hace nada en GET, HEAD ni OPTIONS: así no se puede olvidar en un endpoint.
router = APIRouter(tags=["payees"], dependencies=[Depends(verificar_csrf)])

CERO = Decimal("0.00")

#: RN-20: una fusión se puede deshacer durante 30 días.
DIAS_PARA_DESHACER = 30

_ESTADISTICAS = text(
    """
    SELECT payee_id,
           COALESCE(SUM(spent), 0)::numeric(14,2) AS gastado,
           COUNT(DISTINCT transaction_id)         AS movimientos,
           MIN(booked_on)                         AS primera,
           MAX(booked_on)                         AS ultima
      FROM vw_movement_lines
     WHERE household_id = :hogar
       AND payee_id IS NOT NULL
       AND kind <> 'transfer'
       AND NOT excluded_from_reports
     GROUP BY payee_id
    """
)


def _normalizar(nombre: str) -> str:
    return sin_acentos(nombre).lower().strip()


async def _nombre_libre(alcance: AlcanceHogar, nombre: str, excluir: uuid.UUID | None) -> None:
    consulta = select(Payee.id).where(
        Payee.household_id == alcance.household_id,
        Payee.normalized_name == _normalizar(nombre),
        Payee.archived_at.is_(None),
        Payee.merged_into_id.is_(None),
    )
    if excluir is not None:
        consulta = consulta.where(Payee.id != excluir)
    if (await alcance.sesion.scalar(consulta)) is not None:
        raise Conflicto(f"Ya tienes un comercio llamado «{nombre}».", codigo="nombre_duplicado")


def _respuesta(
    comercio: Payee,
    *,
    tematica: Category | None = None,
    estadisticas: dict[str, object] | None = None,
    facturas: int | None = None,
) -> ComercioRespuesta:
    datos = estadisticas or {}
    gastado = datos.get("gastado")
    movimientos = datos.get("movimientos")
    medio = None
    if gastado is not None and movimientos:
        medio = (Decimal(str(gastado)) / Decimal(str(movimientos))).quantize(Decimal("0.01"))
    return ComercioRespuesta(
        id=comercio.id,
        created_at=comercio.created_at,
        updated_at=comercio.updated_at,
        name=comercio.name,
        normalized_name=comercio.normalized_name,
        default_category=ref_tematica(tematica),
        # `payees` no tiene tabla de alias: los alias que aprende el sistema viven
        # en `product_aliases`, que es de productos. Aquí viaja siempre vacío.
        aliases=[],
        tax_id=comercio.tax_id,
        website=comercio.website,
        note=comercio.notes,
        is_archived=comercio.archived_at is not None,
        transactions_count=int(movimientos) if movimientos is not None else None,
        total_spent=Decimal(str(gastado)) if gastado is not None else None,
        average_ticket=medio,
        first_seen_on=datos.get("primera"),  # type: ignore[arg-type]
        last_seen_on=datos.get("ultima") or comercio.last_seen_on,  # type: ignore[arg-type]
        invoices_count=facturas,
    )


async def _estadisticas_de(
    alcance: AlcanceHogar, ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, object]]:
    if not ids:
        return {}
    filas = await alcance.sesion.execute(_ESTADISTICAS, {"hogar": alcance.household_id})
    return {
        fila.payee_id: {
            "gastado": fila.gastado,
            "movimientos": fila.movimientos,
            "primera": fila.primera,
            "ultima": fila.ultima,
        }
        for fila in filas
        if fila.payee_id in set(ids)
    }


@router.get("/payees", summary="Comercios con número de movimientos y total gastado")
async def listar_comercios(
    alcance: Alcance,
    filtro: Annotated[ComercioFiltro, Query()],
) -> Pagina[ComercioRespuesta]:
    consulta = select(Payee).where(
        Payee.household_id == alcance.household_id, Payee.merged_into_id.is_(None)
    )
    if filtro.is_archived is not None:
        consulta = consulta.where(
            Payee.archived_at.is_not(None) if filtro.is_archived else Payee.archived_at.is_(None)
        )
    if filtro.category_id:
        consulta = consulta.where(Payee.default_category_id == filtro.category_id)
    if filtro.q:
        consulta = consulta.where(texto_plano(Payee.name).like(f"%{_normalizar(filtro.q)}%"))

    total = await contar(alcance, consulta)
    columnas = {
        "name": Payee.name,
        "transactions_count": Payee.transaction_count,
        "total_spent": Payee.transaction_count,
        "last_seen_on": Payee.last_seen_on,
        "created_at": Payee.created_at,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is not None:
            consulta = consulta.order_by(
                columna.desc().nulls_last() if descendente else columna.asc().nulls_last()
            )
    consulta = consulta.order_by(Payee.id.desc())

    filas = list(
        (await alcance.sesion.execute(consulta.offset(filtro.desplazamiento).limit(filtro.size)))
        .scalars()
        .all()
    )
    tematicas = await _tematicas_de(alcance, filas)
    estadisticas = (
        await _estadisticas_de(alcance, [fila.id for fila in filas])
        if "stats" in filtro.include
        else {}
    )
    items = [
        _respuesta(
            fila,
            tematica=tematicas.get(fila.default_category_id) if fila.default_category_id else None,
            estadisticas=estadisticas.get(fila.id),
        )
        for fila in filas
    ]
    return Pagina.crear(items, page=filtro.page, size=filtro.size, total=total)


async def _tematicas_de(alcance: AlcanceHogar, comercios: list[Payee]) -> dict[uuid.UUID, Category]:
    ids = {c.default_category_id for c in comercios if c.default_category_id}
    if not ids:
        return {}
    return {
        categoria.id: categoria
        for categoria in await alcance.sesion.scalars(select(Category).where(Category.id.in_(ids)))
    }


@router.post("/payees", status_code=status.HTTP_201_CREATED, summary="Crea un comercio")
async def crear_comercio(
    alcance: AlcanceEscritura, datos: ComercioCrear, respuesta: Response
) -> ComercioRespuesta:
    await _nombre_libre(alcance, datos.name, None)
    tematica = None
    if datos.default_category_id is not None:
        tematica = await del_hogar(
            alcance, Category, datos.default_category_id, mensaje="La temática no existe."
        )
    comercio = Payee(
        household_id=alcance.household_id,
        name=datos.name,
        normalized_name=_normalizar(datos.name),
        default_category_id=tematica.id if tematica else None,
        website=datos.website,
        tax_id=datos.tax_id,
        notes=datos.note,
    )
    alcance.sesion.add(comercio)
    await alcance.sesion.commit()
    await alcance.sesion.refresh(comercio)
    respuesta.headers["Location"] = f"{settings.api_prefix}/payees/{comercio.id}"
    return _respuesta(comercio, tematica=tematica)


@router.get("/payees/suggestions", summary="Sugerencias por parecido difuso")
async def sugerir_comercios(
    alcance: Alcance,
    filtro: Annotated[ComercioSugerenciaFiltro, Query()],
) -> list[ComercioSugerenciaRespuesta]:
    """Usa `similitud()` del servicio de normalización; el umbral por defecto es 88."""
    filas = list(
        await alcance.sesion.scalars(
            select(Payee).where(
                Payee.household_id == alcance.household_id,
                Payee.archived_at.is_(None),
                Payee.merged_into_id.is_(None),
            )
        )
    )
    objetivo = _normalizar(filtro.name)
    puntuadas = [(comercio, similitud(objetivo, comercio.normalized_name)) for comercio in filas]
    puntuadas = [par for par in puntuadas if par[1] >= filtro.min_score]
    puntuadas.sort(key=lambda par: -par[1])
    return [
        ComercioSugerenciaRespuesta(
            payee=ComercioRefRespuesta(id=comercio.id, name=comercio.name),
            score=round(puntuacion, 2),
        )
        for comercio, puntuacion in puntuadas[: filtro.limit]
    ]


@router.post("/payees/merge", summary="Fusiona comercios duplicados")
async def fusionar_comercios(
    alcance: AlcanceEscritura, datos: ComercioFusionCrear
) -> ComercioFusionResultadoRespuesta:
    """Reasigna el histórico y deja las origen archivadas apuntando a la destino."""
    destino = await del_hogar(alcance, Payee, datos.target_id, mensaje="El comercio no existe.")
    origenes = [
        await del_hogar(alcance, Payee, identificador, mensaje="El comercio no existe.")
        for identificador in datos.source_ids
    ]
    ids = [origen.id for origen in origenes]

    movidas = await alcance.sesion.execute(
        update(Transaction)
        .where(Transaction.household_id == alcance.household_id, Transaction.payee_id.in_(ids))
        .values(payee_id=destino.id)
    )
    facturas = await alcance.sesion.execute(
        update(Invoice)
        .where(Invoice.household_id == alcance.household_id, Invoice.payee_id.in_(ids))
        .values(payee_id=destino.id)
    )
    reglas = await alcance.sesion.execute(
        update(CategorizationRule)
        .where(
            CategorizationRule.household_id == alcance.household_id,
            CategorizationRule.set_payee_id.in_(ids),
        )
        .values(set_payee_id=destino.id)
    )
    recurrentes = await alcance.sesion.execute(
        update(RecurringRule)
        .where(
            RecurringRule.household_id == alcance.household_id,
            RecurringRule.payee_id.in_(ids),
        )
        .values(payee_id=destino.id)
    )

    ahora = datetime.now(UTC)
    operacion = MergeOperation(
        household_id=alcance.household_id,
        entity_type="payee",
        source_id=ids[0],
        target_id=destino.id,
        source_label=", ".join(origen.name for origen in origenes),
        target_label=destino.name,
        status="done",
        options={"keep_aliases": datos.keep_aliases},
        counts={"transactions": movidas.rowcount or 0, "invoices": facturas.rowcount or 0},
        performed_by_id=alcance.usuario.id,
        started_at=ahora,
        finished_at=ahora,
        undo_deadline=ahora + timedelta(days=DIAS_PARA_DESHACER),
    )
    alcance.sesion.add(operacion)

    for origen in origenes:
        origen.archived_at = origen.archived_at or ahora
        origen.merged_into_id = destino.id
        destino.transaction_count += origen.transaction_count
        origen.transaction_count = 0

    await alcance.sesion.commit()
    return ComercioFusionResultadoRespuesta(
        merge_id=operacion.id,
        target=ComercioRefRespuesta(id=destino.id, name=destino.name),
        sources=[ComercioRefRespuesta(id=o.id, name=o.name) for o in origenes],
        transactions_moved=movidas.rowcount or 0,
        invoices_moved=facturas.rowcount or 0,
        aliases_moved=0,
        rules_updated=reglas.rowcount or 0,
        recurring_updated=recurrentes.rowcount or 0,
    )


@router.get("/payees/{comercio_id}", summary="Detalle con estadísticas")
async def obtener_comercio(alcance: Alcance, comercio_id: uuid.UUID) -> ComercioRespuesta:
    comercio = await del_hogar(alcance, Payee, comercio_id, mensaje="El comercio no existe.")
    tematica = (
        await alcance.sesion.get(Category, comercio.default_category_id)
        if comercio.default_category_id
        else None
    )
    estadisticas = await _estadisticas_de(alcance, [comercio.id])
    facturas = int(
        await alcance.sesion.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.household_id == alcance.household_id, Invoice.payee_id == comercio.id)
        )
        or 0
    )
    return _respuesta(
        comercio,
        tematica=tematica,
        estadisticas=estadisticas.get(comercio.id),
        facturas=facturas,
    )


@router.patch("/payees/{comercio_id}", summary="Renombra, cambia temática o archiva")
async def editar_comercio(
    alcance: AlcanceEscritura, comercio_id: uuid.UUID, datos: ComercioActualizar
) -> ComercioRespuesta:
    comercio = await del_hogar(alcance, Payee, comercio_id, mensaje="El comercio no existe.")
    campos = datos.model_dump(exclude_unset=True)
    if datos.name:
        await _nombre_libre(alcance, datos.name, comercio.id)
        comercio.name = datos.name
        comercio.normalized_name = _normalizar(datos.name)
    if "default_category_id" in campos:
        if datos.default_category_id is None:
            comercio.default_category_id = None
        else:
            comercio.default_category_id = (
                await del_hogar(
                    alcance, Category, datos.default_category_id, mensaje="La temática no existe."
                )
            ).id
    if "website" in campos:
        comercio.website = datos.website
    if "tax_id" in campos:
        comercio.tax_id = datos.tax_id
    if "note" in campos:
        comercio.notes = datos.note
    if datos.is_archived is not None:
        comercio.archived_at = datetime.now(UTC) if datos.is_archived else None
    await alcance.sesion.commit()
    return await obtener_comercio(alcance, comercio.id)


@router.delete(
    "/payees/{comercio_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra el comercio",
)
async def borrar_comercio(
    alcance: AlcanceEscritura,
    comercio_id: uuid.UUID,
    reassign_to: Annotated[uuid.UUID | None, Query()] = None,
    on_history: Annotated[str | None, Query(pattern="^(null|reassign)$")] = None,
) -> Response:
    """Con histórico hay que decir qué se hace con él: dejarlo a nulo o reasignarlo."""
    comercio = (
        await alcance.sesion.execute(
            select(Payee).where(Payee.household_id == alcance.household_id, Payee.id == comercio_id)
        )
    ).scalar_one_or_none()
    if comercio is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    con_historico = int(
        await alcance.sesion.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.household_id == alcance.household_id,
                Transaction.payee_id == comercio.id,
            )
        )
        or 0
    )
    if con_historico:
        if on_history is None:
            raise Conflicto(
                f"Este comercio tiene {con_historico} movimientos. Indica «on_history=null» "
                "para desvincularlos o «on_history=reassign» con otro comercio."
            )
        destino_id = None
        if on_history == "reassign":
            if reassign_to is None:
                raise ReglaDeNegocio("Indica el comercio al que reasignar el histórico.")
            destino_id = (
                await del_hogar(alcance, Payee, reassign_to, mensaje="El comercio no existe.")
            ).id
        await alcance.sesion.execute(
            update(Transaction)
            .where(
                Transaction.household_id == alcance.household_id,
                Transaction.payee_id == comercio.id,
            )
            .values(payee_id=destino_id)
        )

    await alcance.sesion.delete(comercio)
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/payees/{comercio_id}/stats", summary="Gasto por mes y por temática")
async def estadisticas_comercio(
    alcance: Alcance,
    comercio_id: uuid.UUID,
    period_from: Annotated[str | None, Query()] = None,
    period_to: Annotated[str | None, Query()] = None,
) -> ComercioEstadisticasRespuesta:
    comercio = await del_hogar(alcance, Payee, comercio_id, mensaje="El comercio no existe.")
    desde = primer_dia(period_from) if period_from else date(1970, 1, 1)
    hasta = rango_de(period_to)[1] if period_to else date(2200, 12, 31)

    por_mes = await alcance.sesion.execute(
        text(
            """
            SELECT period_month,
                   COALESCE(SUM(spent), 0)::numeric(14,2) AS gastado,
                   COUNT(DISTINCT transaction_id)         AS movimientos
              FROM vw_movement_lines
             WHERE household_id = :hogar AND payee_id = :comercio
               AND booked_on BETWEEN :desde AND :hasta
               AND kind <> 'transfer' AND NOT excluded_from_reports
             GROUP BY period_month
             ORDER BY period_month
            """
        ),
        {
            "hogar": alcance.household_id,
            "comercio": comercio.id,
            "desde": desde,
            "hasta": hasta,
        },
    )
    meses = [
        ComercioPeriodoRespuesta(
            period=periodo_de(fila.period_month),
            amount=Decimal(fila.gastado),
            transactions=fila.movimientos,
        )
        for fila in por_mes
    ]

    por_tematica = await alcance.sesion.execute(
        text(
            """
            SELECT category_id,
                   COALESCE(SUM(spent), 0)::numeric(14,2) AS gastado,
                   COUNT(DISTINCT transaction_id)         AS movimientos
              FROM vw_movement_lines
             WHERE household_id = :hogar AND payee_id = :comercio
               AND booked_on BETWEEN :desde AND :hasta
               AND kind <> 'transfer' AND NOT excluded_from_reports
             GROUP BY category_id
            """
        ),
        {
            "hogar": alcance.household_id,
            "comercio": comercio.id,
            "desde": desde,
            "hasta": hasta,
        },
    )
    filas_tematica = list(por_tematica)
    ids = [fila.category_id for fila in filas_tematica if fila.category_id]
    tematicas = (
        {
            categoria.id: categoria
            for categoria in await alcance.sesion.scalars(
                select(Category).where(Category.id.in_(ids))
            )
        }
        if ids
        else {}
    )
    total = sum((Decimal(fila.gastado) for fila in filas_tematica), CERO)
    movimientos = sum(fila.movimientos for fila in filas_tematica)
    categorias = [
        ComercioTematicaRespuesta(
            category=ref_tematica(tematicas.get(fila.category_id)),
            amount=Decimal(fila.gastado),
            transactions=fila.movimientos,
            share_pct=float(Decimal(fila.gastado) / total * 100) if total else 0.0,
        )
        for fila in filas_tematica
    ]
    categorias.sort(key=lambda item: -item.amount)

    return ComercioEstadisticasRespuesta(
        payee=ComercioRefRespuesta(id=comercio.id, name=comercio.name),
        period_from=periodo_valido(period_from) if period_from else None,
        period_to=periodo_valido(period_to) if period_to else None,
        total_spent=total,
        transactions=movimientos,
        average_ticket=(total / movimientos).quantize(Decimal("0.01")) if movimientos else CERO,
        by_period=meses,
        by_category=categorias,
    )


__all__ = ["router"]
