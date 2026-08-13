"""Hogares y miembros: la raíz de tenencia del modelo de datos.

`docs/arquitectura/modelo-datos.md` §2.3 y §2.4: cada usuario recibe un hogar al
registrarse y RN-01 se lee como «filtrar por el hogar de la sesión». §12 del
contrato avisa de que la API **todavía no expone el concepto**: no hay endpoints
en §3 hasta que F-57 (multiusuario con roles) los necesite. Estos esquemas
existen para que ese día no haya que inventar nombres nuevos, y para que los
ajustes del hogar —divisa, umbrales de aviso— tengan una forma acordada.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import EmailStr, Field

from app.schemas.comun import (
    Actualizacion,
    Moneda,
    Nombre,
    Peticion,
    Respuesta,
    RespuestaSellada,
)

#: `budget_start_day` se limita a 28 para que el mes presupuestario exista en
#: febrero sin reglas especiales (modelo de datos §2.3).
DIA_INICIO_MAXIMO = 28

Porcentaje = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]


class ModoArrastre(StrEnum):
    """Qué se propone a las temáticas nuevas para el rollover (F-26, RN-32)."""

    NONE = "none"
    CARRY = "carry"
    CARRY_NEGATIVE = "carry_negative"


class RolMiembro(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class HogarCrear(Peticion):
    name: Nombre = "Mi hogar"
    currency: Moneda = "EUR"
    locale: str = Field(default="es-ES", max_length=10)
    timezone: str = Field(default="Europe/Madrid", max_length=64)
    budget_start_day: int = Field(default=1, ge=1, le=DIA_INICIO_MAXIMO)
    default_rollover_mode: ModoArrastre = ModoArrastre.NONE


class HogarActualizar(Actualizacion):
    name: Nombre | None = None
    currency: Moneda | None = None
    locale: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=64)
    budget_start_day: int | None = Field(default=None, ge=1, le=DIA_INICIO_MAXIMO)
    default_rollover_mode: ModoArrastre | None = None
    near_limit_pct: Porcentaje | None = Field(default=None, gt=0)
    price_alert_pct: Porcentaje | None = None
    unusual_expense_sigma: Decimal | None = Field(default=None, ge=0, le=10, decimal_places=2)


class HogarRespuesta(RespuestaSellada):
    name: str
    currency: str
    locale: str
    timezone: str
    budget_start_day: int
    default_rollover_mode: ModoArrastre
    near_limit_pct: Porcentaje
    price_alert_pct: Porcentaje
    unusual_expense_sigma: Decimal
    is_archived: bool = False
    members_count: int = 1
    my_role: RolMiembro = RolMiembro.OWNER


class MiembroHogarCrear(Peticion):
    """Invitación a un hogar. Nunca se degrada ni se expulsa al último `owner`."""

    email: EmailStr
    role: RolMiembro = RolMiembro.EDITOR


class MiembroHogarActualizar(Actualizacion):
    role: RolMiembro | None = None
    is_default: bool | None = None


class MiembroHogarRespuesta(Respuesta):
    id: UUID
    household_id: UUID
    user_id: UUID | None
    email: EmailStr
    name: str | None
    role: RolMiembro
    is_default: bool
    invited_at: datetime | None
    accepted_at: datetime | None = Field(default=None, description="Nulo: invitación pendiente.")
