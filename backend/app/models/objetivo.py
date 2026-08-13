"""Fondos objetivo (sinking funds) y sus aportaciones."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Money
from app.models.mixins import DomainBase, fk_tenencia, uuid_fk

ESTADOS_OBJETIVO = ("active", "paused", "reached", "cancelled")


class Goal(DomainBase):
    """«Vacaciones: 2.400 € para julio» (F-31).

    El importe acumulado no se guarda: es
    `starting_amount + SUM(goal_contributions.amount)`. Una decena de aportaciones
    por objetivo no justifica un contador que se pueda desincronizar.
    """

    __tablename__ = "goals"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    # El objetivo es una capa de intención sobre el dinero: si la temática se
    # archiva o la cuenta se cierra, sobrevive huérfano y visible.
    category_id: Mapped[uuid.UUID | None] = uuid_fk("categories.id", ondelete="SET NULL")
    account_id: Mapped[uuid.UUID | None] = uuid_fk("accounts.id", ondelete="SET NULL")
    target_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    monthly_contribution: Mapped[Decimal | None] = mapped_column(Money)
    starting_amount: Mapped[Decimal] = mapped_column(
        Money, nullable=False, server_default=text("0")
    )
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="active")
    icon: Mapped[str] = mapped_column(Text, nullable=False, server_default="target")
    color_slot: Mapped[int | None] = mapped_column(SmallInteger)
    reached_at: Mapped[datetime | None]
    notes: Mapped[str | None] = mapped_column(Text)

    contributions: Mapped[list[GoalContribution]] = relationship(
        back_populates="goal",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="GoalContribution.goal_id",
    )

    __table_args__ = (
        fk_tenencia("goals", "category_id", "categories", ondelete="SET NULL"),
        fk_tenencia("goals", "account_id", "accounts", ondelete="SET NULL"),
        Index(
            "uq_goals_household_id_name",
            "household_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
        Index(
            "ix_goals_household_id_status_target_date",
            "household_id",
            "status",
            "target_date",
        ),
        CheckConstraint("status IN ('active', 'paused', 'reached', 'cancelled')", name="status"),
        CheckConstraint("target_amount > 0", name="target_amount"),
        CheckConstraint("starting_amount >= 0", name="starting_amount"),
        CheckConstraint("(status = 'reached') = (reached_at IS NOT NULL)", name="reached"),
    )


class GoalContribution(DomainBase):
    """Cada aportación a un fondo, ligada o no a una transacción real."""

    __tablename__ = "goal_contributions"

    goal_id: Mapped[uuid.UUID] = uuid_fk("goals.id", ondelete="CASCADE", nullable=False)
    # Borrar la transacción no borra el histórico del fondo: solo lo desliga y la
    # aportación queda como ajuste manual.
    transaction_id: Mapped[uuid.UUID | None] = uuid_fk("transactions.id", ondelete="SET NULL")
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    goal: Mapped[Goal] = relationship(back_populates="contributions", foreign_keys=[goal_id])

    __table_args__ = (
        fk_tenencia("goal_contributions", "transaction_id", "transactions", ondelete="SET NULL"),
        Index(
            "ix_goal_contributions_goal_id_occurred_on",
            "goal_id",
            "occurred_on",
            postgresql_include=["amount"],
        ),
        Index(
            "uq_goal_contributions_goal_id_transaction_id",
            "goal_id",
            "transaction_id",
            unique=True,
            postgresql_where=text("transaction_id IS NOT NULL"),
        ),
        CheckConstraint("amount <> 0", name="amount_not_zero"),
    )
