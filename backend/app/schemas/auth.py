"""Autenticación y sesión: §3.1 y §4.2 del contrato.

La contraseña nunca sale en una respuesta, así que aquí solo hay esquemas de
entrada y la descripción de las sesiones activas.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.comun import Nombre, Peticion, Respuesta, fallo

#: RN-05. Diez caracteres y variedad mínima, sin exigir jeroglíficos que acaben
#: en un pósit pegado a la pantalla.
LONGITUD_MINIMA_CONTRASENYA = 10
LONGITUD_MAXIMA_CONTRASENYA = 128


def _validar_fuerza(contrasenya: str) -> str:
    """RN-05: ni solo dígitos ni solo letras."""
    if contrasenya.isdigit() or contrasenya.isalpha():
        fallo("contrasenya_debil", "La contraseña debe combinar letras y números.")
    return contrasenya


class RegistroCrear(Peticion):
    """Alta del usuario. Solo con `allow_registration` o en el primer arranque (RN-06)."""

    email: EmailStr
    password: str = Field(
        min_length=LONGITUD_MINIMA_CONTRASENYA, max_length=LONGITUD_MAXIMA_CONTRASENYA
    )
    name: Nombre

    @field_validator("password")
    @classmethod
    def _fuerte(cls, valor: str) -> str:
        return _validar_fuerza(valor)

    @field_validator("email")
    @classmethod
    def _minusculas(cls, valor: str) -> str:
        return valor.lower()


class LoginCrear(Peticion):
    email: EmailStr
    password: str = Field(min_length=1, max_length=LONGITUD_MAXIMA_CONTRASENYA)

    @field_validator("email")
    @classmethod
    def _minusculas(cls, valor: str) -> str:
        return valor.lower()


class CambioContrasenyaCrear(Peticion):
    current_password: str = Field(min_length=1, max_length=LONGITUD_MAXIMA_CONTRASENYA)
    new_password: str = Field(
        min_length=LONGITUD_MINIMA_CONTRASENYA, max_length=LONGITUD_MAXIMA_CONTRASENYA
    )

    @field_validator("new_password")
    @classmethod
    def _fuerte(cls, valor: str) -> str:
        return _validar_fuerza(valor)

    @model_validator(mode="after")
    def _distinta(self) -> CambioContrasenyaCrear:
        if self.current_password == self.new_password:
            fallo("contrasenya_debil", "La nueva contraseña debe ser distinta de la actual.")
        return self


class ConfirmarContrasenyaCrear(Peticion):
    """Confirmación para operaciones irreversibles: `DELETE /users/me`."""

    password: str = Field(min_length=1, max_length=LONGITUD_MAXIMA_CONTRASENYA)


class CsrfRespuesta(Respuesta):
    csrf_token: str


class RefrescoRespuesta(Respuesta):
    """El refresco no devuelve el token: viaja en la cookie `httpOnly`."""

    expires_at: datetime


class SesionRespuesta(Respuesta):
    """Una familia de tokens de refresco: «cerrar sesión en el otro dispositivo»."""

    id: UUID
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip_hint: str | None = Field(
        default=None, description="IP truncada: 192.168.1.x. Nunca la IP completa (§9)."
    )
    is_current: bool
