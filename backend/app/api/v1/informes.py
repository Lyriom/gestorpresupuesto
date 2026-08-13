"""Los informes del contrato: §3.19 y §4.12.

Todo el gasto de este módulo sale de la vista `vw_movement_lines`, no de
`transactions`. La razón está en la propia migración que la crea: la disyunción
«transacción simple o repartida» y la inversión del signo están escritas **una
sola vez** en todo el sistema, así que ningún informe puede contar dos veces el
mismo dinero ni equivocarse de signo. Las transferencias quedan fuera del gasto y
del ingreso (RN-21).

El análisis de precios no se recalcula aquí: es `app/services/precios.py`, igual
que en `productos.py`.
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import uuid as uuidlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import Select, column, func, select, table

from app.api.deps import Alcance, AlcanceHogar, verificar_csrf
from app.api.v1.productos import (
    _producto_o_404,
    comercios_por_nombre,
    comparar_cesta_de,
    comparativa_de,
    comparativa_por_comercio,
    estadisticas_de,
    productos_de_cesta,
    puntos_por_producto,
    ref_comercio,
    ref_producto,
    ultima_observacion,
)
from app.core.errors import ReglaDeNegocio
from app.models.categoria import Category
from app.models.comercio import Payee
from app.models.cuenta import Account
from app.models.presupuesto import BudgetAllocation, BudgetPeriod
from app.models.producto import Product, ProductPrice
from app.models.recurrente import RecurringOccurrence, RecurringRule
from app.models.transaccion import Transaction
from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comun import Respuesta
from app.schemas.cuenta import TIPOS_PASIVO, CuentaRefRespuesta, TipoCuenta
from app.schemas.informe import (
    AnomaliaFilaRespuesta,
    AnomaliasFiltro,
    AnomaliasRespuesta,
    CashFlowFiltro,
    CashFlowRespuesta,
    CestaFiltro,
    CestaInformeRespuesta,
    ComparativaMensualRespuesta,
    GastoPorTematicaFilaRespuesta,
    GastoPorTematicaFiltro,
    GastoPorTematicaRespuesta,
    IngresoGastoFilaRespuesta,
    IngresoGastoRespuesta,
    ParametrosInforme,
    PatrimonioCuentaRespuesta,
    PatrimonioFiltro,
    PatrimonioRespuesta,
    PrecioProductoFiltro,
    PrecioProductoRespuesta,
    PresupuestoVsRealFilaRespuesta,
    PresupuestoVsRealFiltro,
    PresupuestoVsRealRespuesta,
    PuntoCashFlowRespuesta,
    PuntoMensualRespuesta,
    PuntoPatrimonioRespuesta,
    PuntoPrecioProductoRespuesta,
    SaldoProyectadoFilaRespuesta,
    SaldoProyectadoFiltro,
    SaldoProyectadoRespuesta,
    SubidaPrecioFilaRespuesta,
    SubidasPrecioFiltro,
    SubidasPrecioRespuesta,
    SuscripcionesFiltro,
    SuscripcionesRespuesta,
    SuscripcionFilaRespuesta,
    TopComercioFilaRespuesta,
    TopComerciosFiltro,
    TopComerciosRespuesta,
)
from app.schemas.recurrente import Frecuencia
from app.schemas.transaccion import TransaccionRespuesta
from app.services import precios
from app.services.formato import euros, porcentaje

router = APIRouter(dependencies=[Depends(verificar_csrf)])

CENTIMO = Decimal("0.01")
CERO = Decimal("0.00")

#: Cuántos meses se muestran cuando no se pide un rango concreto.
MESES_POR_DEFECTO = 12

#: Meses equivalentes de cada frecuencia, para el coste mensual de una suscripción.
MESES_DE_FRECUENCIA: dict[str, Decimal] = {
    Frecuencia.WEEKLY: Decimal("52") / Decimal("12"),
    Frecuencia.BIWEEKLY: Decimal("26") / Decimal("12"),
    Frecuencia.MONTHLY: Decimal(1),
    Frecuencia.BIMONTHLY: Decimal("0.5"),
    Frecuencia.QUARTERLY: Decimal(1) / Decimal(3),
    Frecuencia.SEMIANNUAL: Decimal(1) / Decimal(6),
    Frecuencia.YEARLY: Decimal(1) / Decimal(12),
    Frecuencia.EVERY_N_DAYS: Decimal(1),
    Frecuencia.LAST_WEEKDAY_OF_MONTH: Decimal(1),
}

# La vista que ya resuelve «simple o repartida» y el signo del gasto.
MOVIMIENTOS = table(
    "vw_movement_lines",
    column("transaction_id"),
    column("split_id"),
    column("household_id"),
    column("account_id"),
    column("payee_id"),
    column("kind"),
    column("booked_on"),
    column("period_month"),
    column("category_id"),
    column("amount"),
    column("spent"),
    column("status"),
    column("excluded_from_reports"),
    column("currency"),
    column("invoice_line_id"),
)

SALDOS = table(
    "vw_account_balances",
    column("account_id"),
    column("household_id"),
    column("type"),
    column("account_class"),
    column("currency"),
    column("opening_balance"),
    column("working_balance"),
    column("cleared_balance"),
    column("net_worth_value"),
)


# --------------------------------------------------------------------------- #
# Periodos y rangos
# --------------------------------------------------------------------------- #


def periodo_de(fecha: date) -> str:
    return f"{fecha.year:04d}-{fecha.month:02d}"


def inicio_de(periodo: str) -> date:
    anyo, mes = (int(parte) for parte in periodo.split("-"))
    return date(anyo, mes, 1)


def fin_de(periodo: str) -> date:
    anyo, mes = (int(parte) for parte in periodo.split("-"))
    return date(anyo, mes, calendar.monthrange(anyo, mes)[1])


def periodos_entre(desde: str, hasta: str) -> list[str]:
    lista: list[str] = []
    actual = inicio_de(desde)
    limite = inicio_de(hasta)
    while actual <= limite and len(lista) < 600:
        lista.append(periodo_de(actual))
        actual = (
            date(actual.year + 1, 1, 1)
            if actual.month == 12
            else date(actual.year, actual.month + 1, 1)
        )
    return lista


@dataclass(slots=True)
class Rango:
    """Ventana del informe, resuelta a fechas y a periodos."""

    desde: date
    hasta: date
    periodo_desde: str
    periodo_hasta: str

    @property
    def dias(self) -> int:
        return (self.hasta - self.desde).days + 1

    def anterior(self) -> Rango:
        """La misma ventana justo antes, para las columnas de comparación."""
        fin = self.desde - timedelta(days=1)
        inicio = fin - timedelta(days=self.dias - 1)
        return Rango(inicio, fin, periodo_de(inicio), periodo_de(fin))


def rango_de(filtro: ParametrosInforme, *, meses: int = 1) -> Rango:
    """`period`, `period_from`/`period_to` o `date_from`/`date_to` (§3.19)."""
    if filtro.date_from or filtro.date_to:
        hasta = filtro.date_to or date.today()
        desde = filtro.date_from or (hasta - timedelta(days=30 * meses))
        if desde > hasta:
            raise ReglaDeNegocio(
                "El rango de fechas está invertido.", codigo="error_solicitud", estado=400
            )
        return Rango(desde, hasta, periodo_de(desde), periodo_de(hasta))

    if filtro.period:
        return Rango(inicio_de(filtro.period), fin_de(filtro.period), filtro.period, filtro.period)

    hasta = filtro.period_to or periodo_de(date.today())
    if filtro.period_from:
        desde = filtro.period_from
    else:
        primero = inicio_de(hasta)
        retroceso = primero
        for _ in range(meses - 1):
            retroceso = (
                date(retroceso.year - 1, 12, 1)
                if retroceso.month == 1
                else date(retroceso.year, retroceso.month - 1, 1)
            )
        desde = periodo_de(retroceso)
    if inicio_de(desde) > inicio_de(hasta):
        raise ReglaDeNegocio(
            "El rango de periodos está invertido.", codigo="error_solicitud", estado=400
        )
    return Rango(inicio_de(desde), fin_de(hasta), desde, hasta)


# --------------------------------------------------------------------------- #
# CSV y ETag
# --------------------------------------------------------------------------- #


def _plano(fila: BaseModel) -> dict[str, str]:
    """Aplana una fila de informe para el CSV: las referencias, por su nombre."""
    salida: dict[str, str] = {}
    for clave, valor in fila.model_dump(mode="json").items():
        if isinstance(valor, dict):
            salida[clave] = str(valor.get("name") or valor.get("id") or "")
        elif isinstance(valor, list):
            continue
        else:
            salida[clave] = "" if valor is None else str(valor)
    return salida


def csv_de(nombre: str, filas: list[Any]) -> Response:
    """CSV en un solo cuerpo, sin paginación, como pide §3.19."""
    planas = [_plano(fila) for fila in filas]
    memoria = io.StringIO()
    if planas:
        escritor = csv.DictWriter(memoria, fieldnames=list(planas[0]), delimiter=";")
        escritor.writeheader()
        escritor.writerows(planas)
    return Response(
        content=memoria.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}.csv"'},
    )


def sellar(respuesta: Response, cuerpo: BaseModel) -> None:
    """`ETag` de todos los informes, calculado sobre el cuerpo ya serializado."""
    huella = hashlib.sha256(cuerpo.model_dump_json().encode("utf-8")).hexdigest()[:32]
    respuesta.headers["ETag"] = f'W/"{huella}"'
    respuesta.headers["Cache-Control"] = "private, max-age=30"


def _pct(parte: Decimal, total: Decimal) -> float:
    if not total:
        return 0.0
    return float((parte / total * 100).quantize(CENTIMO))


def _variacion(anterior: Decimal | None, actual: Decimal) -> float | None:
    if anterior is None or anterior == 0:
        return None
    proporcion = precios.variacion(anterior, actual)
    return None if proporcion is None else float((proporcion * 100).quantize(CENTIMO))


# --------------------------------------------------------------------------- #
# Consultas base
# --------------------------------------------------------------------------- #


def _gasto(
    household_id: uuidlib.UUID,
    rango: Rango,
    *,
    tipo: str = "expense",
    cuentas: list[uuidlib.UUID] | None = None,
) -> Select:
    """Movimientos de gasto o de ingreso, ya sin transferencias (RN-21)."""
    consulta = select(MOVIMIENTOS).where(
        MOVIMIENTOS.c.household_id == household_id,
        MOVIMIENTOS.c.booked_on >= rango.desde,
        MOVIMIENTOS.c.booked_on <= rango.hasta,
        MOVIMIENTOS.c.kind == tipo,
        MOVIMIENTOS.c.excluded_from_reports.is_(False),
    )
    if cuentas:
        consulta = consulta.where(MOVIMIENTOS.c.account_id.in_(cuentas))
    return consulta


async def _por_categoria(
    alcance: AlcanceHogar,
    rango: Rango,
    *,
    cuentas: list[uuidlib.UUID] | None = None,
    etiquetas: list[uuidlib.UUID] | None = None,
) -> tuple[dict[uuidlib.UUID | None, Decimal], dict[uuidlib.UUID | None, int]]:
    """Gastado y número de movimientos por temática."""
    base = _gasto(alcance.household_id, rango, cuentas=cuentas).subquery()
    consulta = select(
        base.c.category_id,
        func.coalesce(func.sum(base.c.spent), 0),
        func.count(func.distinct(base.c.transaction_id)),
    ).group_by(base.c.category_id)
    if etiquetas:
        from app.models.transaccion import TransactionTag

        con_etiqueta = select(TransactionTag.transaction_id).where(
            TransactionTag.household_id == alcance.household_id,
            TransactionTag.tag_id.in_(etiquetas),
        )
        consulta = consulta.where(base.c.transaction_id.in_(con_etiqueta))

    importes: dict[uuidlib.UUID | None, Decimal] = {}
    cuantos: dict[uuidlib.UUID | None, int] = {}
    for fila in (await alcance.sesion.execute(consulta)).all():
        importes[fila[0]] = Decimal(fila[1]).quantize(CENTIMO)
        cuantos[fila[0]] = fila[2]
    return importes, cuantos


async def _arbol(alcance: AlcanceHogar) -> dict[uuidlib.UUID, Category]:
    filas = (
        await alcance.sesion.execute(
            select(Category).where(Category.household_id == alcance.household_id)
        )
    ).scalars()
    return {categoria.id: categoria for categoria in filas}


def _ref_categoria(categoria: Category) -> CategoriaRefRespuesta:
    return CategoriaRefRespuesta(id=categoria.id, name=categoria.name, color=categoria.color_hex)


async def _asignado(alcance: AlcanceHogar, rango: Rango) -> dict[uuidlib.UUID, Decimal]:
    """Presupuesto asignado por temática en los periodos del rango."""
    filas = (
        await alcance.sesion.execute(
            select(
                BudgetAllocation.category_id,
                func.sum(BudgetAllocation.allocated_amount + BudgetAllocation.carryover_in),
            )
            .join(BudgetPeriod, BudgetPeriod.id == BudgetAllocation.budget_period_id)
            .where(
                BudgetAllocation.household_id == alcance.household_id,
                BudgetPeriod.period_month >= inicio_de(rango.periodo_desde),
                BudgetPeriod.period_month <= inicio_de(rango.periodo_hasta),
            )
            .group_by(BudgetAllocation.category_id)
        )
    ).all()
    return {fila[0]: Decimal(fila[1]).quantize(CENTIMO) for fila in filas}


# --------------------------------------------------------------------------- #
# 1. Gasto por temática (F-18)
# --------------------------------------------------------------------------- #


@router.get(
    "/reports/spending-by-category",
    tags=["reports"],
    response_model=None,
    summary="Gasto por temática",
)
async def gasto_por_tematica(
    alcance: Alcance,
    respuesta: Response,
    filtro: Annotated[GastoPorTematicaFiltro, Query()],
) -> Any:
    """F-18: importe, porcentaje, presupuesto y comparación con el periodo anterior."""
    rango = rango_de(filtro)
    arbol = await _arbol(alcance)
    importes, cuantos = await _por_categoria(
        alcance, rango, cuentas=filtro.account_id, etiquetas=filtro.tag_id
    )
    previos, _ = await _por_categoria(
        alcance, rango.anterior(), cuentas=filtro.account_id, etiquetas=filtro.tag_id
    )
    asignado = await _asignado(alcance, rango)

    if filtro.category_id:
        elegida = arbol.get(filtro.category_id)
        if elegida is None:
            raise ReglaDeNegocio("Esa temática no existe.", codigo="no_encontrado", estado=404)

    def antecesor(category_id: uuidlib.UUID, nivel: int) -> uuidlib.UUID | None:
        """El identificador del ancestro en el nivel pedido (1 = raíz)."""
        categoria = arbol.get(category_id)
        if categoria is None:
            return None
        ruta = list(categoria.path_ids)
        if filtro.category_id and filtro.category_id not in ruta:
            return None
        return ruta[min(nivel, len(ruta)) - 1]

    agregado: dict[uuidlib.UUID, dict[str, Any]] = {}
    sin_clasificar = CERO
    for category_id, importe in importes.items():
        if category_id is None:
            sin_clasificar += importe
            continue
        clave = antecesor(category_id, filtro.depth)
        if clave is None:
            continue
        entrada = agregado.setdefault(clave, {"amount": CERO, "transactions": 0, "previous": CERO})
        entrada["amount"] += importe
        entrada["transactions"] += cuantos.get(category_id, 0)
    for category_id, importe in previos.items():
        if category_id is None:
            continue
        clave = antecesor(category_id, filtro.depth)
        if clave is not None and clave in agregado:
            agregado[clave]["previous"] += importe

    total = sum((datos["amount"] for datos in agregado.values()), CERO) + sin_clasificar
    filas: list[GastoPorTematicaFilaRespuesta] = []
    for category_id, datos in agregado.items():
        categoria = arbol[category_id]
        if filtro.min_amount is not None and datos["amount"] < filtro.min_amount:
            continue
        asignada = asignado.get(category_id)
        filas.append(
            GastoPorTematicaFilaRespuesta(
                category=_ref_categoria(categoria),
                depth=categoria.depth,
                parent_id=categoria.parent_id,
                amount=datos["amount"],
                share_pct=_pct(datos["amount"], total),
                transactions=datos["transactions"],
                allocated=asignada,
                variance=(asignada - datos["amount"]) if asignada is not None else None,
                previous_amount=datos["previous"] or None,
                change_pct=_variacion(datos["previous"] or None, datos["amount"]),
                children=(
                    _hijas(arbol, category_id, importes, cuantos, asignado, total)
                    if filtro.include_children
                    else []
                ),
            )
        )
    filas.sort(key=lambda fila: fila.amount, reverse=True)

    cuerpo = GastoPorTematicaRespuesta(
        period_from=rango.periodo_desde,
        period_to=rango.periodo_hasta,
        total=total,
        uncategorized=sin_clasificar,
        rows=filas,
    )
    if filtro.format == "csv":
        return csv_de("gasto-por-tematica", filas)
    sellar(respuesta, cuerpo)
    return cuerpo


def _hijas(
    arbol: dict[uuidlib.UUID, Category],
    padre: uuidlib.UUID,
    importes: dict[uuidlib.UUID | None, Decimal],
    cuantos: dict[uuidlib.UUID | None, int],
    asignado: dict[uuidlib.UUID, Decimal],
    total: Decimal,
) -> list[GastoPorTematicaFilaRespuesta]:
    """Desglose del subárbol de una temática, un nivel por vuelta."""
    filas = []
    for categoria in arbol.values():
        if categoria.parent_id != padre:
            continue
        descendientes = sum(
            (
                importe
                for identificador, importe in importes.items()
                if identificador is not None
                and identificador in arbol
                and categoria.id in arbol[identificador].path_ids
            ),
            CERO,
        )
        if not descendientes:
            continue
        filas.append(
            GastoPorTematicaFilaRespuesta(
                category=_ref_categoria(categoria),
                depth=categoria.depth,
                parent_id=categoria.parent_id,
                amount=descendientes,
                share_pct=_pct(descendientes, total),
                transactions=cuantos.get(categoria.id, 0),
                allocated=asignado.get(categoria.id),
                children=_hijas(arbol, categoria.id, importes, cuantos, asignado, total),
            )
        )
    return sorted(filas, key=lambda fila: fila.amount, reverse=True)


# --------------------------------------------------------------------------- #
# 2. Mes a mes (F-19)
# --------------------------------------------------------------------------- #


class ComparativaMensualFiltro(ParametrosInforme):
    """`GET /reports/monthly-comparison`: §3.19 admite `category_id*` y `kind`.

    El contrato no le dedica un esquema en §4.12, así que se declara aquí: un
    modelo de consulta no se puede mezclar con parámetros sueltos en la misma
    firma, y los informes tienen que aceptar todos sus filtros.
    """

    category_id: list[uuidlib.UUID] = Field(default=[])
    kind: Literal["expense", "income"] = "expense"


@router.get(
    "/reports/monthly-comparison",
    tags=["reports"],
    response_model=None,
    summary="Comparativa mes a mes",
)
async def comparativa_mensual(
    alcance: Alcance,
    respuesta: Response,
    filtro: Annotated[ComparativaMensualFiltro, Query()],
) -> Any:
    """F-19: serie del gasto total y por temática entre dos periodos."""
    rango = rango_de(filtro, meses=MESES_POR_DEFECTO)
    base = _gasto(alcance.household_id, rango).subquery()
    ingresos = _gasto(alcance.household_id, rango, tipo="income").subquery()

    consulta = select(base.c.period_month, base.c.category_id, func.sum(base.c.spent)).group_by(
        base.c.period_month, base.c.category_id
    )
    if filtro.category_id:
        consulta = consulta.where(base.c.category_id.in_(filtro.category_id))

    gasto: dict[str, Decimal] = defaultdict(lambda: CERO)
    por_tematica: dict[str, dict[str, Decimal]] = defaultdict(dict)
    for fila in (await alcance.sesion.execute(consulta)).all():
        periodo = periodo_de(fila[0])
        importe = Decimal(fila[2]).quantize(CENTIMO)
        gasto[periodo] += importe
        if fila[1] is not None:
            por_tematica[periodo][str(fila[1])] = importe

    entradas: dict[str, Decimal] = defaultdict(lambda: CERO)
    for fila in (
        await alcance.sesion.execute(
            select(ingresos.c.period_month, func.sum(ingresos.c.amount)).group_by(
                ingresos.c.period_month
            )
        )
    ).all():
        entradas[periodo_de(fila[0])] = Decimal(fila[1]).quantize(CENTIMO)

    serie = [
        PuntoMensualRespuesta(
            period=periodo,
            expense=gasto.get(periodo, CERO),
            income=entradas.get(periodo, CERO),
            net=(entradas.get(periodo, CERO) - gasto.get(periodo, CERO)),
            by_category=por_tematica.get(periodo, {}),
        )
        for periodo in periodos_entre(rango.periodo_desde, rango.periodo_hasta)
    ]
    media = (
        (sum((punto.expense for punto in serie), CERO) / len(serie)).quantize(CENTIMO)
        if serie
        else CERO
    )
    con_gasto = [punto for punto in serie if punto.expense > 0]
    cuerpo = ComparativaMensualRespuesta(
        periods=[punto.period for punto in serie],
        series=serie,
        average_expense=media,
        best_period=min(con_gasto, key=lambda p: p.expense).period if con_gasto else None,
        worst_period=max(con_gasto, key=lambda p: p.expense).period if con_gasto else None,
    )
    if filtro.format == "csv":
        return csv_de("mes-a-mes", serie)
    sellar(respuesta, cuerpo)
    return cuerpo


# --------------------------------------------------------------------------- #
# 3. Cash flow (F-36)
# --------------------------------------------------------------------------- #


@router.get("/reports/cash-flow", tags=["reports"], response_model=None, summary="Cash flow")
async def cash_flow(
    alcance: Alcance, respuesta: Response, filtro: Annotated[CashFlowFiltro, Query()]
) -> Any:
    """F-36: entradas, salidas y neto por periodo, con acumulado."""
    rango = rango_de(filtro, meses=MESES_POR_DEFECTO)
    tramo = (
        func.date_trunc("week", MOVIMIENTOS.c.booked_on)
        if filtro.granularity == "week"
        else func.date_trunc("month", MOVIMIENTOS.c.booked_on)
    )
    consulta = (
        select(
            tramo.label("tramo"),
            func.sum(func.greatest(MOVIMIENTOS.c.amount, 0)).label("entradas"),
            func.sum(func.least(MOVIMIENTOS.c.amount, 0)).label("salidas"),
        )
        .where(
            MOVIMIENTOS.c.household_id == alcance.household_id,
            MOVIMIENTOS.c.booked_on >= rango.desde,
            MOVIMIENTOS.c.booked_on <= rango.hasta,
            MOVIMIENTOS.c.kind != "transfer",
            MOVIMIENTOS.c.excluded_from_reports.is_(False),
        )
        .group_by(tramo)
        .order_by(tramo)
    )
    if filtro.account_id:
        consulta = consulta.where(MOVIMIENTOS.c.account_id.in_(filtro.account_id))

    puntos: list[PuntoCashFlowRespuesta] = []
    acumulado = CERO
    entradas_totales = CERO
    salidas_totales = CERO
    for fila in (await alcance.sesion.execute(consulta)).all():
        entrada = Decimal(fila.entradas or 0).quantize(CENTIMO)
        salida = abs(Decimal(fila.salidas or 0)).quantize(CENTIMO)
        neto = entrada - salida
        acumulado += neto
        entradas_totales += entrada
        salidas_totales += salida
        etiqueta = (
            fila.tramo.date().isoformat()
            if filtro.granularity == "week"
            else periodo_de(fila.tramo.date())
        )
        puntos.append(
            PuntoCashFlowRespuesta(
                period=etiqueta,
                inflow=entrada,
                outflow=salida,
                net=neto,
                cumulative=acumulado,
            )
        )

    neto_total = entradas_totales - salidas_totales
    cuerpo = CashFlowRespuesta(
        granularity=filtro.granularity,
        points=puntos,
        total_inflow=entradas_totales,
        total_outflow=salidas_totales,
        net=neto_total,
        savings_rate=float((neto_total / entradas_totales).quantize(Decimal("0.0001")))
        if entradas_totales
        else 0.0,
    )
    if filtro.format == "csv":
        return csv_de("cash-flow", puntos)
    sellar(respuesta, cuerpo)
    return cuerpo


# --------------------------------------------------------------------------- #
# 4. Top comercios (F-37)
# --------------------------------------------------------------------------- #


@router.get("/reports/top-payees", tags=["reports"], response_model=None, summary="Top comercios")
async def top_comercios(
    alcance: Alcance, respuesta: Response, filtro: Annotated[TopComerciosFiltro, Query()]
) -> Any:
    """F-37: ranking por gasto con número de operaciones y ticket medio."""
    rango = rango_de(filtro)
    actual = await _por_comercio(alcance, rango, filtro.category_id)
    previo = await _por_comercio(alcance, rango.anterior(), filtro.category_id)
    comercios = {
        comercio.id: comercio
        for comercio in (
            await alcance.sesion.execute(
                select(Payee).where(Payee.household_id == alcance.household_id)
            )
        ).scalars()
    }
    arbol = await _arbol(alcance)
    total = sum((datos["amount"] for datos in actual.values()), CERO)

    filas: list[TopComercioFilaRespuesta] = []
    for payee_id, datos in actual.items():
        anterior = previo.get(payee_id, {}).get("amount")
        principal = datos["top_category"]
        filas.append(
            TopComercioFilaRespuesta(
                payee=ref_comercio(comercios.get(payee_id)) if payee_id else None,
                amount=datos["amount"],
                transactions=datos["transactions"],
                average_ticket=(datos["amount"] / datos["transactions"]).quantize(CENTIMO)
                if datos["transactions"]
                else CERO,
                share_pct=_pct(datos["amount"], total),
                top_category=(
                    _ref_categoria(arbol[principal])
                    if principal is not None and principal in arbol
                    else None
                ),
                previous_amount=anterior,
                change_pct=_variacion(anterior, datos["amount"]),
            )
        )
    filas.sort(key=lambda fila: fila.amount, reverse=True)
    filas = filas[: filtro.limit]

    cuerpo = TopComerciosRespuesta(
        period_from=rango.periodo_desde,
        period_to=rango.periodo_hasta,
        total=total,
        rows=filas,
    )
    if filtro.format == "csv":
        return csv_de("top-comercios", filas)
    sellar(respuesta, cuerpo)
    return cuerpo


async def _por_comercio(
    alcance: AlcanceHogar, rango: Rango, category_id: uuidlib.UUID | None
) -> dict[Any, dict[str, Any]]:
    base = _gasto(alcance.household_id, rango).subquery()
    consulta = select(
        base.c.payee_id,
        base.c.category_id,
        func.sum(base.c.spent),
        func.count(func.distinct(base.c.transaction_id)),
    ).group_by(base.c.payee_id, base.c.category_id)
    if category_id:
        consulta = consulta.where(base.c.category_id == category_id)

    resumen: dict[Any, dict[str, Any]] = {}
    for fila in (await alcance.sesion.execute(consulta)).all():
        entrada = resumen.setdefault(
            fila[0], {"amount": CERO, "transactions": 0, "top_category": None, "mayor": CERO}
        )
        importe = Decimal(fila[2]).quantize(CENTIMO)
        entrada["amount"] += importe
        entrada["transactions"] += fila[3]
        if importe > entrada["mayor"]:
            entrada["mayor"] = importe
            entrada["top_category"] = fila[1]
    return resumen


# --------------------------------------------------------------------------- #
# 5. Patrimonio neto (F-11)
# --------------------------------------------------------------------------- #


@router.get("/reports/net-worth", tags=["reports"], response_model=None, summary="Patrimonio neto")
async def patrimonio(
    alcance: Alcance, respuesta: Response, filtro: Annotated[PatrimonioFiltro, Query()]
) -> Any:
    """F-11: serie mensual de activos, pasivos y neto (RN-25)."""
    rango = rango_de(filtro, meses=MESES_POR_DEFECTO)
    cuentas = list(
        (
            await alcance.sesion.execute(
                select(Account).where(
                    Account.household_id == alcance.household_id,
                    Account.include_in_net_worth.is_(True),
                )
            )
        ).scalars()
    )
    mes = func.date_trunc("month", Transaction.booked_on)
    movimientos = (
        await alcance.sesion.execute(
            select(Transaction.account_id, mes, func.sum(Transaction.amount))
            .where(Transaction.household_id == alcance.household_id)
            .group_by(Transaction.account_id, mes)
        )
    ).all()
    por_cuenta: dict[Any, dict[str, Decimal]] = defaultdict(dict)
    for fila in movimientos:
        por_cuenta[fila[0]][periodo_de(fila[1].date())] = Decimal(fila[2]).quantize(CENTIMO)

    puntos: list[PuntoPatrimonioRespuesta] = []
    anterior_neto: Decimal | None = None
    todos = periodos_entre(rango.periodo_desde, rango.periodo_hasta)
    for periodo in todos:
        activos = CERO
        pasivos = CERO
        for cuenta in cuentas:
            saldo = cuenta.opening_balance
            for otro, importe in por_cuenta.get(cuenta.id, {}).items():
                if otro <= periodo:
                    saldo += importe
            if TipoCuenta(cuenta.type) in TIPOS_PASIVO:
                pasivos += -saldo
            else:
                activos += saldo
        neto = (activos - pasivos).quantize(CENTIMO)
        puntos.append(
            PuntoPatrimonioRespuesta(
                period=periodo,
                assets=activos.quantize(CENTIMO),
                liabilities=pasivos.quantize(CENTIMO),
                net_worth=neto,
                change=(neto - anterior_neto) if anterior_neto is not None else CERO,
                change_pct=_variacion(anterior_neto, neto),
            )
        )
        anterior_neto = neto

    detalle: list[PatrimonioCuentaRespuesta] = []
    if filtro.include_accounts:
        saldos = {
            fila.account_id: fila
            for fila in (
                await alcance.sesion.execute(
                    select(SALDOS).where(SALDOS.c.household_id == alcance.household_id)
                )
            ).all()
        }
        for cuenta in cuentas:
            fila = saldos.get(cuenta.id)
            valor = Decimal(fila.net_worth_value) if fila else cuenta.opening_balance
            detalle.append(
                PatrimonioCuentaRespuesta(
                    account=CuentaRefRespuesta(
                        id=cuenta.id,
                        name=cuenta.name,
                        type=TipoCuenta(cuenta.type),
                        currency=cuenta.currency,
                    ),
                    type=TipoCuenta(cuenta.type),
                    balance=valor.quantize(CENTIMO),
                    is_liability=TipoCuenta(cuenta.type) in TIPOS_PASIVO,
                )
            )

    cuerpo = PatrimonioRespuesta(
        points=puntos,
        current=puntos[-1].net_worth if puntos else CERO,
        change_12m=(puntos[-1].net_worth - puntos[0].net_worth) if len(puntos) > 1 else None,
        by_account=detalle,
    )
    if filtro.format == "csv":
        return csv_de("patrimonio-neto", puntos)
    sellar(respuesta, cuerpo)
    return cuerpo


# --------------------------------------------------------------------------- #
# 6. Presupuestado frente a real
# --------------------------------------------------------------------------- #


@router.get(
    "/reports/budget-vs-actual",
    tags=["reports"],
    response_model=None,
    summary="Presupuestado frente a real",
)
async def presupuesto_vs_real(
    alcance: Alcance, respuesta: Response, filtro: Annotated[PresupuestoVsRealFiltro, Query()]
) -> Any:
    rango = rango_de(filtro)
    arbol = await _arbol(alcance)
    asignaciones = (
        await alcance.sesion.execute(
            select(
                BudgetPeriod.period_month,
                BudgetAllocation.category_id,
                BudgetAllocation.allocated_amount + BudgetAllocation.carryover_in,
            )
            .join(BudgetPeriod, BudgetPeriod.id == BudgetAllocation.budget_period_id)
            .where(
                BudgetAllocation.household_id == alcance.household_id,
                BudgetPeriod.period_month >= inicio_de(rango.periodo_desde),
                BudgetPeriod.period_month <= inicio_de(rango.periodo_hasta),
            )
        )
    ).all()
    base = _gasto(alcance.household_id, rango).subquery()
    gastado = {
        (periodo_de(fila[0]), fila[1]): Decimal(fila[2]).quantize(CENTIMO)
        for fila in (
            await alcance.sesion.execute(
                select(base.c.period_month, base.c.category_id, func.sum(base.c.spent)).group_by(
                    base.c.period_month, base.c.category_id
                )
            )
        ).all()
    }

    filas: list[PresupuestoVsRealFilaRespuesta] = []
    for periodo_mes, category_id, importe in asignaciones:
        if category_id not in arbol:
            continue
        periodo = periodo_de(periodo_mes)
        asignado = Decimal(importe).quantize(CENTIMO)
        real = gastado.get((periodo, category_id), CERO)
        sobrepasa = real > asignado
        if filtro.only_overspent and not sobrepasa:
            continue
        filas.append(
            PresupuestoVsRealFilaRespuesta(
                period=periodo,
                category=_ref_categoria(arbol[category_id]),
                allocated=asignado,
                spent=real,
                variance=(asignado - real),
                used_pct=_pct(real, asignado) if asignado else 0.0,
                is_overspent=sobrepasa,
            )
        )
    filas.sort(key=lambda fila: (fila.period, -fila.spent))

    cuerpo = PresupuestoVsRealRespuesta(
        period_from=rango.periodo_desde,
        period_to=rango.periodo_hasta,
        allocated_total=sum((fila.allocated for fila in filas), CERO),
        spent_total=sum((fila.spent for fila in filas), CERO),
        variance_total=sum((fila.variance for fila in filas), CERO),
        overspent_categories=sum(1 for fila in filas if fila.is_overspent),
        rows=filas,
    )
    if filtro.format == "csv":
        return csv_de("presupuesto-vs-real", filas)
    sellar(respuesta, cuerpo)
    return cuerpo


# --------------------------------------------------------------------------- #
# 7. Evolución del precio de un producto (F-15)
# --------------------------------------------------------------------------- #


@router.get(
    "/reports/product-price",
    tags=["reports"],
    response_model=None,
    summary="Evolución del precio de un producto",
)
async def precio_de_producto(
    alcance: Alcance, respuesta: Response, filtro: Annotated[PrecioProductoFiltro, Query()]
) -> Any:
    """F-15: serie por fecha, media móvil y variación acumulada."""
    producto = await _producto_o_404(alcance, filtro.product_id)
    rango = rango_de(filtro, meses=MESES_POR_DEFECTO)
    historial = await puntos_por_producto(
        alcance.sesion,
        alcance.household_id,
        [producto.id],
        desde=rango.desde if (filtro.date_from or filtro.period or filtro.period_from) else None,
        hasta=rango.hasta if (filtro.date_to or filtro.period or filtro.period_to) else None,
        payee_ids=filtro.payee_id or None,
    )
    puntos = historial.get(producto.id, [])
    comercios = await comercios_por_nombre(alcance.sesion, alcance.household_id)
    por_nombre = {comercio.name: comercio for comercio in comercios.values()}

    serie: list[PuntoPrecioProductoRespuesta] = []
    ventana: list[Decimal] = []
    anterior: Decimal | None = None
    for punto in puntos:
        ventana.append(punto.precio)
        ventana = ventana[-3:]
        media = (sum(ventana) / len(ventana)).quantize(Decimal("0.0001"))
        serie.append(
            PuntoPrecioProductoRespuesta(
                observed_at=punto.fecha,
                unit_price=punto.precio,
                payee=ref_comercio(por_nombre.get(punto.comercio or "")),
                invoice_id=uuidlib.UUID(punto.factura_id) if punto.factura_id else None,
                change_pct=_variacion(anterior, punto.precio),
                moving_average=media,
            )
        )
        anterior = punto.precio

    cuerpo = PrecioProductoRespuesta(
        product=ref_producto(producto),
        unit=producto.unit,
        points=serie,
        stats=estadisticas_de(producto.id, puntos),
        by_payee=comparativa_por_comercio(puntos, comercios),
        comparison=await comparativa_de(alcance, producto),
    )
    if filtro.format == "csv":
        return csv_de(f"precio-{producto.id}", serie)
    sellar(respuesta, cuerpo)
    return cuerpo


# --------------------------------------------------------------------------- #
# 8. Subidas de precio detectadas (F-16)
# --------------------------------------------------------------------------- #


@router.get(
    "/reports/price-increases",
    tags=["reports"],
    response_model=None,
    summary="Subidas de precio detectadas",
)
async def subidas_de_precio(
    alcance: Alcance, respuesta: Response, filtro: Annotated[SubidasPrecioFiltro, Query()]
) -> Any:
    """F-16: ordenadas por impacto en euros, no por porcentaje."""
    rango = rango_de(filtro, meses=3)
    consulta = (
        select(ProductPrice, Product, Payee)
        .join(Product, Product.id == ProductPrice.product_id)
        .join(Payee, Payee.id == ProductPrice.payee_id, isouter=True)
        .where(
            ProductPrice.household_id == alcance.household_id,
            ProductPrice.priced_on >= rango.desde,
            ProductPrice.priced_on <= rango.hasta,
            ProductPrice.change_pct.is_not(None),
            ProductPrice.change_pct >= Decimal(str(filtro.min_change_pct)),
        )
        .order_by(ProductPrice.change_pct.desc())
    )
    if filtro.payee_id:
        consulta = consulta.where(ProductPrice.payee_id == filtro.payee_id)
    if filtro.category_id:
        consulta = consulta.where(Product.category_id == filtro.category_id)

    filas: list[SubidaPrecioFilaRespuesta] = []
    impacto_total = CERO
    for observacion, producto, comercio in (await alcance.sesion.execute(consulta)).all():
        cambio = Decimal(observacion.change_pct)
        previa = await ultima_observacion(
            alcance.sesion,
            alcance.household_id,
            producto.id,
            payee_id=observacion.payee_id,
            antes_de=observacion.priced_on,
            excluir=observacion.id,
        )
        # Despejar el precio anterior del porcentaje perdería decimales: se lee.
        anterior = (
            previa.unit_price
            if previa is not None
            else (observacion.unit_price / (1 + cambio / 100)).quantize(Decimal("0.0001"))
        )
        cantidad = observacion.quantity or Decimal(1)
        impacto = ((observacion.unit_price - anterior) * cantidad).quantize(CENTIMO)
        impacto_total += impacto
        filas.append(
            SubidaPrecioFilaRespuesta(
                product=ref_producto(producto),
                payee=ref_comercio(comercio),
                previous_unit_price=anterior,
                new_unit_price=observacion.unit_price,
                change_pct=float(cambio),
                observed_at=observacion.priced_on,
                typical_quantity=cantidad,
                estimated_monthly_impact=impacto,
            )
        )
    filas.sort(key=lambda fila: fila.estimated_monthly_impact or CERO, reverse=True)

    cuerpo = SubidasPrecioRespuesta(
        period_from=rango.periodo_desde,
        period_to=rango.periodo_hasta,
        min_change_pct=filtro.min_change_pct,
        total_estimated_impact=impacto_total,
        rows=filas,
    )
    if filtro.format == "csv":
        return csv_de("subidas-de-precio", filas)
    sellar(respuesta, cuerpo)
    return cuerpo


# --------------------------------------------------------------------------- #
# 9. Cesta de la compra (F-60)
# --------------------------------------------------------------------------- #


@router.get("/reports/basket", tags=["reports"], response_model=None, summary="Cesta comparada")
async def cesta(
    alcance: Alcance, respuesta: Response, filtro: Annotated[CestaFiltro, Query()]
) -> Any:
    """F-60: coste de la misma cesta en cada comercio, con cobertura."""
    productos = await productos_de_cesta(alcance, list(filtro.product_id))
    if not productos:
        raise ReglaDeNegocio(
            "Indica los productos de la cesta o marca alguno como habitual.",
            codigo="datos_invalidos",
        )
    cuerpo: CestaInformeRespuesta = await comparar_cesta_de(
        alcance, productos, meses=filtro.months, basket_id=filtro.basket_id
    )
    if filtro.format == "csv":
        return csv_de("cesta", cuerpo.by_payee)
    sellar(respuesta, cuerpo)
    return cuerpo


# --------------------------------------------------------------------------- #
# 10. Suscripciones (F-29, F-30)
# --------------------------------------------------------------------------- #


@router.get(
    "/reports/subscriptions", tags=["reports"], response_model=None, summary="Suscripciones"
)
async def suscripciones(
    alcance: Alcance, respuesta: Response, filtro: Annotated[SuscripcionesFiltro, Query()]
) -> Any:
    consulta = select(RecurringRule).where(
        RecurringRule.household_id == alcance.household_id,
        RecurringRule.is_subscription.is_(True),
    )
    if filtro.is_active is not None:
        consulta = consulta.where(
            RecurringRule.status == "active"
            if filtro.is_active
            else RecurringRule.status != "active"
        )
    reglas = list((await alcance.sesion.execute(consulta)).scalars())
    comercios = {
        comercio.id: comercio
        for comercio in (
            await alcance.sesion.execute(
                select(Payee).where(Payee.household_id == alcance.household_id)
            )
        ).scalars()
    }
    arbol = await _arbol(alcance)

    hace_un_anyo = date.today() - timedelta(days=365)
    subidas = {
        fila[0]
        for fila in (
            await alcance.sesion.execute(
                select(RecurringOccurrence.recurring_rule_id)
                .where(
                    RecurringOccurrence.household_id == alcance.household_id,
                    RecurringOccurrence.due_on >= hace_un_anyo,
                    RecurringOccurrence.amount_change_pct.is_not(None),
                    RecurringOccurrence.amount_change_pct > 0,
                )
                .distinct()
            )
        ).all()
    }

    filas: list[SuscripcionFilaRespuesta] = []
    mensual_total = CERO
    for regla in reglas:
        factor = MESES_DE_FRECUENCIA.get(regla.frequency, Decimal(1))
        mensual = (abs(regla.expected_amount) * factor).quantize(CENTIMO)
        mensual_total += mensual
        cambio = None
        if regla.last_amount and regla.expected_amount:
            cambio = _variacion(abs(regla.expected_amount), abs(regla.last_amount))
        filas.append(
            SuscripcionFilaRespuesta(
                recurring_id=regla.id,
                name=regla.name,
                payee=ref_comercio(comercios.get(regla.payee_id)) if regla.payee_id else None,
                category=(
                    _ref_categoria(arbol[regla.category_id]) if regla.category_id in arbol else None
                ),
                frequency=Frecuencia(regla.frequency),
                amount=abs(regla.expected_amount).quantize(CENTIMO),
                monthly_cost=mensual,
                annual_cost=(mensual * 12).quantize(CENTIMO),
                next_occurrence_on=regla.next_due_on,
                price_change_pct=cambio,
                increased_last_year=regla.id in subidas,
                is_active=regla.status == "active",
            )
        )
    filas.sort(key=lambda fila: fila.monthly_cost, reverse=True)

    cuerpo = SuscripcionesRespuesta(
        monthly_total=mensual_total,
        annual_total=(mensual_total * 12).quantize(CENTIMO),
        active=sum(1 for fila in filas if fila.is_active),
        increases_last_year=sum(1 for fila in filas if fila.increased_last_year),
        rows=filas,
    )
    if filtro.format == "csv":
        return csv_de("suscripciones", filas)
    sellar(respuesta, cuerpo)
    return cuerpo


# --------------------------------------------------------------------------- #
# 11. Saldo proyectado a fin de mes (F-47)
# --------------------------------------------------------------------------- #


@router.get(
    "/reports/projected-balance",
    tags=["reports"],
    response_model=None,
    summary="Saldo proyectado a fin de mes",
)
async def saldo_proyectado(
    alcance: Alcance, respuesta: Response, filtro: Annotated[SaldoProyectadoFiltro, Query()]
) -> Any:
    """F-47: saldo actual + recurrentes pendientes − presupuesto restante."""
    rango = rango_de(filtro)
    hoy = date.today()
    consulta = select(Account).where(
        Account.household_id == alcance.household_id, Account.archived_at.is_(None)
    )
    if filtro.account_id:
        consulta = consulta.where(Account.id.in_(filtro.account_id))
    cuentas = list((await alcance.sesion.execute(consulta)).scalars())

    saldos = {
        fila.account_id: Decimal(fila.working_balance)
        for fila in (
            await alcance.sesion.execute(
                select(SALDOS).where(SALDOS.c.household_id == alcance.household_id)
            )
        ).all()
    }
    pendientes = {
        fila[0]: abs(Decimal(fila[1])).quantize(CENTIMO)
        for fila in (
            await alcance.sesion.execute(
                select(RecurringRule.account_id, func.sum(RecurringRule.expected_amount))
                .where(
                    RecurringRule.household_id == alcance.household_id,
                    RecurringRule.status == "active",
                    RecurringRule.next_due_on.is_not(None),
                    RecurringRule.next_due_on <= rango.hasta,
                    RecurringRule.next_due_on >= hoy,
                )
                .group_by(RecurringRule.account_id)
            )
        ).all()
    }
    asignado = await _asignado(alcance, rango)
    gastado, _ = await _por_categoria(alcance, rango)
    restante = sum(
        (
            max(CERO, importe - gastado.get(category_id, CERO))
            for category_id, importe in asignado.items()
        ),
        CERO,
    )
    reparto = (restante / len(cuentas)).quantize(CENTIMO) if cuentas else CERO

    filas: list[SaldoProyectadoFilaRespuesta] = []
    for cuenta in cuentas:
        actual = saldos.get(cuenta.id, cuenta.opening_balance).quantize(CENTIMO)
        recurrente = pendientes.get(cuenta.id, CERO)
        proyectado = (actual - recurrente - reparto).quantize(CENTIMO)
        filas.append(
            SaldoProyectadoFilaRespuesta(
                account=CuentaRefRespuesta(
                    id=cuenta.id,
                    name=cuenta.name,
                    type=TipoCuenta(cuenta.type),
                    currency=cuenta.currency,
                ),
                current_balance=actual,
                pending_recurring=recurrente,
                remaining_budget=reparto,
                projected_balance=proyectado,
                will_be_negative=proyectado < 0,
            )
        )

    cuerpo = SaldoProyectadoRespuesta(
        period=rango.periodo_hasta,
        as_of=hoy,
        rows=filas,
        total_projected=sum((fila.projected_balance for fila in filas), CERO),
    )
    if filtro.format == "csv":
        return csv_de("saldo-proyectado", filas)
    sellar(respuesta, cuerpo)
    return cuerpo


# --------------------------------------------------------------------------- #
# 12. Gasto inusual (F-48)
# --------------------------------------------------------------------------- #


def _respuesta_transaccion(transaccion: Transaction) -> TransaccionRespuesta:
    """La transacción tal y como la devuelve su propio grupo de endpoints."""
    return TransaccionRespuesta(
        id=transaccion.id,
        created_at=transaccion.created_at,
        updated_at=transaccion.updated_at,
        kind=transaccion.kind,  # type: ignore[arg-type]
        account_id=transaccion.account_id,
        date=transaccion.booked_on,
        amount=transaccion.amount,
        signed_amount=transaccion.amount,
        currency=transaccion.currency,
        category_id=transaccion.category_id,
        payee_id=transaccion.payee_id,
        description=transaccion.description or None,
        note=transaccion.notes,
        is_split=transaccion.split_count > 0,
        status=transaccion.status,  # type: ignore[arg-type]
        is_reconciled=transaccion.status == "reconciled",
        is_anomaly=True,
        categorized_by=transaccion.categorized_by,  # type: ignore[arg-type]
    )


@router.get("/reports/anomalies", tags=["reports"], response_model=None, summary="Gasto inusual")
async def anomalias(
    alcance: Alcance, respuesta: Response, filtro: Annotated[AnomaliasFiltro, Query()]
) -> Any:
    """F-48: transacciones que se salen de la media histórica de su temática."""
    rango = rango_de(filtro)
    arbol = await _arbol(alcance)
    comercios = {
        comercio.id: comercio
        for comercio in (
            await alcance.sesion.execute(
                select(Payee).where(Payee.household_id == alcance.household_id)
            )
        ).scalars()
    }

    # La referencia es todo el histórico de la temática, no solo el periodo.
    estadisticas = {
        fila[0]: (Decimal(fila[1]), Decimal(fila[2] or 0))
        for fila in (
            await alcance.sesion.execute(
                select(
                    MOVIMIENTOS.c.category_id,
                    func.avg(MOVIMIENTOS.c.spent),
                    func.stddev_pop(MOVIMIENTOS.c.spent),
                )
                .where(
                    MOVIMIENTOS.c.household_id == alcance.household_id,
                    MOVIMIENTOS.c.kind == "expense",
                    MOVIMIENTOS.c.excluded_from_reports.is_(False),
                )
                .group_by(MOVIMIENTOS.c.category_id)
            )
        ).all()
    }

    movimientos = (
        await alcance.sesion.execute(
            _gasto(alcance.household_id, rango).order_by(MOVIMIENTOS.c.booked_on.desc())
        )
    ).all()
    transacciones = {
        transaccion.id: transaccion
        for transaccion in (
            await alcance.sesion.execute(
                select(Transaction).where(
                    Transaction.household_id == alcance.household_id,
                    Transaction.id.in_(
                        [fila.transaction_id for fila in movimientos] or [uuidlib.uuid4()]
                    ),
                )
            )
        ).scalars()
    }

    filas: list[AnomaliaFilaRespuesta] = []
    for fila in movimientos:
        media, desviacion = estadisticas.get(fila.category_id, (CERO, CERO))
        gasto = Decimal(fila.spent)
        if gasto <= 0 or desviacion == 0:
            continue
        z = float(((gasto - media) / desviacion).quantize(Decimal("0.01")))
        if z < filtro.z:
            continue
        if filtro.min_amount is not None and gasto < filtro.min_amount:
            continue
        transaccion = transacciones.get(fila.transaction_id)
        if transaccion is None:
            continue
        nombre = arbol[fila.category_id].name if fila.category_id in arbol else "sin clasificar"
        filas.append(
            AnomaliaFilaRespuesta(
                transaction=_respuesta_transaccion(transaccion),
                category=(
                    _ref_categoria(arbol[fila.category_id]) if fila.category_id in arbol else None
                ),
                payee=ref_comercio(comercios.get(fila.payee_id)) if fila.payee_id else None,
                amount=gasto.quantize(CENTIMO),
                average_amount=media.quantize(CENTIMO),
                z_score=z,
                reason=(
                    f"{euros(gasto)} frente a una media de {euros(media.quantize(CENTIMO))} "
                    f"en {nombre}."
                ),
            )
        )

    cuerpo = AnomaliasRespuesta(
        period_from=rango.periodo_desde, period_to=rango.periodo_hasta, z=filtro.z, rows=filas
    )
    if filtro.format == "csv":
        return csv_de("gasto-inusual", filas)
    sellar(respuesta, cuerpo)
    return cuerpo


# --------------------------------------------------------------------------- #
# 13. Ingresos, gastos y ahorro
# --------------------------------------------------------------------------- #


@router.get(
    "/reports/income-vs-expense",
    tags=["reports"],
    response_model=None,
    summary="Ingresos, gastos y ahorro",
)
async def ingresos_vs_gastos(
    alcance: Alcance, respuesta: Response, filtro: Annotated[ParametrosInforme, Query()]
) -> Any:
    """El encabezado del panel: ingreso, gasto, ahorro y tasa de ahorro."""
    rango = rango_de(filtro, meses=MESES_POR_DEFECTO)
    gasto = _gasto(alcance.household_id, rango).subquery()
    ingreso = _gasto(alcance.household_id, rango, tipo="income").subquery()

    gastos = {
        periodo_de(fila[0]): Decimal(fila[1]).quantize(CENTIMO)
        for fila in (
            await alcance.sesion.execute(
                select(gasto.c.period_month, func.sum(gasto.c.spent)).group_by(gasto.c.period_month)
            )
        ).all()
    }
    ingresos = {
        periodo_de(fila[0]): Decimal(fila[1]).quantize(CENTIMO)
        for fila in (
            await alcance.sesion.execute(
                select(ingreso.c.period_month, func.sum(ingreso.c.amount)).group_by(
                    ingreso.c.period_month
                )
            )
        ).all()
    }

    filas: list[IngresoGastoFilaRespuesta] = []
    for periodo in periodos_entre(rango.periodo_desde, rango.periodo_hasta):
        entrada = ingresos.get(periodo, CERO)
        salida = gastos.get(periodo, CERO)
        ahorro = entrada - salida
        filas.append(
            IngresoGastoFilaRespuesta(
                period=periodo,
                income=entrada,
                expense=salida,
                savings=ahorro,
                savings_rate=float((ahorro / entrada).quantize(Decimal("0.0001")))
                if entrada
                else 0.0,
            )
        )

    entrada_total = sum((fila.income for fila in filas), CERO)
    salida_total = sum((fila.expense for fila in filas), CERO)
    ahorro_total = entrada_total - salida_total
    tasas = [fila.savings_rate for fila in filas if fila.income]
    cuerpo = IngresoGastoRespuesta(
        period_from=rango.periodo_desde,
        period_to=rango.periodo_hasta,
        income_total=entrada_total,
        expense_total=salida_total,
        savings_total=ahorro_total,
        savings_rate=float((ahorro_total / entrada_total).quantize(Decimal("0.0001")))
        if entrada_total
        else 0.0,
        average_savings_rate=round(sum(tasas) / len(tasas), 4) if tasas else None,
        rows=filas,
    )
    if filtro.format == "csv":
        return csv_de("ingresos-vs-gastos", filas)
    sellar(respuesta, cuerpo)
    return cuerpo


# --------------------------------------------------------------------------- #
# Extra: inflación personal
# --------------------------------------------------------------------------- #


class InflacionProductoRespuesta(Respuesta):
    """Un producto de la cesta real con su variación en la ventana."""

    product: Any
    first_unit_price: Any
    last_unit_price: Any
    change_pct: float


class InflacionRespuesta(Respuesta):
    """La inflación de la cesta real de este hogar, no la del INE."""

    date_from: date
    date_to: date
    products: int = Field(description="Productos con observación antes y después.")
    inflation_pct: float | None = None
    message: str | None = None
    rows: list[InflacionProductoRespuesta] = Field(default_factory=list)


@router.get(
    "/reports/personal-inflation",
    tags=["reports"],
    response_model=None,
    summary="Inflación personal",
)
async def inflacion_personal(
    alcance: Alcance, respuesta: Response, filtro: Annotated[ParametrosInforme, Query()]
) -> Any:
    """Variación media de los precios de la cesta real del hogar.

    No es un informe de §3.19 —el contrato no le da hueco— pero
    `precios.inflacion_personal()` existe y es el diferencial del producto, así
    que se expone aquí con la misma forma que los demás.
    """
    rango = rango_de(filtro, meses=MESES_POR_DEFECTO)
    productos = list(
        (
            await alcance.sesion.execute(
                select(Product).where(
                    Product.household_id == alcance.household_id,
                    Product.merged_into_id.is_(None),
                )
            )
        ).scalars()
    )
    historial = await puntos_por_producto(
        alcance.sesion, alcance.household_id, [producto.id for producto in productos]
    )
    variacion = precios.inflacion_personal(list(historial.values()), rango.desde, rango.hasta)

    filas: list[InflacionProductoRespuesta] = []
    for producto in productos:
        puntos = historial.get(producto.id, [])
        antiguos = [punto for punto in puntos if punto.fecha <= rango.desde]
        recientes = [punto for punto in puntos if rango.desde < punto.fecha <= rango.hasta]
        if not antiguos or not recientes:
            continue
        base = max(antiguos, key=lambda punto: punto.fecha).precio
        ultimo = max(recientes, key=lambda punto: punto.fecha).precio
        cambio = _variacion(base, ultimo)
        if cambio is None:
            continue
        filas.append(
            InflacionProductoRespuesta(
                product=ref_producto(producto),
                first_unit_price=base,
                last_unit_price=ultimo,
                change_pct=cambio,
            )
        )
    filas.sort(key=lambda fila: fila.change_pct, reverse=True)

    cuerpo = InflacionRespuesta(
        date_from=rango.desde,
        date_to=rango.hasta,
        products=len(filas),
        inflation_pct=float((variacion * 100).quantize(CENTIMO)) if variacion is not None else None,
        message=(
            f"Tu cesta ha variado un {porcentaje(variacion)} entre "
            f"{rango.desde.isoformat()} y {rango.hasta.isoformat()}."
            if variacion is not None
            else "Aún no hay suficientes observaciones de precio para calcularla."
        ),
        rows=filas,
    )
    if filtro.format == "csv":
        return csv_de("inflacion-personal", filas)
    sellar(respuesta, cuerpo)
    return cuerpo
