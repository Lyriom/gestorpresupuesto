"""Importación de extractos: el lote y cada una de sus filas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    Date,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Money
from app.models.mixins import DomainBase, fk_tenencia, uuid_fk

# Estados del contrato de API (§4.11 de api.md). `needs_mapping` es el que hace que
# la interfaz pida el mapeo de columnas (RN-67); `reverted` no es un estado: una
# importación deshecha queda en `committed` con `reverted_at`, para no perder que
# hubo un commit.
ESTADOS_LOTE = ("analyzing", "needs_mapping", "ready", "committed", "failed", "discarded")
CHECK_ESTADOS_LOTE = (
    "status IN ('analyzing', 'needs_mapping', 'ready', 'committed', 'failed', 'discarded')"
)

ESTADOS_FILA = ("new", "imported", "duplicate", "skipped", "error")


class ImportBatch(DomainBase):
    """Registro de cada fichero importado (F-25, F-33).

    Sin esta tabla, «deshacer la importación de ayer» es imposible.
    """

    __tablename__ = "import_batches"

    # `NULL` si el fichero trae la cuenta por fila.
    account_id: Mapped[uuid.UUID | None] = uuid_fk("accounts.id", ondelete="RESTRICT")
    source_type: Mapped[str] = mapped_column(String(4), nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # El original se conserva 90 días.
    storage_key: Mapped[str | None] = mapped_column(Text)
    encoding: Mapped[str | None] = mapped_column(String(20))
    delimiter: Mapped[str | None] = mapped_column(CHAR(1))
    # `,` en los bancos españoles.
    decimal_separator: Mapped[str | None] = mapped_column(CHAR(1))
    date_format: Mapped[str | None] = mapped_column(String(20))
    column_mapping: Mapped[dict | None] = mapped_column(JSONB)
    sign_convention: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="signed"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="analyzing")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    applied_at: Mapped[datetime | None]
    reverted_at: Mapped[datetime | None]
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")

    rows: Mapped[list[ImportRow]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ImportRow.row_number",
        foreign_keys="ImportRow.import_batch_id",
    )

    __table_args__ = (
        fk_tenencia("import_batches", "account_id", "accounts", ondelete="RESTRICT"),
        # Reimportar el mismo fichero se avisa, no se bloquea: puede ser legítimo si
        # el extracto anterior estaba incompleto.
        Index("ix_import_batches_household_id_file_sha256", "household_id", "file_sha256"),
        Index(
            "ix_import_batches_household_id_created_at",
            "household_id",
            text("created_at DESC"),
        ),
        CheckConstraint("source_type IN ('csv', 'ofx', 'qif')", name="source_type"),
        CheckConstraint(CHECK_ESTADOS_LOTE, name="status"),
        CheckConstraint("sign_convention IN ('signed', 'debit_credit')", name="sign_convention"),
        CheckConstraint(
            "row_count >= 0 AND imported_count >= 0 AND duplicate_count >= 0 "
            "AND error_count >= 0 AND imported_count <= row_count",
            name="counts",
        ),
        CheckConstraint(
            "source_type <> 'csv' "
            "OR status IN ('analyzing', 'needs_mapping', 'failed') "
            "OR column_mapping IS NOT NULL",
            name="csv_needs_mapping",
        ),
    )


class ImportRow(DomainBase):
    """Cada fila del fichero, con su estado.

    Política de duplicados, en dos niveles y ninguno silencioso: con `external_id`
    el índice único de `transactions` rechaza el alta; sin él se compara la huella y
    la fila se marca `duplicate` sin importarse, pero con un interruptor «importar
    igualmente». Dos cafés de 1,20 € el mismo día son legítimos.
    """

    __tablename__ = "import_rows"

    import_batch_id: Mapped[uuid.UUID] = uuid_fk(
        "import_batches.id", ondelete="CASCADE", nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    parsed_booked_on: Mapped[date | None] = mapped_column(Date)
    parsed_amount: Mapped[Decimal | None] = mapped_column(Money)
    parsed_description: Mapped[str | None] = mapped_column(Text)
    parsed_external_id: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="new")
    duplicate_of_id: Mapped[uuid.UUID | None] = uuid_fk("transactions.id", ondelete="SET NULL")
    transaction_id: Mapped[uuid.UUID | None] = uuid_fk("transactions.id", ondelete="SET NULL")
    matched_rule_id: Mapped[uuid.UUID | None] = uuid_fk(
        "categorization_rules.id", ondelete="SET NULL"
    )
    message: Mapped[str | None] = mapped_column(Text)

    batch: Mapped[ImportBatch] = relationship(back_populates="rows", foreign_keys=[import_batch_id])

    __table_args__ = (
        fk_tenencia("import_rows", "transaction_id", "transactions", ondelete="SET NULL"),
        fk_tenencia("import_rows", "duplicate_of_id", "transactions", ondelete="SET NULL"),
        UniqueConstraint("import_batch_id", "row_number"),
        Index("ix_import_rows_import_batch_id_status", "import_batch_id", "status"),
        Index(
            "ix_import_rows_household_id_fingerprint",
            "household_id",
            "fingerprint",
            postgresql_where=text("fingerprint IS NOT NULL"),
        ),
        Index(
            "uq_import_rows_transaction_id",
            "transaction_id",
            unique=True,
            postgresql_where=text("transaction_id IS NOT NULL"),
        ),
        CheckConstraint(
            "status IN ('new', 'imported', 'duplicate', 'skipped', 'error')", name="status"
        ),
        CheckConstraint(
            "status <> 'imported' OR transaction_id IS NOT NULL",
            name="imported_has_transaction",
        ),
        CheckConstraint("row_number >= 1", name="row_number"),
    )
