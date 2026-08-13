"""Avisos accionables y control de envío de los resúmenes periódicos."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mixins import DomainBase, fk_tenencia, uuid_fk

TIPOS_AVISO = (
    "budget_overspend",
    "budget_near_limit",
    "product_price_increase",
    "recurring_price_increase",
    "recurring_due",
    "unusual_expense",
    "invoice_needs_review",
    "invoice_duplicate",
    "import_duplicate",
    "goal_at_risk",
    "reconciliation_mismatch",
    "low_balance_forecast",
)


class Alert(DomainBase):
    """Una sola tabla para todos los avisos accionables.

    Se unifican porque la interfaz los muestra en una sola bandeja y el ciclo de
    vida es idéntico: nacen, se leen, se descartan o se resuelven. El generador usa
    `INSERT ... ON CONFLICT (household_id, dedupe_key) DO UPDATE`, de forma que un
    sobrepaso que empeora **actualiza** el aviso en lugar de crear un segundo: es la
    respuesta directa al antipatrón del exceso de notificaciones.
    """

    __tablename__ = "alerts"

    type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False, server_default="info")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="new")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    # Identidad lógica del aviso: «budget_overspend:2026-08-01:<category_id>».
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    # Polimórfico y sin FK: los avisos cuyo sujeto ya no existe los borra el
    # barrendero nocturno.
    subject_table: Mapped[str | None] = mapped_column(Text)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    category_id: Mapped[uuid.UUID | None] = uuid_fk("categories.id", ondelete="SET NULL")
    period_month: Mapped[date | None] = mapped_column(Date)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    read_at: Mapped[datetime | None]
    dismissed_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]
    delivery: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        fk_tenencia("alerts", "category_id", "categories", ondelete="SET NULL"),
        UniqueConstraint("household_id", "dedupe_key"),
        # La bandeja: avisos vivos, más recientes primero.
        Index(
            "ix_alerts_household_id_status_triggered_at",
            "household_id",
            "status",
            text("triggered_at DESC"),
            postgresql_where=text("status IN ('new', 'read')"),
        ),
        Index("ix_alerts_household_id_type_period_month", "household_id", "type", "period_month"),
        Index(
            "ix_alerts_subject_table_subject_id",
            "subject_table",
            "subject_id",
            postgresql_where=text("subject_id IS NOT NULL"),
        ),
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="severity"),
        CheckConstraint("status IN ('new', 'read', 'dismissed', 'resolved')", name="status"),
        CheckConstraint("type IN (" + ", ".join(f"'{t}'" for t in TIPOS_AVISO) + ")", name="type"),
        CheckConstraint("(subject_table IS NULL) = (subject_id IS NULL)", name="subject"),
        CheckConstraint(
            "(status = 'dismissed') = (dismissed_at IS NOT NULL) "
            "AND (status = 'resolved') = (resolved_at IS NOT NULL)",
            name="status_timestamps",
        ),
    )


class DigestRun(DomainBase):
    """Control de envío del resumen semanal o mensual (F-45).

    Existe para no enviarlo dos veces ni saltarse una semana en silencio.
    """

    __tablename__ = "digest_runs"

    # `NULL` = todos los miembros del hogar.
    user_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="CASCADE")
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False, server_default="email")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    payload: Mapped[dict | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime | None]
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # `NULLS NOT DISTINCT` es imprescindible: sin él, el resumen «para todos los
        # miembros» (`user_id IS NULL`) podría duplicarse.
        Index(
            "uq_digest_runs_household_id_user_id_kind_period_from",
            "household_id",
            "user_id",
            "kind",
            "period_from",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_digest_runs_status_period_from", "status", "period_from"),
        CheckConstraint("kind IN ('weekly', 'monthly')", name="kind"),
        CheckConstraint("status IN ('pending', 'sent', 'skipped', 'error')", name="status"),
        CheckConstraint("period_to >= period_from", name="period"),
    )
