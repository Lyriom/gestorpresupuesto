"""Recurrentes y suscripciones: §3.8 y §4.7 del contrato.

La frecuencia que viaja por el cable es la del contrato, en inglés, porque es la
que consume el frontend; el motor de repeticiones vive en
`app/services/recurrencia.py` con su propio vocabulario en castellano. Aquí se
declara la correspondencia una sola vez (`A_FRECUENCIA_SERVICIO`) y se construye
la `ReglaRepeticion` del servicio con `a_regla_repeticion()`, en vez de duplicar
el motor o sus enums.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.core.errors import ReglaDeNegocio
from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comercio import ComercioRefRespuesta
from app.schemas.comun import (
    Actualizacion,
    ImporteStr,
    Moneda,
    Nombre,
    ParametrosBusqueda,
    Peticion,
    Respuesta,
    RespuestaSellada,
    fallo,
)
from app.services.recurrencia import ErrorRecurrencia, ReglaRepeticion
from app.services.recurrencia import Frecuencia as FrecuenciaServicio

#: Valor de `day_of_month` que significa «el último día del mes» (nóminas).
ULTIMO_DIA_DEL_MES = -1


class Frecuencia(StrEnum):
    """Vocabulario público. `EVERY_N_DAYS` usa `interval` como número de días."""

    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    BIMONTHLY = "bimonthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    YEARLY = "yearly"
    EVERY_N_DAYS = "every_n_days"
    LAST_WEEKDAY_OF_MONTH = "last_weekday_of_month"


#: Correspondencia con el motor de `app/services/recurrencia.py`.
A_FRECUENCIA_SERVICIO: dict[Frecuencia, FrecuenciaServicio] = {
    Frecuencia.WEEKLY: FrecuenciaServicio.SEMANAL,
    Frecuencia.BIWEEKLY: FrecuenciaServicio.QUINCENAL,
    Frecuencia.MONTHLY: FrecuenciaServicio.MENSUAL,
    Frecuencia.BIMONTHLY: FrecuenciaServicio.BIMESTRAL,
    Frecuencia.QUARTERLY: FrecuenciaServicio.TRIMESTRAL,
    # Sin esta entrada no se podría dar de alta un seguro semestral, que es de
    # los recurrentes más habituales: el motor ya lo soporta.
    Frecuencia.SEMIANNUAL: FrecuenciaServicio.SEMESTRAL,
    Frecuencia.YEARLY: FrecuenciaServicio.ANUAL,
    Frecuencia.EVERY_N_DAYS: FrecuenciaServicio.DIARIA,
    # El último día laborable del mes es una mensual con `dia_del_mes = -1` y
    # ajuste a día laborable, que es justo lo que hace el servicio.
    Frecuencia.LAST_WEEKDAY_OF_MONTH: FrecuenciaServicio.MENSUAL,
}


class RecurrenteCrear(Peticion):
    name: Nombre
    kind: Literal["expense", "income"] = "expense"
    account_id: UUID
    category_id: UUID | None = None
    payee_id: UUID | None = None
    amount: ImporteStr = Field(gt=0)
    currency: Moneda = "EUR"
    frequency: Frecuencia
    interval: int = Field(
        default=1, ge=1, le=365, description="Con `every_n_days`, cada cuántos días."
    )
    day_of_month: int | None = Field(
        default=None, ge=ULTIMO_DIA_DEL_MES, le=31, description="-1 = último día del mes."
    )
    weekday: int | None = Field(default=None, ge=0, le=6, description="0 = lunes … 6 = domingo.")
    starts_on: date
    ends_on: date | None = None
    is_subscription: bool = False
    auto_post: bool = Field(default=False, description="Se materializa sin intervención.")
    remind_days_before: int = Field(default=3, ge=0, le=60)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _dia_valido(self) -> RecurrenteCrear:
        if self.day_of_month == 0:
            fallo("datos_invalidos", "El día del mes debe estar entre 1 y 31, o ser -1.")
        # Construir la regla del servicio es la comprobación de coherencia: ahí
        # viven las reglas de intervalo, día y rango de fechas.
        try:
            self.a_regla_repeticion()
        except ReglaDeNegocio as exc:
            fallo("datos_invalidos", exc.mensaje)
        return self

    def a_regla_repeticion(self) -> ReglaRepeticion:
        """Traduce el recurrente a la regla que entiende el motor del servicio.

        La usa la capa de servicio, ya fuera de la validación, así que el error
        viaja como `AppError`; el validador de arriba lo reescribe como error de
        campo para que el formulario pueda pintarlo.
        """
        ultimo_laborable = self.frequency is Frecuencia.LAST_WEEKDAY_OF_MONTH
        try:
            return ReglaRepeticion(
                frecuencia=A_FRECUENCIA_SERVICIO[self.frequency],
                intervalo=self.interval,
                dia_del_mes=ULTIMO_DIA_DEL_MES if ultimo_laborable else self.day_of_month,
                dia_de_la_semana=self.weekday,
                fecha_inicio=self.starts_on,
                fecha_fin=self.ends_on,
                solo_dias_laborables=ultimo_laborable,
            )
        except ErrorRecurrencia as exc:
            raise ReglaDeNegocio(str(exc), codigo="datos_invalidos") from exc


class RecurrenteActualizar(Actualizacion):
    name: Nombre | None = None
    account_id: UUID | None = None
    category_id: UUID | None = None
    payee_id: UUID | None = None
    amount: ImporteStr | None = Field(default=None, gt=0)
    currency: Moneda | None = None
    frequency: Frecuencia | None = None
    interval: int | None = Field(default=None, ge=1, le=365)
    day_of_month: int | None = Field(default=None, ge=ULTIMO_DIA_DEL_MES, le=31)
    weekday: int | None = Field(default=None, ge=0, le=6)
    starts_on: date | None = None
    ends_on: date | None = None
    is_subscription: bool | None = None
    auto_post: bool | None = None
    remind_days_before: int | None = Field(default=None, ge=0, le=60)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _rango_coherente(self) -> RecurrenteActualizar:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            fallo("datos_invalidos", "La fecha de fin es anterior a la de inicio.")
        return self


class OcurrenciaRespuesta(Respuesta):
    """Una ocurrencia ya materializada (RN-36: única por recurrente y fecha)."""

    id: UUID
    occurrence_date: date
    amount: ImporteStr
    transaction_id: UUID | None
    is_skipped: bool = False
    posted_at: date | None = None


class RecurrenteRespuesta(RespuestaSellada):
    name: str
    kind: Literal["expense", "income"]
    account_id: UUID
    category: CategoriaRefRespuesta | None = None
    payee: ComercioRefRespuesta | None = None
    amount: ImporteStr
    currency: str
    frequency: Frecuencia
    interval: int
    day_of_month: int | None = None
    weekday: int | None = None
    rule_text: str | None = Field(
        default=None, description="Descripción legible de la regla, para la interfaz."
    )
    starts_on: date
    ends_on: date | None
    next_occurrence_on: date | None
    last_posted_on: date | None
    is_active: bool
    is_paused: bool
    is_subscription: bool
    auto_post: bool
    remind_days_before: int = 3
    occurrences_count: int = 0
    average_amount: ImporteStr | None = None
    last_amount: ImporteStr | None = None
    price_change_pct: float | None = Field(
        default=None, description="Subida del último cargo frente al anterior (F-30, RN-40)."
    )
    annual_cost: ImporteStr | None = None
    note: str | None = None
    occurrences: list[OcurrenciaRespuesta] = Field(default_factory=list)


class RecurrentePublicarCrear(Peticion):
    """Materializa ya una ocurrencia como transacción real (RN-36)."""

    occurrence_date: date
    amount: ImporteStr | None = Field(default=None, gt=0, description="Por si vino distinto.")
    note: str | None = Field(default=None, max_length=2000)


class RecurrenteSaltarCrear(Peticion):
    occurrence_date: date
    reason: str | None = Field(default=None, max_length=280)


class ProximoVencimientoRespuesta(Respuesta):
    """Ventana de vencimientos para el recordatorio (F-49) y el saldo proyectado (F-47)."""

    recurring_id: UUID
    name: str
    account_id: UUID
    category: CategoriaRefRespuesta | None = None
    due_on: date
    days_until: int
    expected_amount: ImporteStr
    is_subscription: bool
    is_overdue: bool


class RecurrenteDetectadoRespuesta(Respuesta):
    """Suscripción detectada en el histórico y aún sin confirmar (F-29, RN-39)."""

    group_id: str
    payee_name: str
    suggested_name: str
    occurrences: int
    first_seen_on: date
    last_seen_on: date
    estimated_frequency: Frecuencia
    average_amount: ImporteStr
    last_amount: ImporteStr
    amount_stability: float = Field(ge=0, le=1, description="RN-39: se exige ≥ 0,8.")
    price_increase_pct: float | None = None
    transaction_ids: list[UUID] = Field(default_factory=list)
    suggested_category: CategoriaRefRespuesta | None = None
    account_id: UUID | None = None


class RecurrenteConfirmarCrear(Peticion):
    """Convierte un grupo detectado en un recurrente real y le vincula el histórico."""

    name: Nombre | None = None
    category_id: UUID | None = None
    account_id: UUID | None = None
    amount: ImporteStr | None = Field(default=None, gt=0)
    frequency: Frecuencia | None = None
    is_subscription: bool = True
    link_history: bool = Field(
        default=True, description="Marca las transacciones del grupo como de este recurrente."
    )


class PuntoPrecioRecurrenteRespuesta(Respuesta):
    occurrence_date: date
    amount: ImporteStr
    change_pct: float | None = None
    is_increase: bool = False
    transaction_id: UUID | None = None


class HistorialPrecioRecurrenteRespuesta(Respuesta):
    """Evolución del importe cobrado, con las subidas marcadas (F-30)."""

    recurring_id: UUID
    name: str
    currency: str = "EUR"
    first_amount: ImporteStr | None = None
    last_amount: ImporteStr | None = None
    total_change_pct: float | None = None
    increases: int = 0
    points: list[PuntoPrecioRecurrenteRespuesta] = Field(default_factory=list)


class RecurrenteFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset(
        {"name", "next_occurrence_on", "amount", "annual_cost", "created_at"}
    )
    ORDEN_POR_DEFECTO = "next_occurrence_on"

    kind: Literal["expense", "income"] | None = None
    is_active: bool | None = None
    is_subscription: bool | None = None
    category_id: UUID | None = None
    account_id: UUID | None = None


class ProximosFiltro(ParametrosBusqueda):
    """`GET /recurring/upcoming`: ventana en días."""

    days: int = Field(default=30, ge=1, le=365)
    account_id: UUID | None = None


class DetectadosFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset({"occurrences", "average_amount", "last_seen_on"})
    ORDEN_POR_DEFECTO = "-occurrences"

    min_occurrences: int = Field(default=3, ge=2, le=60, description="RN-39: al menos 3.")
    months: int = Field(default=12, ge=1, le=60)
