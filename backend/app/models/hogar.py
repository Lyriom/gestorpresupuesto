"""Hogares y miembros: la raíz de tenencia de todo el modelo."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.mixins import CHECK_MONEDA, GlobalBase, columna_moneda, uuid_fk

# Los tres modos de arrastre del sobrante mensual (F-26).
MODOS_ARRASTRE = ("none", "carry", "carry_negative")
CHECK_MODOS_ARRASTRE = "IN ('none', 'carry', 'carry_negative')"

ROLES = ("owner", "editor", "viewer")


class Household(GlobalBase):
    """La raíz de tenencia. Cada usuario recibe uno al registrarse.

    F-57 (multiusuario con roles) se implementa después añadiendo miembros, sin
    ninguna migración de esquema.
    """

    __tablename__ = "households"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = columna_moneda()
    locale: Mapped[str] = mapped_column(String(10), nullable=False, server_default="es-ES")
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="Europe/Madrid")
    budget_start_day: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )
    #: De cuánto en cuánto se presupuesta: `month` o `week`. Decide los periodos que
    #: se crean de ahora en adelante; los que ya existen guardan el suyo.
    budget_granularity: Mapped[str] = mapped_column(
        String(5), nullable=False, server_default="month"
    )
    default_rollover_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="none"
    )
    near_limit_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("85.00")
    )
    price_alert_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("5.00")
    )
    unusual_expense_sigma: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, server_default=text("2.50")
    )
    # El creador puede irse del hogar y el hogar sigue existiendo para el resto.
    created_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")
    archived_at: Mapped[datetime | None]

    members: Mapped[list[HouseholdMember]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(CHECK_MONEDA, name="currency"),
        # El día 28 como tope hace que el mes presupuestario exista en febrero sin
        # reglas especiales.
        CheckConstraint("budget_start_day BETWEEN 1 AND 28", name="budget_start_day"),
        CheckConstraint("budget_granularity IN ('month', 'week')", name="budget_granularity"),
        CheckConstraint(
            f"default_rollover_mode {CHECK_MODOS_ARRASTRE}", name="default_rollover_mode"
        ),
        CheckConstraint(
            "near_limit_pct > 0 AND near_limit_pct <= 100 AND price_alert_pct >= 0",
            name="pct_ranges",
        ),
    )


class HouseholdMember(GlobalBase):
    """Quién puede entrar en qué hogar y con qué permiso (F-57)."""

    __tablename__ = "household_members"

    # La unicidad (household_id, user_id) ya sirve de índice por hogar.
    household_id: Mapped[uuid.UUID] = uuid_fk("households.id", ondelete="CASCADE", nullable=False)
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE", nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False, server_default="owner")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    invited_at: Mapped[datetime | None]
    accepted_at: Mapped[datetime | None]
    invited_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")

    household: Mapped[Household] = relationship(
        back_populates="members", foreign_keys=[household_id]
    )

    __table_args__ = (
        UniqueConstraint("household_id", "user_id"),
        CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="role"),
        # Un solo hogar por defecto por usuario: la regla de negocio expresada en
        # la base de datos y no en un `if` del servicio.
        Index(
            "uq_household_members_user_id_default",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        Index(
            "ix_household_members_user_id_role",
            "user_id",
            "role",
            postgresql_where=text("accepted_at IS NOT NULL"),
        ),
    )
