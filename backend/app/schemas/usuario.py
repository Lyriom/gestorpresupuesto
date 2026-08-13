"""Perfil, «yo», metadatos públicos y asistente inicial: §3.2 y §4.2 del contrato."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.schemas.comun import (
    Actualizacion,
    Moneda,
    Nombre,
    Peticion,
    Respuesta,
    RespuestaSellada,
)
from app.schemas.cuenta import CuentaCrear


class Tema(StrEnum):
    DARK = "dark"
    LIGHT = "light"
    SYSTEM = "system"


class UsuarioRespuesta(RespuestaSellada):
    email: EmailStr
    name: str
    locale: str
    timezone: str
    currency: str
    theme: Tema
    onboarding_completed: bool


class YoRespuesta(UsuarioRespuesta):
    """«Yo» con lo que la SPA necesita al arrancar, en una sola llamada."""

    accounts_count: int
    categories_count: int
    unread_alerts: int
    current_period: str
    session_expires_at: datetime


class UsuarioActualizar(Actualizacion):
    name: Nombre | None = None
    email: EmailStr | None = None
    locale: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=64)
    currency: Moneda | None = None
    theme: Tema | None = None

    @field_validator("email")
    @classmethod
    def _minusculas(cls, valor: str | None) -> str | None:
        return valor.lower() if valor else valor


class MetaRespuesta(Respuesta):
    """Público: lo que se puede saber sin sesión, para pintar el login."""

    app_name: str
    allow_registration: bool
    first_run: bool
    default_currency: str
    default_locale: str
    max_upload_mb: int
    max_pdf_pages: int
    ocr_enabled: bool


class PasoOnboardingRespuesta(Respuesta):
    """Un paso del asistente inicial (F-50)."""

    key: Literal["account", "categories", "income", "budget", "first_expense"]
    label: str
    done: bool
    optional: bool = False


class OnboardingRespuesta(Respuesta):
    completed: bool
    seeded: bool
    steps: list[PasoOnboardingRespuesta] = Field(default_factory=list)
    next_step: str | None = None


class OnboardingSembrarCrear(Peticion):
    """Juego inicial de temáticas y cuentas a partir de un preset."""

    preset: Literal["es_basico", "es_completo", "minimo"] = "es_basico"
    accounts: list[CuentaCrear] = Field(default_factory=list, max_length=20)
