"""Facturas en PDF: cabecera, líneas y plantillas de extracción por emisor."""

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
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Confidence, Money, Quantity, Score, UnitPrice
from app.models.mixins import CHECK_MONEDA, DomainBase, columna_moneda, fk_tenencia, uuid_fk

# Los cinco estados del contrato de API (§3.13 de api.md). `discarded` es
# imprescindible para RN-46: una factura descartada no puede quedar
# indistinguible de una confirmada, o `confirm` dejaría de ser irrepetible.
ESTADOS_FACTURA = ("processing", "pending_review", "failed", "confirmed", "discarded")
CHECK_ESTADOS_FACTURA = (
    "status IN ('processing', 'pending_review', 'failed', 'confirmed', 'discarded')"
)

# `MetodoExtraccion` de `extraccion_pdf.py`, tal cual.
METODOS_EXTRACCION = ("tabla", "texto", "ocr", "ninguno")

METODOS_EMPAREJAMIENTO = ("barcode", "grouping_key", "alias", "trigram_fuzzy", "manual", "none")


class Invoice(DomainBase):
    """Destino de persistencia de `FacturaExtraida`, con su estado de procesado.

    La correspondencia con la dataclass es 1:1: `emisor` → `issuer_name`,
    `nif_emisor` → `issuer_tax_id`, `metodo` → `extraction_method`,
    `confianza` → `confidence`, `avisos` → `warnings`, `lineas` → `invoice_lines`.
    """

    __tablename__ = "invoices"

    payee_id: Mapped[uuid.UUID | None] = uuid_fk("payees.id", ondelete="SET NULL")
    # Una transacción puede pagar varias facturas (una domiciliación que agrupa dos
    # recibos) y hay facturas que se registran antes de pagarse: la FK va en el lado
    # de la factura y sin UNIQUE.
    transaction_id: Mapped[uuid.UUID | None] = uuid_fk("transactions.id", ondelete="SET NULL")
    issuer_name: Mapped[str | None] = mapped_column(Text)
    issuer_tax_id: Mapped[str | None] = mapped_column(Text)
    invoice_number: Mapped[str | None] = mapped_column(Text)
    issued_on: Mapped[date | None] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date)
    # Periodo facturado: imprescindible en luz, gas y telefonía.
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    taxable_base: Mapped[Decimal | None] = mapped_column(Money)
    tax_amount: Mapped[Decimal | None] = mapped_column(Money)
    total_amount: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str] = columna_moneda()
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="processing")
    # `email` y `api` están desde el día uno para que F-51 no necesite migración.
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="upload")
    extraction_method: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="ninguno"
    )
    extraction_template_id: Mapped[uuid.UUID | None] = uuid_fk(
        "extraction_templates.id", ondelete="SET NULL"
    )
    page_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    confidence: Mapped[Decimal] = mapped_column(
        Confidence, nullable=False, server_default=text("0")
    )
    warnings: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # Texto crudo, para reprocesar sin volver a leer el PDF.
    raw_text: Mapped[str | None] = mapped_column(Text)
    # Las cuatro son nulas en una factura metida a mano, que no tiene documento.
    # La restricción `fichero_si_y_solo_si_subida` exige que vayan las cuatro
    # juntas o ninguna, según el origen: una factura subida sin su PDF sigue
    # siendo imposible.
    file_name: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    content_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    duplicate_of_id: Mapped[uuid.UUID | None] = uuid_fk("invoices.id", ondelete="SET NULL")
    processing_started_at: Mapped[datetime | None]
    processed_at: Mapped[datetime | None]
    # Instante de la confirmación (el `confirmed_at` del contrato de API).
    reviewed_at: Mapped[datetime | None]
    reviewed_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")
    error_message: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    uploaded_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")

    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InvoiceLine.line_number",
        foreign_keys="InvoiceLine.invoice_id",
    )

    __table_args__ = (
        fk_tenencia("invoices", "payee_id", "payees", ondelete="SET NULL"),
        fk_tenencia("invoices", "transaction_id", "transactions", ondelete="SET NULL"),
        fk_tenencia("invoices", "duplicate_of_id", "invoices", ondelete="SET NULL"),
        # Nivel 1 de detección de duplicados: bytes idénticos, se bloquea.
        Index(
            "uq_invoices_household_id_content_sha256",
            "household_id",
            "content_sha256",
            unique=True,
        ),
        # Nivel 2: duplicado lógico. Dos facturas distintas del mismo emisor no
        # comparten número, así que también se bloquea.
        Index(
            "uq_invoices_household_id_issuer_tax_id_invoice_number",
            "household_id",
            "issuer_tax_id",
            "invoice_number",
            unique=True,
            postgresql_where=text(
                "issuer_tax_id IS NOT NULL AND invoice_number IS NOT NULL "
                "AND status <> 'failed' AND duplicate_of_id IS NULL"
            ),
        ),
        # Nivel 3: sospecha heurística (mismo emisor, fecha y total). No se bloquea:
        # se crea un aviso y el usuario decide.
        Index(
            "ix_invoices_household_id_payee_id_issued_on",
            "household_id",
            "payee_id",
            "issued_on",
            postgresql_include=["total_amount"],
        ),
        Index(
            "ix_invoices_household_id_status_created_at",
            "household_id",
            "status",
            text("created_at DESC"),
        ),
        Index("ix_invoices_household_id_issued_on", "household_id", text("issued_on DESC")),
        UniqueConstraint("household_id", "id"),
        CheckConstraint(CHECK_ESTADOS_FACTURA, name="status"),
        CheckConstraint(
            "extraction_method IN ('tabla', 'texto', 'ocr', 'ninguno')",
            name="extraction_method",
        ),
        CheckConstraint("source IN ('upload', 'email', 'api', 'manual')", name="source"),
        CheckConstraint(
            "(source = 'manual' AND num_nulls("
            "file_name, storage_key, byte_size, content_sha256) = 4) OR "
            "(source <> 'manual' AND num_nulls("
            "file_name, storage_key, byte_size, content_sha256) = 0)",
            name="fichero_si_y_solo_si_subida",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence"),
        CheckConstraint("jsonb_typeof(warnings) = 'array'", name="warnings_is_array"),
        CheckConstraint(
            "period_to IS NULL OR period_from IS NULL OR period_to >= period_from",
            name="period",
        ),
        # «La interfaz obliga al usuario a revisar antes de guardar», en SQL: una
        # factura no llega a `confirmed` sin fecha ni total, sea cual sea la
        # confianza del parser.
        CheckConstraint(
            "status <> 'confirmed' "
            "OR (issued_on IS NOT NULL AND total_amount IS NOT NULL "
            "AND reviewed_at IS NOT NULL)",
            name="confirmed_needs_data",
        ),
        CheckConstraint(
            "status <> 'failed' OR error_message IS NOT NULL", name="error_has_message"
        ),
        CheckConstraint(
            "duplicate_of_id IS NULL OR duplicate_of_id <> id", name="duplicate_not_self"
        ),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="content_sha256"),
        CheckConstraint(CHECK_MONEDA, name="currency"),
    )


