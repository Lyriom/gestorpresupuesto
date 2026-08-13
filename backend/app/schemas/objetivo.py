"""Fondos objetivo (F-31): §3.15 y §4.11 del contrato."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comun import (
    Actualizacion,
    FechaMovimiento,
    ImporteStr,
    Nombre,
    ParametrosBusqueda,
    Peticion,
    Respuesta,
    RespuestaSellada,
    fallo,
)


class TipoMovimientoObjetivo(StrEnum):
    CONTRIBUTION = "contribution"
    WITHDRAWAL = "withdrawal"


class ObjetivoCrear(Peticion):
    name: Nombre
    target_amount: ImporteStr = Field(gt=0, description="RN-51.")
    target_date: date | None = None
    category_id: UUID | None = None
    account_id: UUID | None = Field(default=None, description="Dónde se guarda el dinero.")
    initial_amount: ImporteStr = Field(default=Decimal("0.00"), ge=0)
    monthly_contribution: ImporteStr | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _fecha_futura(self) -> ObjetivoCrear:
        """RN-51: al crearlo, la fecha límite está en el futuro.

        Al editarlo sí se admite una fecha pasada: un objetivo puede vencer sin
        haberse cumplido y hay que poder corregir la fecha después.
        """
        if self.target_date and self.target_date <= date.today():
            fallo("datos_invalidos", "La fecha objetivo debe estar en el futuro.")
        return self


class ObjetivoActualizar(Actualizacion):
    name: Nombre | None = None
    target_amount: ImporteStr | None = Field(default=None, gt=0)
    target_date: date | None = None
    category_id: UUID | None = None
    account_id: UUID | None = None
    monthly_contribution: ImporteStr | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=1000)


class ObjetivoRespuesta(RespuestaSellada):
    name: str
    target_amount: ImporteStr
    current_amount: ImporteStr
    remaining: ImporteStr
    progress_pct: float = Field(ge=0)
    target_date: date | None
    months_left: int | None
    required_monthly: ImporteStr | None = Field(
        default=None, description="Se recalcula en cada lectura, nunca se guarda (RN-51)."
    )
    monthly_contribution: ImporteStr | None
    is_on_track: bool
    is_completed: bool = Field(description="current_amount ≥ target_amount (RN-54).")
    category: CategoriaRefRespuesta | None = None
    account_id: UUID | None = None
    note: str | None = None


class MovimientoObjetivoCrear(Peticion):
    """Aportación o retirada. Con `account_id` genera una transferencia real (RN-53)."""

    amount: ImporteStr = Field(gt=0)
    date: FechaMovimiento
    account_id: UUID | None = Field(
        default=None, description="Si se indica, genera una transferencia real."
    )
    note: str | None = Field(default=None, max_length=280)


class MovimientoObjetivoRespuesta(Respuesta):
    id: UUID
    goal_id: UUID
    kind: TipoMovimientoObjetivo
    amount: ImporteStr = Field(description="Siempre positivo; el signo lo da `kind` (RN-52).")
    date: date
    account_id: UUID | None
    transaction_id: UUID | None = Field(
        default=None, description="La pata de la transferencia, si la hubo."
    )
    balance_after: ImporteStr | None = None
    note: str | None
    created_at: datetime


class ObjetivoFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset(
        {"name", "target_date", "progress_pct", "target_amount", "created_at"}
    )
    ORDEN_POR_DEFECTO = "target_date"

    is_completed: bool | None = None
    category_id: UUID | None = None
    account_id: UUID | None = None
