"""Transacciones, repartos, etiquetas y adjuntos: el movimiento de dinero."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Money
from app.models.mixins import CHECK_MONEDA, DomainBase, columna_moneda, fk_tenencia, uuid_fk

TIPOS_MOVIMIENTO = ("expense", "income", "transfer")
ESTADOS_TRANSACCION = ("pending", "cleared", "reconciled")
ORIGENES_CATEGORIA = ("user", "rule", "payee", "import", "invoice")


class Transaction(DomainBase):
    """El movimiento de dinero. Tabla más consultada del sistema.

    Los importes son **firmados**: un gasto es negativo, un ingreso positivo y una
    transferencia son dos filas que suman cero. Así el saldo es una única suma sin
    `CASE`, y una devolución de Amazon (gasto con importe positivo) reduce el
    gastado de su temática en lugar de inflar los ingresos del mes.
    """

    __tablename__ = "transactions"

    account_id: Mapped[uuid.UUID] = uuid_fk("accounts.id", ondelete="RESTRICT", nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    # Fecha contable: la que manda en los informes.
    booked_on: Mapped[date] = mapped_column(Date, nullable=False)
    value_on: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = columna_moneda()
    # RESTRICT sostiene la prohibición de borrar temáticas: solo archivar o fusionar.
    category_id: Mapped[uuid.UUID | None] = uuid_fk("categories.id", ondelete="RESTRICT")
    # El comercio es metadato; el movimiento no depende de él.
    payee_id: Mapped[uuid.UUID | None] = uuid_fk("payees.id", ondelete="SET NULL")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="cleared")
    transfer_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    split_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    split_total: Mapped[Decimal] = mapped_column(Money, nullable=False, server_default=text("0"))
    attachment_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    excluded_from_reports: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    recurring_rule_id: Mapped[uuid.UUID | None] = uuid_fk("recurring_rules.id", ondelete="SET NULL")
    # use_alter rompe el ciclo de claves ajenas con recurring_occurrences: la FK se
    # añade con un ALTER TABLE posterior a la creación de las dos tablas.
    recurring_occurrence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recurring_occurrences.id", ondelete="SET NULL", use_alter=True),
    )
    goal_id: Mapped[uuid.UUID | None] = uuid_fk("goals.id", ondelete="SET NULL")
    reconciliation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reconciliations.id", ondelete="SET NULL", use_alter=True),
    )
    # Borrar el registro del lote nunca debe borrar dinero: «deshacer importación»
    # es una operación explícita que borra primero las transacciones.
    import_batch_id: Mapped[uuid.UUID | None] = uuid_fk("import_batches.id", ondelete="SET NULL")
    external_id: Mapped[str | None] = mapped_column(Text)
    import_fingerprint: Mapped[str | None] = mapped_column(Text)
    categorized_by: Mapped[str] = mapped_column(String(8), nullable=False, server_default="user")
    applied_rule_id: Mapped[uuid.UUID | None] = uuid_fk(
        "categorization_rules.id", ondelete="SET NULL"
    )
    created_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")

    # `foreign_keys` es obligatorio en todas las relaciones: con las FK compuestas
    # de tenencia hay más de un camino entre cada par de tablas.
    splits: Mapped[list[TransactionSplit]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TransactionSplit.line_number",
        foreign_keys="TransactionSplit.transaction_id",
    )
    tag_links: Mapped[list[TransactionTag]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="TransactionTag.transaction_id",
    )

    __table_args__ = (
        fk_tenencia("transactions", "account_id", "accounts", ondelete="RESTRICT"),
        fk_tenencia("transactions", "category_id", "categories", ondelete="RESTRICT"),
        fk_tenencia("transactions", "payee_id", "payees", ondelete="SET NULL"),
        # El invariante central: una transacción es simple (tiene temática y no
        # tiene splits) o repartida (no tiene temática y sus splits suman su
        # importe). Nunca las dos cosas, así que ningún informe puede contar dos
        # veces el mismo dinero.
        CheckConstraint(
            "(split_count = 0 AND split_total = 0 "
            "AND (category_id IS NOT NULL OR kind = 'transfer')) "
            "OR (split_count > 0 AND category_id IS NULL AND split_total = amount "
            "AND kind <> 'transfer')",
            name="split_invariant",
        ),
        CheckConstraint("kind IN ('expense', 'income', 'transfer')", name="kind"),
        CheckConstraint("status IN ('pending', 'cleared', 'reconciled')", name="status"),
        CheckConstraint(
            "categorized_by IN ('user', 'rule', 'payee', 'import', 'invoice')",
            name="categorized_by",
        ),
        # Una transacción de cero euros es siempre un error de captura o de importación.
        CheckConstraint("amount <> 0", name="amount_not_zero"),
        CheckConstraint(CHECK_MONEDA, name="currency"),
        CheckConstraint(
            "kind <> 'transfer' "
            "OR (category_id IS NULL AND split_count = 0 AND transfer_group_id IS NOT NULL)",
            name="transfer_shape",
        ),
        CheckConstraint(
            "transfer_group_id IS NULL OR kind = 'transfer'", name="group_only_transfer"
        ),
        CheckConstraint("value_on IS NULL OR value_on >= booked_on - 30", name="value_on"),
        # Listado principal y filtros (F-42): el índice que más se usa.
        Index(
            "ix_transactions_household_id_booked_on",
            "household_id",
            text("booked_on DESC"),
            text("id DESC"),
        ),
        # Saldo de cuenta y extracto. INCLUDE permite index-only scan.
        Index(
            "ix_transactions_account_id_booked_on",
            "account_id",
            "booked_on",
            postgresql_include=["amount", "status"],
        ),
        # Gastado por temática y mes, rama de transacciones simples.
        Index(
            "ix_transactions_household_id_category_id_booked_on",
            "household_id",
            "category_id",
            "booked_on",
            postgresql_include=["amount", "kind"],
            postgresql_where=text(
                "split_count = 0 AND category_id IS NOT NULL AND NOT excluded_from_reports"
            ),
        ),
        # Top comercios (F-37) y detección de recurrentes (F-29).
        Index(
            "ix_transactions_household_id_payee_id_booked_on",
            "household_id",
            "payee_id",
            text("booked_on DESC"),
            postgresql_include=["amount"],
            postgresql_where=text("payee_id IS NOT NULL"),
        ),
        # Cash flow y comparativa mes a mes (F-19, F-36).
        Index(
            "ix_transactions_household_id_kind_booked_on",
            "household_id",
            "kind",
            "booked_on",
            postgresql_include=["amount"],
            postgresql_where=text("NOT excluded_from_reports"),
        ),
        Index(
            "ix_transactions_transfer_group_id",
            "transfer_group_id",
            postgresql_where=text("transfer_group_id IS NOT NULL"),
        ),
        # Duplicado seguro de importación: solo cuando el banco da un ID propio.
        Index(
            "uq_transactions_account_id_external_id",
            "account_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        # Huella blanda: NO es única (dos cafés iguales el mismo día son legítimos);
        # sirve para marcar la fila importada como sospechosa y que decida el usuario.
        Index(
            "ix_transactions_household_id_import_fingerprint",
            "household_id",
            "import_fingerprint",
            postgresql_where=text("import_fingerprint IS NOT NULL"),
        ),
        Index(
            "ix_transactions_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
        Index(
            "ix_transactions_recurring_rule_id_booked_on",
            "recurring_rule_id",
            text("booked_on DESC"),
            postgresql_where=text("recurring_rule_id IS NOT NULL"),
        ),
        UniqueConstraint("household_id", "id"),
    )


class TransactionSplit(DomainBase):
    """Reparto de una transacción entre varias temáticas (F-08).

    También es el puente entre la factura y el presupuesto: al confirmar una
    factura, cada línea categorizada genera un split (F-17).
    """

    __tablename__ = "transaction_splits"

    transaction_id: Mapped[uuid.UUID] = uuid_fk(
        "transactions.id", ondelete="CASCADE", nullable=False
    )
    category_id: Mapped[uuid.UUID] = uuid_fk("categories.id", ondelete="RESTRICT", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    line_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    # Perder la trazabilidad no debe borrar el reparto del dinero.
    invoice_line_id: Mapped[uuid.UUID | None] = uuid_fk("invoice_lines.id", ondelete="SET NULL")

    transaction: Mapped[Transaction] = relationship(
        back_populates="splits", foreign_keys=[transaction_id]
    )

    __table_args__ = (
        fk_tenencia("transaction_splits", "transaction_id", "transactions", ondelete="CASCADE"),
        fk_tenencia("transaction_splits", "category_id", "categories", ondelete="RESTRICT"),
        # DEFERRABLE porque reordenar splits o colapsarlos durante una fusión
        # reasigna `line_number` en varias filas dentro de la misma sentencia.
        UniqueConstraint(
            "transaction_id",
            "line_number",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        Index(
            "ix_transaction_splits_transaction_id",
            "transaction_id",
            postgresql_include=["category_id", "amount"],
        ),
        Index(
            "ix_transaction_splits_household_id_category_id",
            "household_id",
            "category_id",
            postgresql_include=["amount", "transaction_id"],
        ),
        # Una línea de factura genera como máximo un split: si no, revisar dos veces
        # la misma factura duplicaría el gasto.
        Index(
            "uq_transaction_splits_invoice_line_id",
            "invoice_line_id",
            unique=True,
            postgresql_where=text("invoice_line_id IS NOT NULL"),
        ),
        CheckConstraint("amount <> 0", name="amount_not_zero"),
        CheckConstraint("line_number >= 1", name="line_number"),
    )


class Tag(DomainBase):
    """Etiqueta libre transversal a la temática (F-35)."""

    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    color_slot: Mapped[int | None] = mapped_column(SmallInteger)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    archived_at: Mapped[datetime | None]

    __table_args__ = (
        Index(
            "uq_tags_household_id_normalized_name",
            "household_id",
            "normalized_name",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index(
            "ix_tags_household_id_usage_count",
            "household_id",
            text("usage_count DESC"),
            postgresql_where=text("archived_at IS NULL"),
        ),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("color_slot IS NULL OR color_slot BETWEEN 1 AND 12", name="color_slot"),
    )


class TransactionTag(DomainBase):
    """Relación N:M entre transacciones y etiquetas.

    Ambas claves ajenas van en CASCADE: la fila *es* la relación. Borrar una
    etiqueta la desasigna sin tocar el dinero, que es lo que se espera de una
    etiqueta libre (a diferencia de una temática, que nunca se borra).
    """

    __tablename__ = "transaction_tags"

    transaction_id: Mapped[uuid.UUID] = uuid_fk(
        "transactions.id", ondelete="CASCADE", nullable=False
    )
    tag_id: Mapped[uuid.UUID] = uuid_fk("tags.id", ondelete="CASCADE", nullable=False)

    transaction: Mapped[Transaction] = relationship(
        back_populates="tag_links", foreign_keys=[transaction_id]
    )

    __table_args__ = (
        fk_tenencia("transaction_tags", "transaction_id", "transactions", ondelete="CASCADE"),
        UniqueConstraint("transaction_id", "tag_id"),
        # «Cuánto me ha costado el viaje a Roma»: del tag a las transacciones.
        Index(
            "ix_transaction_tags_household_id_tag_id",
            "household_id",
            "tag_id",
            postgresql_include=["transaction_id"],
        ),
    )


class Attachment(DomainBase):
    """Imagen o PDF de una transacción (F-21) o el original de una factura (F-12).

    Los bytes viven en `settings.upload_dir`; aquí solo va el metadato. El fichero
    se borra después del `COMMIT`, nunca antes, y un barrendero nocturno elimina
    los huérfanos.
    """

    __tablename__ = "attachments"

    transaction_id: Mapped[uuid.UUID | None] = uuid_fk("transactions.id", ondelete="CASCADE")
    invoice_id: Mapped[uuid.UUID | None] = uuid_fk("invoices.id", ondelete="CASCADE")
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(SmallInteger)
    uploaded_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")

    __table_args__ = (
        fk_tenencia("attachments", "transaction_id", "transactions", ondelete="CASCADE"),
        fk_tenencia("attachments", "invoice_id", "invoices", ondelete="CASCADE"),
        # `num_nonnulls(...) = 1` expresa «exactamente un dueño» sin disparadores.
        CheckConstraint("num_nonnulls(transaction_id, invoice_id) = 1", name="single_owner"),
        CheckConstraint("byte_size > 0", name="byte_size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256"),
        UniqueConstraint("storage_key"),
        Index(
            "ix_attachments_transaction_id",
            "transaction_id",
            postgresql_where=text("transaction_id IS NOT NULL"),
        ),
        Index(
            "ix_attachments_invoice_id",
            "invoice_id",
            postgresql_where=text("invoice_id IS NOT NULL"),
        ),
        Index("ix_attachments_household_id_sha256", "household_id", "sha256"),
    )
