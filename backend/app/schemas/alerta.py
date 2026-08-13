"""Alertas y digest: §3.16 y §4.11 del contrato.

RN-73: toda alerta es accionable y financiera. Aquí no hay ningún tipo
promocional ni informativo de relleno.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comercio import ComercioRefRespuesta
from app.schemas.comun import (
    ImporteStr,
    ParametrosListado,
    Periodo,
    Peticion,
    Respuesta,
)
from app.schemas.producto import ProductoRefRespuesta


class TipoAlerta(StrEnum):
    BUDGET_OVERSPENT = "budget_overspent"  # F-20
    BUDGET_NEAR_LIMIT = "budget_near_limit"
    PRODUCT_PRICE_INCREASE = "product_price_increase"  # F-16
    RECURRING_PRICE_INCREASE = "recurring_price_increase"  # F-30
    UNUSUAL_SPENDING = "unusual_spending"  # F-48
    UPCOMING_CHARGE = "upcoming_charge"  # F-49
    DUPLICATE_SUSPECTED = "duplicate_suspected"  # F-34
    INVOICE_LOW_CONFIDENCE = "invoice_low_confidence"
    GOAL_AT_RISK = "goal_at_risk"
    ACCOUNT_UNRECONCILED = "account_unreconciled"


class Severidad(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertaRespuesta(Respuesta):
    id: UUID
    type: TipoAlerta
    severity: Severidad
    title: str
    message: str
    period: Periodo | None = None
    amount: ImporteStr | None = None
    change_pct: float | None = None
    is_read: bool = False
    is_dismissed: bool = False
    muted_until: datetime | None = None
    created_at: datetime
    resolved_at: datetime | None = Field(
        default=None, description="RN-71: la alerta se cierra sola si su causa desaparece."
    )
    # Objeto que la originó: solo uno viene relleno.
    category_id: UUID | None = None
    transaction_id: UUID | None = None
    product_id: UUID | None = None
    recurring_id: UUID | None = None
    invoice_id: UUID | None = None
    goal_id: UUID | None = None
    account_id: UUID | None = None


class ContadorAlertasRespuesta(Respuesta):
    """El badge de la barra lateral: un solo `COUNT`."""

    unread: int = Field(ge=0)
    by_severity: dict[Severidad, int] = Field(default_factory=dict)


class AlertaLeerTodasCrear(Peticion):
    type: list[TipoAlerta] = Field(default_factory=list)
    period: Periodo | None = None


class AlertaDescartarCrear(Peticion):
    """Descartar silencia esa causa concreta durante `mute_days` (RN-72)."""

    mute_days: int = Field(default=30, ge=0, le=365)


class AlertaRecalcularCrear(Peticion):
    """Idempotente por causa (RN-71): recalcular no duplica nada."""

    period: Periodo
    type: list[TipoAlerta] = Field(default_factory=list)


class DigestTematicaRespuesta(Respuesta):
    category: CategoriaRefRespuesta
    amount: ImporteStr
    allocated: ImporteStr | None = None
    change_pct: float | None = None


class DigestComercioRespuesta(Respuesta):
    payee: ComercioRefRespuesta | None
    amount: ImporteStr
    transactions: int


class DigestPrecioRespuesta(Respuesta):
    product: ProductoRefRespuesta
    change_pct: float
    new_unit_price: ImporteStr


class DigestRespuesta(Respuesta):
    """Resumen semanal o mensual tal y como se enviaría (F-45).

    RN-74: se compone con los mismos datos que los informes, no calcula nada por
    su cuenta.
    """

    range: Literal["week", "month"]
    period: Periodo
    date_from: date
    date_to: date
    generated_at: datetime
    currency: str = "EUR"
    total_expense: ImporteStr
    total_income: ImporteStr
    net: ImporteStr
    savings_rate: float | None = None
    budget_used_pct: float | None = None
    top_categories: list[DigestTematicaRespuesta] = Field(default_factory=list)
    top_payees: list[DigestComercioRespuesta] = Field(default_factory=list)
    price_increases: list[DigestPrecioRespuesta] = Field(default_factory=list)
    upcoming_charges: int = 0
    unreviewed_invoices: int = 0
    alerts: list[AlertaRespuesta] = Field(default_factory=list)


class AlertaFiltro(ParametrosListado):
    CAMPOS_ORDENABLES = frozenset({"created_at", "severity", "type", "amount"})
    ORDEN_POR_DEFECTO = "-created_at"

    type: list[TipoAlerta] = Field(default=[])
    severity: list[Severidad] = Field(default=[])
    is_read: bool | None = None
    is_dismissed: bool | None = None
    period: Periodo | None = None
    date_from: date | None = None
    date_to: date | None = None


class DigestFiltro(ParametrosListado):
    period: Periodo | None = None
    range: Literal["week", "month"] = "week"
