"""Comercios y proveedores: el emisor como entidad propia, no como texto libre."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mixins import DomainBase, fk_tenencia, uuid_fk

TIPOS_COMERCIO = ("merchant", "supplier", "employer", "person", "institution")


class Payee(DomainBase):
    """El comercio como entidad estable.

    Es lo que hace posibles el ranking de comercios (F-37), la comparación de
    precio entre proveedores (F-38) y las plantillas de extracción por emisor
    (F-40).
    """

    __tablename__ = "payees"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    # `sin_acentos().lower()` sin ruido: es la base del trigrama y de la unicidad.
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, server_default="merchant")
    tax_id: Mapped[str | None] = mapped_column(Text)
    # Perder la sugerencia de temática no es grave.
    default_category_id: Mapped[uuid.UUID | None] = uuid_fk("categories.id", ondelete="SET NULL")
    website: Mapped[str | None] = mapped_column(Text)
    # Fichero local, nunca una URL externa.
    logo_key: Mapped[str | None] = mapped_column(Text)
    color_slot: Mapped[int | None] = mapped_column(SmallInteger)
    is_subscription_provider: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    transaction_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_seen_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None]
    merged_into_id: Mapped[uuid.UUID | None] = uuid_fk("payees.id", ondelete="RESTRICT")

    __table_args__ = (
        Index(
            "uq_payees_household_id_normalized_name",
            "household_id",
            "normalized_name",
            unique=True,
            postgresql_where=text("archived_at IS NULL AND merged_into_id IS NULL"),
        ),
        Index(
            "ix_payees_normalized_name_trgm",
            "normalized_name",
            postgresql_using="gin",
            postgresql_ops={"normalized_name": "gin_trgm_ops"},
        ),
        # Reconocer al emisor de una factura nueva por NIF, que es fiable, en lugar
        # de por el nombre, que se detecta con heurísticas.
        Index(
            "uq_payees_household_id_tax_id",
            "household_id",
            "tax_id",
            unique=True,
            postgresql_where=text("tax_id IS NOT NULL AND merged_into_id IS NULL"),
        ),
        Index(
            "ix_payees_household_id_transaction_count",
            "household_id",
            text("transaction_count DESC"),
            postgresql_where=text("archived_at IS NULL"),
        ),
        UniqueConstraint("household_id", "id"),
        fk_tenencia("payees", "default_category_id", "categories", ondelete="SET NULL"),
        fk_tenencia("payees", "merged_into_id", "payees", ondelete="RESTRICT"),
        CheckConstraint(
            "kind IN ('merchant', 'supplier', 'employer', 'person', 'institution')",
            name="kind",
        ),
        CheckConstraint("merged_into_id IS NULL OR merged_into_id <> id", name="merge_not_self"),
        CheckConstraint(
            "merged_into_id IS NULL OR archived_at IS NOT NULL", name="merged_is_archived"
        ),
    )
