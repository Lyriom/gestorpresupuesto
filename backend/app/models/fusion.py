"""Bitácora y diario de deshacer de las fusiones de temáticas, comercios y productos."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.mixins import DomainBase, uuid_fk

ENTIDADES_FUSIONABLES = ("category", "payee", "product")
ESTADOS_FUSION = ("preview", "running", "done", "failed", "reverted")

# Lista blanca de tablas que la función de deshacer puede tocar. No es cosmética:
# `revert_merge()` construye SQL dinámico con `format('UPDATE %I ...')` y este
# `CHECK` es lo que garantiza que ningún nombre arbitrario llegue a ese `EXECUTE`.
TABLAS_REVERSIBLES = (
    "categories",
    "transactions",
    "transaction_splits",
    "invoice_lines",
    "budget_allocations",
    "categorization_rules",
    "recurring_rules",
    "goals",
    "products",
    "payees",
    "product_aliases",
    "product_prices",
    "saved_views",
    "alerts",
)


class MergeOperation(DomainBase):
    """Qué se fusionó con qué, con qué opciones y hasta cuándo se puede deshacer.

    `source_id` y `target_id` **no son claves ajenas**: la tabla es polimórfica y,
    sobre todo, es un registro de auditoría que debe sobrevivir aunque la entidad
    referida desaparezca. `source_label` y `target_label` congelan los nombres para
    que el histórico se lea sin resolver ninguna FK.
    """

    __tablename__ = "merge_operations"

    entity_type: Mapped[str] = mapped_column(String(10), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_label: Mapped[str] = mapped_column(Text, nullable=False)
    target_label: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="preview")
    options: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    source_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    # Deshacer la fusión madre deshace las hijas: son una unidad atómica.
    parent_merge_operation_id: Mapped[uuid.UUID | None] = uuid_fk(
        "merge_operations.id", ondelete="CASCADE"
    )
    performed_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    reverted_at: Mapped[datetime | None]
    reverted_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")
    undo_deadline: Mapped[datetime | None]
    error_message: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)

    changes: Mapped[list[MergeOperationChange]] = relationship(
        back_populates="operation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MergeOperationChange.seq",
        foreign_keys="MergeOperationChange.merge_operation_id",
    )

    __table_args__ = (
        Index(
            "ix_merge_operations_household_id_created_at",
            "household_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_merge_operations_household_id_entity_type_source_id",
            "household_id",
            "entity_type",
            "source_id",
        ),
        Index(
            "ix_merge_operations_household_id_target_id",
            "household_id",
            "entity_type",
            "target_id",
        ),
        Index(
            "ix_merge_operations_undo_deadline",
            "undo_deadline",
            postgresql_where=text("status = 'done'"),
        ),
        # Una previsualización viva por par origen-destino: evita que dos pestañas
        # del navegador peleen por la misma fusión.
        Index(
            "uq_merge_operations_running",
            "household_id",
            "entity_type",
            "source_id",
            unique=True,
            postgresql_where=text("status IN ('preview', 'running')"),
        ),
        CheckConstraint("entity_type IN ('category', 'payee', 'product')", name="entity_type"),
        CheckConstraint(
            "status IN ('preview', 'running', 'done', 'failed', 'reverted')", name="status"
        ),
        CheckConstraint("source_id <> target_id", name="not_self"),
        CheckConstraint(
            "status <> 'done' OR (source_snapshot IS NOT NULL AND finished_at IS NOT NULL)",
            name="done_has_snapshot",
        ),
        CheckConstraint("(status = 'reverted') = (reverted_at IS NOT NULL)", name="reverted"),
        CheckConstraint(
            "status <> 'failed' OR error_message IS NOT NULL", name="failed_has_message"
        ),
    )


class MergeOperationChange(DomainBase):
    """El diario de deshacer: una fila por cada valor que cambió."""

    __tablename__ = "merge_operation_changes"

    merge_operation_id: Mapped[uuid.UUID] = uuid_fk(
        "merge_operations.id", ondelete="CASCADE", nullable=False
    )
    # Secuencia global y no `row_number()` por fusión: la comprobación «¿alguien tocó
    # esta fila después de mi fusión?» compara el orden **entre** fusiones distintas.
    seq: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("nextval('merge_operation_changes_seq')"),
    )
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    row_pk: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    change_type: Mapped[str] = mapped_column(String(6), nullable=False)
    column_name: Mapped[str | None] = mapped_column(Text)
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    old_row: Mapped[dict | None] = mapped_column(JSONB)

    operation: Mapped[MergeOperation] = relationship(
        back_populates="changes", foreign_keys=[merge_operation_id]
    )

    __table_args__ = (
        Index("ix_merge_operation_changes_merge_operation_id_seq", "merge_operation_id", "seq"),
        # Comprobación de conflicto antes de deshacer.
        Index(
            "ix_merge_operation_changes_table_name_row_pk",
            "table_name",
            "row_pk",
            text("seq DESC"),
        ),
        CheckConstraint("change_type IN ('update', 'delete')", name="change_type"),
        CheckConstraint(
            "(change_type = 'update' AND column_name IS NOT NULL AND old_row IS NULL) "
            "OR (change_type = 'delete' AND column_name IS NULL AND old_row IS NOT NULL)",
            name="shape",
        ),
        CheckConstraint(
            "table_name IN (" + ", ".join(f"'{t}'" for t in TABLAS_REVERSIBLES) + ")",
            name="table_name",
        ),
    )
