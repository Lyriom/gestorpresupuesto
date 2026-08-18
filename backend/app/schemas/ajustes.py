"""Ajustes, avisos, vistas guardadas, almacenamiento y exportaciones.

§3.20 y §4.13 del contrato. Las exportaciones (§3.18) viven aquí porque son la
otra mitad de «tus datos son tuyos» y el contrato no les dedica bloque propio
en §4.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.alerta import Severidad, TipoAlerta
from app.schemas.comun import (
    Actualizacion,
    Moneda,
    Nombre,
    Peticion,
    Respuesta,
    RespuestaSellada,
    fallo,
)
from app.schemas.usuario import Tema


class ArrastreNegativo(StrEnum):
    """Qué hacer con el sobregasto al cerrar el mes (RN-32)."""

    CARRY = "carry"  # se paga el mes que viene, estilo YNAB
    RESET = "reset"  # se deja a cero


class GranularidadPresupuesto(StrEnum):
    """De cuánto en cuánto se reparte el dinero.

    Cambiarlo **no reinterpreta lo ya guardado**: cada periodo recuerda si era un mes
    o una semana. Decide los que se crean a partir de ahora y qué enseña la interfaz.
    """

    MES = "month"
    SEMANA = "week"


class PeriodicidadDigest(StrEnum):
    OFF = "off"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class AjustesRespuesta(Respuesta):
    currency: str
    locale: str
    timezone: str
    first_day_of_week: int = Field(ge=0, le=6)
    budget_granularity: GranularidadPresupuesto
    theme: Tema
    rollover_default: bool
    rollover_negative: ArrastreNegativo
    budget_alert_pct: float = Field(ge=0, le=2, description="0.9 avisa al 90 % consumido.")
    price_increase_pct: float = Field(ge=0, description="3.0 avisa a partir de +3 %.")
    anomaly_z: float = Field(ge=0, description="Desviaciones típicas para el gasto inusual.")
    duplicate_window_days: int = Field(ge=0, le=30)
    product_match_threshold: float = Field(ge=50, le=100, description="Umbral difuso (88).")
    digest: PeriodicidadDigest


class AjustesActualizar(Actualizacion):
    """Cambiar un umbral recalcula las alertas abiertas (RN-71)."""

    currency: Moneda | None = None
    locale: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=64)
    first_day_of_week: int | None = Field(default=None, ge=0, le=6)
    budget_granularity: GranularidadPresupuesto | None = None
    theme: Tema | None = None
    rollover_default: bool | None = None
    rollover_negative: ArrastreNegativo | None = None
    budget_alert_pct: float | None = Field(default=None, ge=0, le=2)
    price_increase_pct: float | None = Field(default=None, ge=0, le=1000)
    anomaly_z: float | None = Field(default=None, ge=0.5, le=10)
    duplicate_window_days: int | None = Field(default=None, ge=0, le=30)
    product_match_threshold: float | None = Field(default=None, ge=50, le=100)
    digest: PeriodicidadDigest | None = None


class PreferenciaAvisoCrear(Peticion):
    type: TipoAlerta
    enabled: bool = True
    min_severity: Severidad = Severidad.INFO
    in_digest: bool = True


class PreferenciaAvisoRespuesta(Respuesta):
    type: TipoAlerta
    enabled: bool
    min_severity: Severidad
    in_digest: bool


class NotificacionesSustituirCrear(Peticion):
    """`PUT`: sustituye las preferencias de aviso por tipo de alerta (F-45)."""

    items: list[PreferenciaAvisoCrear] = Field(default_factory=list, max_length=40)
    digest: PeriodicidadDigest = PeriodicidadDigest.WEEKLY
    digest_weekday: int = Field(default=0, ge=0, le=6, description="0 = lunes.")
    digest_day_of_month: int = Field(default=1, ge=1, le=28)

    @model_validator(mode="after")
    def _sin_tipos_repetidos(self) -> NotificacionesSustituirCrear:
        tipos = [item.type for item in self.items]
        if len(set(tipos)) != len(tipos):
            fallo("datos_invalidos", "Hay dos preferencias para el mismo tipo de aviso.")
        return self


class NotificacionesRespuesta(Respuesta):
    items: list[PreferenciaAvisoRespuesta] = Field(default_factory=list)
    digest: PeriodicidadDigest
    digest_weekday: int
    digest_day_of_month: int
    last_digest_at: datetime | None = None


class VistaGuardadaCrear(Peticion):
    """Conjunto de filtros con nombre (design system §5.18)."""

    name: Nombre
    resource: Literal["transactions", "invoices", "products", "alerts"] = "transactions"
    filters: dict[str, Any] = Field(description="La query string tal cual, ya validada.")
    is_pinned: bool = False


class VistaGuardadaActualizar(Actualizacion):
    name: Nombre | None = None
    filters: dict[str, Any] | None = None
    is_pinned: bool | None = None


class VistaGuardadaRespuesta(RespuestaSellada):
    name: str
    resource: Literal["transactions", "invoices", "products", "alerts"]
    filters: dict[str, Any] = Field(default_factory=dict)
    is_pinned: bool
    last_used_at: datetime | None = None


class AlmacenamientoRespuesta(Respuesta):
    """Espacio ocupado y cuota (RN-78)."""

    invoices_bytes: int
    attachments_bytes: int
    exports_bytes: int
    total_bytes: int
    quota_bytes: int | None = Field(
        default=None, description="Nulo: sin límite, el caso normal en self-hosted."
    )
    files_count: int
    used_pct: float | None = None


class AmbitoExportacion(StrEnum):
    ALL = "all"
    TRANSACTIONS = "transactions"
    INVOICES = "invoices"
    PRODUCTS = "products"
    BUDGETS = "budgets"
    SETTINGS = "settings"


class FormatoExportacion(StrEnum):
    JSON = "json"
    CSV = "csv"
    ZIP = "zip"


class EstadoExportacion(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


class ExportacionCrear(Peticion):
    """F-43. Los ficheros generados caducan a los 7 días."""

    scope: AmbitoExportacion = AmbitoExportacion.ALL
    format: FormatoExportacion = FormatoExportacion.JSON
    date_from: date | None = None
    date_to: date | None = None
    include_files: bool = Field(
        default=False, description="Incluye los PDF originales; solo con formato zip."
    )

    @model_validator(mode="after")
    def _ficheros_solo_en_zip(self) -> ExportacionCrear:
        if self.include_files and self.format is not FormatoExportacion.ZIP:
            fallo("datos_invalidos", "Para incluir los ficheros originales elige el formato zip.")
        return self


class ExportacionRespuesta(RespuestaSellada):
    status: EstadoExportacion
    scope: AmbitoExportacion
    format: FormatoExportacion
    date_from: date | None = None
    date_to: date | None = None
    include_files: bool = False
    size_bytes: int | None = None
    rows: int | None = None
    file_url: str | None = None
    expires_at: datetime | None = None
    error: str | None = None
