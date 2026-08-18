"""Los trece informes de §3.19 y §4.12 del contrato.

Todos aceptan `format=json` (por defecto) o `format=csv` —en CSV la respuesta va
en streaming y sin paginación—, responden con `ETag` y excluyen las
transferencias del gasto y del ingreso (RN-21).

Donde el contrato dejaba `list[dict[str, Any]]` (patrimonio por cuenta, saldo
proyectado) aquí hay una fila tipada: añadir tipos a una respuesta es un cambio
compatible y el frontend deja de adivinar claves.
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comercio import ComercioRefRespuesta
from app.schemas.comun import (
    CantidadStr,
    ImporteStr,
    ParametrosListado,
    Periodo,
    PeriodoPresupuesto,
    PrecioStr,
    Respuesta,
)
from app.schemas.cuenta import CuentaRefRespuesta, TipoCuenta
from app.schemas.producto import (
    ComparativaProductoRespuesta,
    EstadisticasPrecioRespuesta,
    PrecioComercioRespuesta,
    ProductoRefRespuesta,
)
from app.schemas.recurrente import Frecuencia
from app.schemas.transaccion import TransaccionRespuesta

FormatoInforme = Literal["json", "csv"]

#: Una observación de precio con más de estos días se considera rancia.
DIAS_PRECIO_RANCIO = 90


class ParametrosInforme(ParametrosListado):
    """Base de los informes: periodo o rango de fechas, y formato."""

    period: Periodo | None = None
    period_from: Periodo | None = None
    period_to: Periodo | None = None
    date_from: date | None = None
    date_to: date | None = None
    format: FormatoInforme = "json"


# --------------------------------------------------------------------------- #
# 1. Gasto por temática (F-18)
# --------------------------------------------------------------------------- #


class GastoPorTematicaFilaRespuesta(Respuesta):
    category: CategoriaRefRespuesta
    depth: int
    parent_id: UUID | None = None
    amount: ImporteStr
    share_pct: float
    transactions: int
    allocated: ImporteStr | None = None
    variance: ImporteStr | None = Field(
        default=None, description="allocated − amount; negativo es sobrepaso."
    )
    previous_amount: ImporteStr | None = None
    change_pct: float | None = None
    children: list[GastoPorTematicaFilaRespuesta] = Field(default_factory=list)


class GastoPorTematicaRespuesta(Respuesta):
    period_from: str
    period_to: str
    currency: str = "EUR"
    total: ImporteStr
    uncategorized: ImporteStr
    rows: list[GastoPorTematicaFilaRespuesta] = Field(default_factory=list)


class GastoPorTematicaFiltro(ParametrosInforme):
    depth: int = Field(default=1, ge=1, le=6)
    category_id: UUID | None = None
    account_id: list[UUID] = Field(default=[])
    tag_id: list[UUID] = Field(default=[])
    include_children: bool = True
    min_amount: ImporteStr | None = None


# --------------------------------------------------------------------------- #
# 2. Mes a mes (F-19)
# --------------------------------------------------------------------------- #


class PuntoMensualRespuesta(Respuesta):
    period: Periodo
    expense: ImporteStr
    income: ImporteStr
    net: ImporteStr
    by_category: dict[str, ImporteStr] = Field(
        default_factory=dict, description="UUID de temática → importe."
    )


class ComparativaMensualRespuesta(Respuesta):
    periods: list[Periodo] = Field(default_factory=list)
    series: list[PuntoMensualRespuesta] = Field(default_factory=list)
    average_expense: ImporteStr
    best_period: Periodo | None = None
    worst_period: Periodo | None = None


# --------------------------------------------------------------------------- #
# 3. Cash flow (F-36)
# --------------------------------------------------------------------------- #


class PuntoCashFlowRespuesta(Respuesta):
    period: str
    inflow: ImporteStr
    outflow: ImporteStr
    net: ImporteStr
    cumulative: ImporteStr


class CashFlowRespuesta(Respuesta):
    granularity: Literal["month", "week"] = "month"
    points: list[PuntoCashFlowRespuesta] = Field(default_factory=list)
    total_inflow: ImporteStr
    total_outflow: ImporteStr
    net: ImporteStr
    savings_rate: float = Field(description="net / inflow; 0.23 = 23 %.")


class CashFlowFiltro(ParametrosInforme):
    granularity: Literal["month", "week"] = "month"
    account_id: list[UUID] = Field(default=[])


# --------------------------------------------------------------------------- #
# 4. Top comercios (F-37)
# --------------------------------------------------------------------------- #


class TopComercioFilaRespuesta(Respuesta):
    payee: ComercioRefRespuesta | None = None
    amount: ImporteStr
    transactions: int
    average_ticket: ImporteStr
    share_pct: float
    top_category: CategoriaRefRespuesta | None = None
    previous_amount: ImporteStr | None = None
    change_pct: float | None = None


class TopComerciosRespuesta(Respuesta):
    period_from: str
    period_to: str
    total: ImporteStr
    rows: list[TopComercioFilaRespuesta] = Field(default_factory=list)


class TopComerciosFiltro(ParametrosInforme):
    category_id: UUID | None = None
    limit: int = Field(default=20, ge=1, le=200)


# --------------------------------------------------------------------------- #
# 5. Patrimonio neto (F-11)
# --------------------------------------------------------------------------- #


class PatrimonioCuentaRespuesta(Respuesta):
    account: CuentaRefRespuesta
    type: TipoCuenta
    balance: ImporteStr
    is_liability: bool
    change: ImporteStr | None = None
    change_pct: float | None = None


class PuntoPatrimonioRespuesta(Respuesta):
    period: Periodo
    assets: ImporteStr
    liabilities: ImporteStr
    net_worth: ImporteStr
    change: ImporteStr
    change_pct: float | None = None


class PatrimonioRespuesta(Respuesta):
    points: list[PuntoPatrimonioRespuesta] = Field(default_factory=list)
    current: ImporteStr
    change_12m: ImporteStr | None = None
    by_account: list[PatrimonioCuentaRespuesta] = Field(default_factory=list)


class PatrimonioFiltro(ParametrosInforme):
    include_accounts: bool = True


# --------------------------------------------------------------------------- #
# 6. Presupuestado frente a real
# --------------------------------------------------------------------------- #


class PresupuestoVsRealFilaRespuesta(Respuesta):
    #: La ventana que se pide es mensual, pero cada fila lleva **su** periodo: si el
    #: hogar presupuesta por semanas, un agosto trae cinco filas por temática, una por
    #: semana, y no una fila mensual que no existe en ninguna parte.
    period: PeriodoPresupuesto
    category: CategoriaRefRespuesta
    allocated: ImporteStr
    spent: ImporteStr
    variance: ImporteStr = Field(description="allocated − spent; negativo es sobrepaso.")
    used_pct: float
    is_overspent: bool


class PresupuestoVsRealRespuesta(Respuesta):
    period_from: Periodo | None = None
    period_to: Periodo | None = None
    allocated_total: ImporteStr
    spent_total: ImporteStr
    variance_total: ImporteStr
    overspent_categories: int = 0
    rows: list[PresupuestoVsRealFilaRespuesta] = Field(default_factory=list)


class PresupuestoVsRealFiltro(ParametrosInforme):
    only_overspent: bool = False


# --------------------------------------------------------------------------- #
# 7. Evolución del precio de un producto (F-15)
# --------------------------------------------------------------------------- #


class PuntoPrecioProductoRespuesta(Respuesta):
    observed_at: date
    unit_price: PrecioStr
    payee: ComercioRefRespuesta | None = None
    invoice_id: UUID | None = None
    change_pct: float | None = None
    moving_average: PrecioStr | None = None


class PrecioProductoRespuesta(Respuesta):
    product: ProductoRefRespuesta
    unit: str | None = None
    points: list[PuntoPrecioProductoRespuesta] = Field(default_factory=list)
    stats: EstadisticasPrecioRespuesta
    by_payee: list[PrecioComercioRespuesta] = Field(default_factory=list)
    comparison: ComparativaProductoRespuesta | None = None


class PrecioProductoFiltro(ParametrosInforme):
    product_id: UUID
    payee_id: list[UUID] = Field(default=[])


# --------------------------------------------------------------------------- #
# 8. Subidas de precio detectadas (F-16)
# --------------------------------------------------------------------------- #


class SubidaPrecioFilaRespuesta(Respuesta):
    product: ProductoRefRespuesta
    payee: ComercioRefRespuesta | None = None
    previous_unit_price: PrecioStr
    new_unit_price: PrecioStr
    change_pct: float
    observed_at: date
    typical_quantity: CantidadStr | None = None
    estimated_monthly_impact: ImporteStr | None = Field(
        default=None,
        description="Variación × cantidad habitual: ordena por lo que duele, no por el %.",
    )


class SubidasPrecioRespuesta(Respuesta):
    period_from: str
    period_to: str
    min_change_pct: float
    total_estimated_impact: ImporteStr
    rows: list[SubidaPrecioFilaRespuesta] = Field(default_factory=list)


class SubidasPrecioFiltro(ParametrosInforme):
    min_change_pct: float = Field(default=3.0, ge=0, le=1000)
    payee_id: UUID | None = None
    category_id: UUID | None = None


# --------------------------------------------------------------------------- #
# 9. Cesta de la compra (F-60)
# --------------------------------------------------------------------------- #


class CestaComercioFilaRespuesta(Respuesta):
    payee: ComercioRefRespuesta | None = None
    total: ImporteStr
    covered_items: int
    missing_items: int
    coverage_pct: float
    diff_vs_cheapest: ImporteStr
    stale_prices: int = Field(default=0, description="Observaciones con más de 90 días.")
    is_comparable: bool = Field(
        default=True, description="False si le falta algún producto: su total no es comparable."
    )


class CestaInformeRespuesta(Respuesta):
    basket_id: UUID | None = None
    items: int
    cheapest: CestaComercioFilaRespuesta | None = None
    by_payee: list[CestaComercioFilaRespuesta] = Field(default_factory=list)
    missing_by_payee: dict[str, list[ProductoRefRespuesta]] = Field(default_factory=dict)
    max_saving: ImporteStr | None = None


class CestaFiltro(ParametrosInforme):
    basket_id: UUID | None = None
    product_id: list[UUID] = Field(default=[])
    months: int = Field(default=3, ge=1, le=60)


# --------------------------------------------------------------------------- #
# 10. Suscripciones (F-29, F-30)
# --------------------------------------------------------------------------- #


class SuscripcionFilaRespuesta(Respuesta):
    recurring_id: UUID
    name: str
    payee: ComercioRefRespuesta | None = None
    category: CategoriaRefRespuesta | None = None
    frequency: Frecuencia
    amount: ImporteStr
    monthly_cost: ImporteStr
    annual_cost: ImporteStr
    next_occurrence_on: date | None = None
    price_change_pct: float | None = None
    increased_last_year: bool = False
    is_active: bool = True


class SuscripcionesRespuesta(Respuesta):
    monthly_total: ImporteStr
    annual_total: ImporteStr
    active: int
    increases_last_year: int = 0
    rows: list[SuscripcionFilaRespuesta] = Field(default_factory=list)


class SuscripcionesFiltro(ParametrosInforme):
    is_active: bool | None = None


# --------------------------------------------------------------------------- #
# 11. Saldo proyectado a fin de mes (F-47)
# --------------------------------------------------------------------------- #


class SaldoProyectadoFilaRespuesta(Respuesta):
    account: CuentaRefRespuesta
    current_balance: ImporteStr
    pending_recurring: ImporteStr
    remaining_budget: ImporteStr
    projected_balance: ImporteStr
    will_be_negative: bool = False


class SaldoProyectadoRespuesta(Respuesta):
    period: Periodo
    as_of: date
    rows: list[SaldoProyectadoFilaRespuesta] = Field(default_factory=list)
    total_projected: ImporteStr


class SaldoProyectadoFiltro(ParametrosInforme):
    account_id: list[UUID] = Field(default=[])


# --------------------------------------------------------------------------- #
# 12. Gasto inusual (F-48)
# --------------------------------------------------------------------------- #


class AnomaliaFilaRespuesta(Respuesta):
    transaction: TransaccionRespuesta
    category: CategoriaRefRespuesta | None = None
    payee: ComercioRefRespuesta | None = None
    amount: ImporteStr
    average_amount: ImporteStr
    z_score: float
    reason: str = Field(description="Ej.: 'Casi el triple de lo habitual en Alimentación'.")


class AnomaliasRespuesta(Respuesta):
    period_from: str
    period_to: str
    z: float
    rows: list[AnomaliaFilaRespuesta] = Field(default_factory=list)


class AnomaliasFiltro(ParametrosInforme):
    z: float = Field(default=2.5, ge=0.5, le=10)
    min_amount: ImporteStr | None = None


# --------------------------------------------------------------------------- #
# 13. Ingresos, gastos y ahorro (encabezado del panel)
# --------------------------------------------------------------------------- #


class IngresoGastoFilaRespuesta(Respuesta):
    period: Periodo
    income: ImporteStr
    expense: ImporteStr
    savings: ImporteStr
    savings_rate: float


class IngresoGastoRespuesta(Respuesta):
    period_from: Periodo | None = None
    period_to: Periodo | None = None
    income_total: ImporteStr
    expense_total: ImporteStr
    savings_total: ImporteStr
    savings_rate: float
    average_savings_rate: float | None = None
    rows: list[IngresoGastoFilaRespuesta] = Field(default_factory=list)


GastoPorTematicaFilaRespuesta.model_rebuild()
