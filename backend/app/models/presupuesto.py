"""Presupuesto mensual: el periodo y el reparto por temática."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Money
from app.models.hogar import CHECK_MODOS_ARRASTRE
from app.models.mixins import DomainBase, fk_tenencia, uuid_fk

ORIGENES_INGRESO = ("manual", "derived")
ORIGENES_ASIGNACION = ("user", "template", "rollover", "merge")


class BudgetPeriod(DomainBase):
    """Un mes presupuestario del hogar: el contenedor de la BudgetBar.

    No hay tabla de «ingresos del mes»: esos ingresos **son** transacciones con
    `kind = 'income'`. Lo que sí hace falta es un número de planificación, porque
    el día 1 el usuario reparte dinero que aún no ha cobrado: `expected_income`.
    """

    __tablename__ = "budget_periods"

    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    expected_income: Mapped[Decimal | None] = mapped_column(Money)
    income_source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="derived")
    note: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None]
    closed_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")
    rollover_applied_at: Mapped[datetime | None]

    allocations: Mapped[list[BudgetAllocation]] = relationship(
        back_populates="period",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="BudgetAllocation.budget_period_id",
    )

    __table_args__ = (
        UniqueConstraint("household_id", "period_month"),
        # El día 1 no es una convención de la aplicación: es una restricción de la base.
        CheckConstraint(
            "period_month = date_trunc('month', period_month)::date", name="first_of_month"
        ),
        CheckConstraint("income_source IN ('manual', 'derived')", name="income_source"),
        CheckConstraint("expected_income IS NULL OR expected_income >= 0", name="expected_income"),
        CheckConstraint(
            "income_source = 'derived' OR expected_income IS NOT NULL",
            name="income_manual_needs_value",
        ),
        CheckConstraint(
            "rollover_applied_at IS NULL OR closed_at IS NOT NULL",
            name="rollover_needs_close",
        ),
        Index(
            "ix_budget_periods_household_id_period_month",
            "household_id",
            text("period_month DESC"),
        ),
        UniqueConstraint("household_id", "id"),
    )


class BudgetAllocation(DomainBase):
    """Cuánto se ha asignado a cada temática en un mes (F-02).

    Lo *gastado* no está aquí: se deriva de las transacciones. Guardar solo lo
    asignado evita el problema clásico de los agregados que se desincronizan.
    """

    __tablename__ = "budget_allocations"

    budget_period_id: Mapped[uuid.UUID] = uuid_fk(
        "budget_periods.id", ondelete="CASCADE", nullable=False
    )
    category_id: Mapped[uuid.UUID] = uuid_fk("categories.id", ondelete="RESTRICT", nullable=False)
    allocated_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, server_default=text("0")
    )
    # Puede ser negativo: es lo que arrastra un exceso de gasto cuando el modo es
    # `carry_negative` (el modelo YNAB).
    carryover_in: Mapped[Decimal] = mapped_column(Money, nullable=False, server_default=text("0"))
    rollover_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="user")

    period: Mapped[BudgetPeriod] = relationship(
        back_populates="allocations", foreign_keys=[budget_period_id]
    )

    __table_args__ = (
        fk_tenencia("budget_allocations", "budget_period_id", "budget_periods", ondelete="CASCADE"),
        fk_tenencia("budget_allocations", "category_id", "categories", ondelete="RESTRICT"),
        UniqueConstraint("budget_period_id", "category_id"),
        # La consulta de la BudgetBar: todas las asignaciones de un mes.
        Index(
            "ix_budget_allocations_budget_period_id",
            "budget_period_id",
            postgresql_include=["category_id", "allocated_amount", "carryover_in"],
        ),
        # El histórico de una temática y la detección de colisiones al fusionar.
        Index(
            "ix_budget_allocations_household_id_category_id",
            "household_id",
            "category_id",
            postgresql_include=[
                "budget_period_id",
                "allocated_amount",
                "carryover_in",
                "rollover_mode",
            ],
        ),
        # Asignar un importe negativo no significa nada en el modelo mental de «una
        # barra que se reparte»: retirar dinero es bajar la asignación.
        CheckConstraint("allocated_amount >= 0", name="allocated_amount"),
        CheckConstraint(f"rollover_mode {CHECK_MODOS_ARRASTRE}", name="rollover_mode"),
        CheckConstraint("source IN ('user', 'template', 'rollover', 'merge')", name="source"),
    )
