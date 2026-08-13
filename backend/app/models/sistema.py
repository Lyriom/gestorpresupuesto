"""Vistas guardadas y exportaciones de datos."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mixins import DomainBase, uuid_fk

ENTIDADES_VISTA = ("transactions", "invoices", "products", "reports")


class SavedView(DomainBase):
    """Filtros combinados guardados (F-42): el «Guardar vista» de la interfaz.

    `filters` puede contener `category_id`, así que la fusión de temáticas reescribe
    esas referencias: por eso esta tabla está en la lista blanca del diario de
    deshacer.
    """

    __tablename__ = "saved_views"

    # Las vistas son personales, no del hogar.
    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE", nullable=False)
    entity: Mapped[str] = mapped_column(String(16), nullable=False, server_default="transactions")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sort: Mapped[dict | None] = mapped_column(JSONB)
    columns: Mapped[dict | None] = mapped_column(JSONB)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))

    __table_args__ = (
        Index(
            "uq_saved_views_user_id_entity_name",
            "user_id",
            "entity",
            text("lower(name)"),
            unique=True,
        ),
        Index("ix_saved_views_household_id_user_id", "household_id", "user_id", "sort_order"),
        CheckConstraint(
            "entity IN ('transactions', 'invoices', 'products', 'reports')", name="entity"
        ),
        CheckConstraint("jsonb_typeof(filters) = 'object'", name="filters_object"),
    )


class DataExport(DomainBase):
    """Exportación y copia de seguridad de los datos propios (F-43).

    Se registra qué se sacó y cuándo, que es información sensible por sí misma.
    """

    __tablename__ = "data_exports"

    format: Mapped[str] = mapped_column(String(8), nullable=False)
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    storage_key: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(CHAR(64))
    # Filas por tabla, para poder comprobar la restauración.
    row_counts: Mapped[dict | None] = mapped_column(JSONB)
    includes_attachments: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    expires_at: Mapped[datetime | None]
    downloaded_at: Mapped[datetime | None]
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")

    __table_args__ = (
        Index(
            "ix_data_exports_household_id_created_at",
            "household_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_data_exports_expires_at",
            "expires_at",
            postgresql_where=text("status = 'ready'"),
        ),
        CheckConstraint("format IN ('json', 'csv', 'zip')", name="format"),
        CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'error', 'expired')", name="status"
        ),
        CheckConstraint(
            "status <> 'ready' OR (storage_key IS NOT NULL AND sha256 IS NOT NULL)",
            name="ready_has_file",
        ),
    )
