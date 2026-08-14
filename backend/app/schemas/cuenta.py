"""Cuentas, saldos, conciliación y patrimonio: §3.3 y §4.3 del contrato."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.comun import (
    Actualizacion,
    ColorHex,
    ImporteStr,
    Moneda,
    Nombre,
    ParametrosBusqueda,
    Peticion,
    Respuesta,
    RespuestaSellada,
    fallo,
)


class TipoCuenta(StrEnum):
    """RN-07: conjunto cerrado. No se cambia el tipo si ya hay movimientos."""

    CHECKING = "checking"
    SAVINGS = "savings"
    CASH = "cash"
    CREDIT_CARD = "credit_card"
    INVESTMENT = "investment"
    DEBT = "debt"


#: Los pasivos restan en el patrimonio neto (RN-25).
TIPOS_PASIVO = frozenset({TipoCuenta.CREDIT_CARD, TipoCuenta.DEBT})

#: Tipos que admiten límite de crédito, interés o cuota mensual.
TIPOS_CON_DEUDA = TIPOS_PASIVO

TipoInteres = Annotated[Decimal, Field(ge=0, le=100, decimal_places=4)]


class CuentaCrear(Peticion):
    name: Nombre
    type: TipoCuenta
    #: Sin indicar, la del hogar. Estaba fija en "EUR" y una instalación en
    #: dólares creaba las cuentas en euros sin que nadie lo pidiera.
    currency: Moneda | None = None
    initial_balance: ImporteStr = Decimal("0.00")
    opened_on: date | None = None
    color: ColorHex | None = None
    icon: str | None = Field(default=None, max_length=40)
    is_excluded_from_net_worth: bool = False
    # Solo para type=debt / credit_card
    credit_limit: ImporteStr | None = Field(default=None, ge=0)
    interest_rate: TipoInteres | None = None
    monthly_payment: ImporteStr | None = Field(default=None, ge=0)
    ends_on: date | None = None

    @model_validator(mode="after")
    def _coherencia_deuda(self) -> CuentaCrear:
        if self.type is not TipoCuenta.DEBT and self.monthly_payment is not None:
            fallo("regla_de_negocio", "La cuota mensual solo se aplica a cuentas de deuda.")
        if self.type not in TIPOS_CON_DEUDA and self.credit_limit is not None:
            fallo(
                "regla_de_negocio",
                "El límite de crédito solo se aplica a tarjetas y cuentas de deuda.",
            )
        if self.ends_on and self.opened_on and self.ends_on < self.opened_on:
            fallo("regla_de_negocio", "La fecha de fin es anterior a la de apertura.")
        return self


class CuentaActualizar(Actualizacion):
    """El `type` no se toca: cambiarlo alteraría el patrimonio neto histórico (RN-07)."""

    name: Nombre | None = None
    currency: Moneda | None = None
    opened_on: date | None = None
    color: ColorHex | None = None
    icon: str | None = Field(default=None, max_length=40)
    is_excluded_from_net_worth: bool | None = None
    credit_limit: ImporteStr | None = Field(default=None, ge=0)
    interest_rate: TipoInteres | None = None
    monthly_payment: ImporteStr | None = Field(default=None, ge=0)
    ends_on: date | None = None
    note: str | None = Field(default=None, max_length=1000)
    # `current_balance` no existe como campo editable: el saldo es derivado
    # (RN-08) y `extra="forbid"` lo rechaza con un 422 si alguien lo intenta.


class CuentaRefRespuesta(Respuesta):
    """Cuenta embebida en otra respuesta: lo justo para pintar un selector."""

    id: UUID
    name: str
    type: TipoCuenta
    currency: str
    color: str | None = None


class CuentaRespuesta(RespuestaSellada):
    name: str
    type: TipoCuenta
    currency: str
    initial_balance: ImporteStr
    current_balance: ImporteStr
    available_balance: ImporteStr | None = Field(
        default=None, description="Tarjetas: límite − saldo dispuesto."
    )
    is_liability: bool
    is_archived: bool
    is_excluded_from_net_worth: bool
    color: str | None
    icon: str | None
    opened_on: date | None = None
    last_transaction_on: date | None
    transactions_count: int
    reconciled_through: date | None
    credit_limit: ImporteStr | None = None
    interest_rate: Decimal | None = None
    monthly_payment: ImporteStr | None = None
    ends_on: date | None = None


class CuentaSaldoRespuesta(Respuesta):
    account_id: UUID
    as_of: date
    balance: ImporteStr
    reconciled_balance: ImporteStr
    unreconciled_amount: ImporteStr
    pending_recurring: ImporteStr


class TotalPorTipoRespuesta(Respuesta):
    type: TipoCuenta
    total: ImporteStr
    accounts: int


class ResumenCuentasRespuesta(Respuesta):
    """Activos, pasivos y patrimonio neto actual (F-11, RN-25)."""

    as_of: date
    currency: str
    assets: ImporteStr
    liabilities: ImporteStr
    net_worth: ImporteStr
    by_type: list[TotalPorTipoRespuesta] = Field(default_factory=list)


class ConciliarCrear(Peticion):
    """F-32: la conciliación no edita saldos, crea un ajuste con rastro (RN-10)."""

    statement_balance: ImporteStr
    statement_date: date
    create_adjustment: bool = True
    adjustment_category_id: UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class ConciliarRespuesta(Respuesta):
    account_id: UUID
    statement_balance: ImporteStr
    computed_balance: ImporteStr
    difference: ImporteStr
    adjustment_transaction_id: UUID | None
    reconciled_through: date


class ConciliacionRespuesta(RespuestaSellada):
    """Una conciliación del historial."""

    account_id: UUID
    statement_date: date
    statement_balance: ImporteStr
    computed_balance: ImporteStr
    difference: ImporteStr
    adjustment_transaction_id: UUID | None
    note: str | None


class CuotaAmortizacionRespuesta(Respuesta):
    """Una fila del calendario de amortización (F-41)."""

    number: int
    due_on: date
    payment: ImporteStr
    principal: ImporteStr
    interest: ImporteStr
    remaining: ImporteStr


class AmortizacionRespuesta(Respuesta):
    account_id: UUID
    principal: ImporteStr
    interest_rate: Decimal
    monthly_payment: ImporteStr
    months: int
    total_interest: ImporteStr
    ends_on: date | None
    rows: list[CuotaAmortizacionRespuesta] = Field(default_factory=list)


class CuentaFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset({"name", "type", "current_balance", "created_at"})
    ORDEN_POR_DEFECTO = "name"

    type: list[TipoCuenta] = Field(default=[])
    is_archived: bool | None = None
    as_of: date | None = None
