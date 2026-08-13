"""Recurrentes y suscripciones: reglas de repetición y sus vencimientos."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Confidence, Money, Percentage
from app.models.mixins import CHECK_MONEDA, DomainBase, columna_moneda, fk_tenencia, uuid_fk
from app.services.recurrencia import Frecuencia

# La lista de frecuencias sale del enum que ya usa `siguiente_fecha()`: si viviera
# también aquí, las dos copias divergirían en cuanto se añadiese una.
CHECK_FRECUENCIA = "frequency IN (" + ", ".join(f"'{f.value}'" for f in Frecuencia) + ")"

ESTADOS_VENCIMIENTO = ("pending", "created", "matched", "skipped", "missed")
DIAS_DEL_MES = ", ".join(str(dia) for dia in range(1, 32))


class RecurringRule(DomainBase):
    """Alquiler, nómina, Netflix (F-28) y las suscripciones detectadas (F-29).

    Una sola tabla para las dos cosas: solo cambia `origin`, así que «promover» una
    suscripción detectada a recurrente confirmada es un `UPDATE` de una columna y
    no una migración de datos entre tablas.

    Se guarda un subconjunto de RFC 5545 en columnas explícitas en lugar de una
    cadena `RRULE`: parsearla en cada consulta haría imposible el índice sobre
    `next_due_on`, y estas columnas cubren el 100 % de los casos domésticos.
    """

    __tablename__ = "recurring_rules"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False, server_default="expense")
    account_id: Mapped[uuid.UUID | None] = uuid_fk("accounts.id", ondelete="RESTRICT")
    counter_account_id: Mapped[uuid.UUID | None] = uuid_fk("accounts.id", ondelete="RESTRICT")
    category_id: Mapped[uuid.UUID | None] = uuid_fk("categories.id", ondelete="RESTRICT")
    payee_id: Mapped[uuid.UUID | None] = uuid_fk("payees.id", ondelete="SET NULL")
    template_splits: Mapped[list | None] = mapped_column(JSONB)
    expected_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = columna_moneda()
    amount_tolerance_pct: Mapped[Decimal] = mapped_column(
        Percentage, nullable=False, server_default=text("5.00")
    )
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)
    interval_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )
    by_month_day: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    by_weekday: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    # Resuelve el único caso espinoso real: qué hacer con el «día 31» en febrero.
    month_day_policy: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="clamp"
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date | None] = mapped_column(Date)
    max_occurrences: Mapped[int | None] = mapped_column(SmallInteger)
    # Denormalizado: el planificador solo mira esta columna.
    next_due_on: Mapped[date | None] = mapped_column(Date)
    lead_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("3"))
    auto_create: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_subscription: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="active")
    origin: Mapped[str] = mapped_column(String(8), nullable=False, server_default="manual")
    detection_confidence: Mapped[Decimal | None] = mapped_column(Confidence)
    confirmed_at: Mapped[datetime | None]
    last_amount: Mapped[Decimal | None] = mapped_column(Money)
    last_seen_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    occurrences: Mapped[list[RecurringOccurrence]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="RecurringOccurrence.recurring_rule_id",
    )

    __table_args__ = (
        fk_tenencia("recurring_rules", "account_id", "accounts", ondelete="RESTRICT"),
        fk_tenencia("recurring_rules", "counter_account_id", "accounts", ondelete="RESTRICT"),
        fk_tenencia("recurring_rules", "category_id", "categories", ondelete="RESTRICT"),
        fk_tenencia("recurring_rules", "payee_id", "payees", ondelete="SET NULL"),
        Index(
            "uq_recurring_rules_household_id_name",
            "household_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("status <> 'ended'"),
        ),
        # La consulta del planificador diario: qué vence hoy o está a punto.
        Index(
            "ix_recurring_rules_next_due_on",
            "next_due_on",
            postgresql_where=text("status = 'active' AND next_due_on IS NOT NULL"),
        ),
        Index(
            "ix_recurring_rules_household_id_status_next_due_on",
            "household_id",
            "status",
            "next_due_on",
            postgresql_include=["expected_amount", "category_id"],
        ),
        # Emparejar una transacción nueva con su recurrente (F-29, F-30).
        Index(
            "ix_recurring_rules_household_id_payee_id",
            "household_id",
            "payee_id",
            postgresql_where=text("payee_id IS NOT NULL"),
        ),
        CheckConstraint("kind IN ('expense', 'income', 'transfer')", name="kind"),
        CheckConstraint(CHECK_FRECUENCIA, name="frequency"),
        CheckConstraint("month_day_policy IN ('clamp', 'last_day')", name="month_day_policy"),
        CheckConstraint("status IN ('active', 'paused', 'ended')", name="status"),
        CheckConstraint("origin IN ('manual', 'detected')", name="origin"),
        CheckConstraint("interval_count BETWEEN 1 AND 60", name="interval"),
        CheckConstraint("expected_amount <> 0", name="amount_not_zero"),
        CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="dates"),
        CheckConstraint("lead_days BETWEEN 0 AND 60", name="lead_days"),
        CheckConstraint(
            "amount_tolerance_pct >= 0 AND amount_tolerance_pct <= 100", name="tolerance"
        ),
        CheckConstraint(
            "detection_confidence IS NULL "
            "OR (detection_confidence >= 0 AND detection_confidence <= 1)",
            name="confidence",
        ),
        CheckConstraint(
            "origin = 'manual' OR detection_confidence IS NOT NULL",
            name="detected_has_confidence",
        ),
        CheckConstraint(
            f"by_month_day IS NULL OR (by_month_day <@ ARRAY[{DIAS_DEL_MES}]::smallint[])",
            name="by_month_day",
        ),
        CheckConstraint(
            "by_weekday IS NULL OR by_weekday <@ ARRAY[0,1,2,3,4,5,6]::smallint[]",
            name="by_weekday",
        ),
        CheckConstraint(
            "kind <> 'transfer' OR counter_account_id IS NOT NULL", name="transfer_shape"
        ),
        CheckConstraint(CHECK_MONEDA, name="currency"),
    )


class RecurringOccurrence(DomainBase):
    """Cada vencimiento concreto de una regla.

    Hace posibles el recordatorio antes del cargo (F-49), la alerta de subida de
    precio de la suscripción (F-30) y la proyección de saldo a fin de mes (F-47).
    """

    __tablename__ = "recurring_occurrences"

    recurring_rule_id: Mapped[uuid.UUID] = uuid_fk(
        "recurring_rules.id", ondelete="CASCADE", nullable=False
    )
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    expected_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    actual_amount: Mapped[Decimal | None] = mapped_column(Money)
    amount_change_pct: Mapped[Decimal | None] = mapped_column(Percentage)
    # Si el usuario borra el cargo, el servicio devuelve el vencimiento a `pending`.
    transaction_id: Mapped[uuid.UUID | None] = uuid_fk("transactions.id", ondelete="SET NULL")
    reminded_at: Mapped[datetime | None]
    alerted_at: Mapped[datetime | None]
    note: Mapped[str | None] = mapped_column(Text)

    rule: Mapped[RecurringRule] = relationship(
        back_populates="occurrences", foreign_keys=[recurring_rule_id]
    )

    __table_args__ = (
        fk_tenencia("recurring_occurrences", "transaction_id", "transactions", ondelete="SET NULL"),
        # Garantía de idempotencia del generador: se puede ejecutar el planificador
        # diez veces el mismo día y el INSERT ... ON CONFLICT DO NOTHING absorbe la
        # repetición.
        UniqueConstraint("recurring_rule_id", "due_on"),
        Index(
            "ix_recurring_occurrences_household_id_status_due_on",
            "household_id",
            "status",
            "due_on",
            postgresql_include=["expected_amount", "recurring_rule_id"],
        ),
        Index(
            "uq_recurring_occurrences_transaction_id",
            "transaction_id",
            unique=True,
            postgresql_where=text("transaction_id IS NOT NULL"),
        ),
        CheckConstraint(
            "status IN ('pending', 'created', 'matched', 'skipped', 'missed')", name="status"
        ),
        CheckConstraint(
            "status NOT IN ('created', 'matched') OR actual_amount IS NOT NULL", name="actual"
        ),
        CheckConstraint(
            "status NOT IN ('created', 'matched') OR transaction_id IS NOT NULL",
            name="transaction",
        ),
    )