class InvoiceLine(DomainBase):
    """Cada línea de producto o concepto de la factura (F-13).

    Se guardan las dos formas de la descripción a propósito: la cruda es la prueba
    documental y la normalizada es la que se indexa y se compara.
    """

    __tablename__ = "invoice_lines"

    invoice_id: Mapped[uuid.UUID] = uuid_fk("invoices.id", ondelete="CASCADE", nullable=False)
    line_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Quantity)
    unit: Mapped[str | None] = mapped_column(String(8))
    # Cuatro decimales: redondear a céntimos falsearía el histórico de precios.
    unit_price: Mapped[Decimal | None] = mapped_column(UnitPrice)
    line_total: Mapped[Decimal | None] = mapped_column(Money)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount_amount: Mapped[Decimal | None] = mapped_column(Money)
    confidence: Mapped[Decimal] = mapped_column(
        Confidence, nullable=False, server_default=text("0.5")
    )
    normalized_description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    brand_guess: Mapped[str | None] = mapped_column(Text)
    size_value: Mapped[Decimal | None] = mapped_column(Quantity)
    size_unit: Mapped[str | None] = mapped_column(String(8))
    product_code: Mapped[str | None] = mapped_column(Text)
    grouping_key: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # Desenlazar no borra la línea, y la fusión de productos reasigna.
    product_id: Mapped[uuid.UUID | None] = uuid_fk("products.id", ondelete="SET NULL")
    category_id: Mapped[uuid.UUID | None] = uuid_fk("categories.id", ondelete="RESTRICT")
    match_method: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")
    match_score: Mapped[Decimal | None] = mapped_column(Score)
    is_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    was_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Línea que no es producto: portes, redondeo, potencia contratada.
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    invoice: Mapped[Invoice] = relationship(back_populates="lines", foreign_keys=[invoice_id])

    __table_args__ = (
        fk_tenencia("invoice_lines", "invoice_id", "invoices", ondelete="CASCADE"),
        fk_tenencia("invoice_lines", "product_id", "products", ondelete="SET NULL"),
        fk_tenencia("invoice_lines", "category_id", "categories", ondelete="RESTRICT"),
        UniqueConstraint("invoice_id", "line_number", deferrable=True, initially="IMMEDIATE"),
        Index("ix_invoice_lines_invoice_id", "invoice_id", "line_number"),
        # Emparejamiento por clave exacta: primer paso del pipeline de productos.
        Index("ix_invoice_lines_household_id_grouping_key", "household_id", "grouping_key"),
        Index(
            "ix_invoice_lines_product_id",
            "product_id",
            postgresql_where=text("product_id IS NOT NULL"),
        ),
        Index(
            "ix_invoice_lines_household_id_category_id",
            "household_id",
            "category_id",
            postgresql_include=["line_total"],
        ),
        # Cola de revisión: líneas de baja confianza o sin producto.
        Index(
            "ix_invoice_lines_household_id_confidence",
            "household_id",
            "confidence",
            postgresql_where=text("NOT is_reviewed AND NOT excluded"),
        ),
        Index(
            "ix_invoice_lines_normalized_description_trgm",
            "normalized_description",
            postgresql_using="gin",
            postgresql_ops={"normalized_description": "gin_trgm_ops"},
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence"),
        CheckConstraint(
            "match_method IN ('barcode', 'grouping_key', 'alias', 'trigram_fuzzy', "
            "'manual', 'none')",
            name="match_method",
        ),
        CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 100)",
            name="match_score",
        ),
        # Evita el estado sucio más probable: una línea con producto pero sin
        # registro de cómo se decidió el enlace, imposible de auditar.
        CheckConstraint("(product_id IS NULL) = (match_method = 'none')", name="match_coherent"),
        CheckConstraint("quantity IS NULL OR quantity <> 0", name="quantity"),
        CheckConstraint("line_number >= 1", name="line_number"),
        CheckConstraint("tax_rate IS NULL OR (tax_rate >= 0 AND tax_rate <= 100)", name="tax_rate"),
    )


class ExtractionTemplate(DomainBase):
    """Cómo se interpreta el PDF de un proveedor concreto (F-40).

    `household_id` **nulable** es la única excepción del modelo: las plantillas de
    serie (Iberdrola, Endesa, Movistar) son datos de la instalación, no de un hogar.
    """

    __tablename__ = "extraction_templates"

    household_id: Mapped[uuid.UUID | None] = uuid_fk(
        "households.id", ondelete="CASCADE", index=True
    )
    payee_id: Mapped[uuid.UUID | None] = uuid_fk("payees.id", ondelete="SET NULL")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_pattern: Mapped[str | None] = mapped_column(Text)
    issuer_tax_id: Mapped[str | None] = mapped_column(Text)
    # Menor gana; las de hogar ganan a las de serie.
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("100"))
    page_settings: Mapped[dict | None] = mapped_column(JSONB)
    header_patterns: Mapped[dict | None] = mapped_column(JSONB)
    line_patterns: Mapped[dict | None] = mapped_column(JSONB)
    post_rules: Mapped[dict | None] = mapped_column(JSONB)
    default_category_id: Mapped[uuid.UUID | None] = uuid_fk("categories.id", ondelete="SET NULL")
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    miss_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_used_at: Mapped[datetime | None]
    created_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")

    __table_args__ = (
        Index(
            "ix_extraction_templates_household_id_priority",
            "household_id",
            "priority",
            postgresql_where=text("is_active"),
        ),
        Index(
            "ix_extraction_templates_issuer_tax_id",
            "issuer_tax_id",
            postgresql_where=text("issuer_tax_id IS NOT NULL AND is_active"),
        ),
        Index(
            "ix_extraction_templates_payee_id",
            "payee_id",
            postgresql_where=text("payee_id IS NOT NULL"),
        ),
        CheckConstraint(
            "issuer_pattern IS NOT NULL OR issuer_tax_id IS NOT NULL OR payee_id IS NOT NULL",
            name="selector",
        ),
        CheckConstraint("hit_count >= 0 AND miss_count >= 0", name="counts"),
    )
