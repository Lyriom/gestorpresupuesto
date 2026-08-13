"""Catálogo canónico de productos, sus grafías conocidas y su historial de precios."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Money, Percentage, Quantity, Score, UnitPrice
from app.models.mixins import CHECK_MONEDA, DomainBase, columna_moneda, fk_tenencia, uuid_fk


class Product(DomainBase):
    """El producto como entidad estable (F-15, F-38, F-39).

    Es lo que convierte «LECHE PASCUAL 1L BRIK» y «Leche Pascual brik 1 l» en una
    sola serie de precios. `grouping_key` viene de `clave_agrupacion()` y es la
    identidad determinista; el código de barras manda sobre cualquier heurística.
    """

    __tablename__ = "products"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    grouping_key: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text)
    size_value: Mapped[Decimal | None] = mapped_column(Quantity)
    size_unit: Mapped[str | None] = mapped_column(String(8))
    barcode: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(8))
    category_id: Mapped[uuid.UUID | None] = uuid_fk("categories.id", ondelete="SET NULL")
    is_basket_item: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    price_alert_threshold_pct: Mapped[Decimal | None] = mapped_column(Percentage)
    first_seen_on: Mapped[date | None] = mapped_column(Date)
    last_seen_on: Mapped[date | None] = mapped_column(Date)
    last_unit_price: Mapped[Decimal | None] = mapped_column(UnitPrice)
    price_observation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None]
    merged_into_id: Mapped[uuid.UUID | None] = uuid_fk("products.id", ondelete="RESTRICT")

    aliases: Mapped[list[ProductAlias]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="ProductAlias.product_id",
    )
    prices: Mapped[list[ProductPrice]] = relationship(
        back_populates="product",
        passive_deletes=True,
        foreign_keys="ProductPrice.product_id",
    )

    __table_args__ = (
        fk_tenencia("products", "category_id", "categories", ondelete="SET NULL"),
        fk_tenencia("products", "merged_into_id", "products", ondelete="RESTRICT"),
        # Identidad determinista: dos líneas con la misma clave son el mismo producto.
        Index(
            "uq_products_household_id_grouping_key",
            "household_id",
            "grouping_key",
            unique=True,
            postgresql_where=text("merged_into_id IS NULL"),
        ),
        Index(
            "uq_products_household_id_barcode",
            "household_id",
            "barcode",
            unique=True,
            postgresql_where=text("barcode IS NOT NULL AND merged_into_id IS NULL"),
        ),
        # Preselección de candidatos para RapidFuzz: GIN y no GiST porque el catálogo
        # se lee mucho más de lo que se escribe.
        Index(
            "ix_products_canonical_name_trgm",
            "canonical_name",
            postgresql_using="gin",
            postgresql_ops={"canonical_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_household_id_basket",
            "household_id",
            postgresql_where=text("is_basket_item AND archived_at IS NULL"),
        ),
        Index(
            "ix_products_household_id_last_seen_on",
            "household_id",
            text("last_seen_on DESC"),
            postgresql_where=text("archived_at IS NULL"),
        ),
        UniqueConstraint("household_id", "id"),
        CheckConstraint("length(btrim(grouping_key)) > 0", name="grouping_key_not_blank"),
        # Refleja la regla de `es_mismo_producto()`: el tamaño es valor **y** unidad
        # o no es nada, o el veto por tamaño distinto dejaría de funcionar.
        CheckConstraint("(size_value IS NULL) = (size_unit IS NULL)", name="size"),
        CheckConstraint("merged_into_id IS NULL OR merged_into_id <> id", name="merge_not_self"),
        CheckConstraint(
            "merged_into_id IS NULL OR archived_at IS NOT NULL", name="merged_is_archived"
        ),
        CheckConstraint("barcode IS NULL OR barcode ~ '^[0-9A-Za-z/-]{4,20}$'", name="barcode"),
    )


class ProductAlias(DomainBase):
    """Memoria del emparejamiento: cada grafía vista apunta a su producto canónico.

    Es lo que hace que RapidFuzz se ejecute una vez por grafía nueva y no una vez
    por línea de factura.
    """

    __tablename__ = "product_aliases"

    product_id: Mapped[uuid.UUID] = uuid_fk("products.id", ondelete="CASCADE", nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    grouping_key: Mapped[str | None] = mapped_column(Text)
    # Un ejemplo literal, para poder explicar la decisión al usuario.
    raw_sample: Mapped[str | None] = mapped_column(Text)
    payee_id: Mapped[uuid.UUID | None] = uuid_fk("payees.id", ondelete="SET NULL")
    match_method: Mapped[str] = mapped_column(String(16), nullable=False)
    match_score: Mapped[Decimal | None] = mapped_column(Score)
    times_seen: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    last_seen_on: Mapped[date | None] = mapped_column(Date)
    confirmed_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")
    # Un alias confirmado a mano no se vuelve a cuestionar.
    confirmed_at: Mapped[datetime | None]

    product: Mapped[Product] = relationship(back_populates="aliases", foreign_keys=[product_id])

    __table_args__ = (
        fk_tenencia("product_aliases", "product_id", "products", ondelete="CASCADE"),
        fk_tenencia("product_aliases", "payee_id", "payees", ondelete="SET NULL"),
        Index(
            "uq_product_aliases_household_id_normalized_text",
            "household_id",
            "normalized_text",
            unique=True,
        ),
        Index("ix_product_aliases_product_id", "product_id"),
        Index(
            "ix_product_aliases_household_id_grouping_key",
            "household_id",
            "grouping_key",
            postgresql_where=text("grouping_key IS NOT NULL"),
        ),
        Index(
            "ix_product_aliases_normalized_text_trgm",
            "normalized_text",
            postgresql_using="gin",
            postgresql_ops={"normalized_text": "gin_trgm_ops"},
        ),
        CheckConstraint(
            "match_method IN ('barcode', 'grouping_key', 'alias', 'trigram_fuzzy', 'manual')",
            name="match_method",
        ),
        CheckConstraint("times_seen >= 1", name="times_seen"),
    )


class ProductPrice(DomainBase):
    """Una fila por cada precio unitario observado, con fecha y proveedor (F-15).

    No se deriva de `invoice_lines` porque hay precios que no vienen de una factura,
    porque una línea puede quedar excluida sin que eso borre la observación
    histórica, y porque el índice del informe de evolución sería un índice sobre una
    tabla diez veces mayor.
    """

    __tablename__ = "product_prices"

    # El historial de precios es el activo diferencial del producto: un producto con
    # observaciones no se borra, se archiva o se fusiona.
    product_id: Mapped[uuid.UUID] = uuid_fk("products.id", ondelete="RESTRICT", nullable=False)
    payee_id: Mapped[uuid.UUID | None] = uuid_fk("payees.id", ondelete="SET NULL")
    # Si se borra la factura, la observación permanece sin origen documental: perder
    # el PDF no debe reescribir la historia de lo que costó el aceite en marzo.
    invoice_line_id: Mapped[uuid.UUID | None] = uuid_fk("invoice_lines.id", ondelete="SET NULL")
    priced_on: Mapped[date] = mapped_column(Date, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(UnitPrice, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(8))
    quantity: Mapped[Decimal | None] = mapped_column(Quantity)
    line_total: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str] = columna_moneda()
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="invoice")
    change_pct: Mapped[Decimal | None] = mapped_column(Percentage)
    # Precio de oferta: se excluye de la tendencia.
    is_promotion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    alerted_at: Mapped[datetime | None]

    product: Mapped[Product] = relationship(back_populates="prices", foreign_keys=[product_id])

    __table_args__ = (
        fk_tenencia("product_prices", "product_id", "products", ondelete="RESTRICT"),
        fk_tenencia("product_prices", "payee_id", "payees", ondelete="SET NULL"),
        # Una línea de factura genera como máximo una observación: revisar dos veces
        # la misma factura no debe duplicar la serie.
        Index(
            "uq_product_prices_invoice_line_id",
            "invoice_line_id",
            unique=True,
            postgresql_where=text("invoice_line_id IS NOT NULL"),
        ),
        # Evolución de precio de un producto (F-15): el índice del informe estrella.
        Index(
            "ix_product_prices_household_id_product_id_priced_on",
            "household_id",
            "product_id",
            text("priced_on DESC"),
            postgresql_include=["unit_price", "payee_id", "is_promotion"],
        ),
        Index(
            "ix_product_prices_household_id_payee_id_product_id_priced_on",
            "household_id",
            "payee_id",
            "product_id",
            text("priced_on DESC"),
            postgresql_include=["unit_price"],
        ),
        Index(
            "ix_product_prices_household_id_change_pct",
            "household_id",
            text("change_pct DESC"),
            postgresql_where=text("alerted_at IS NULL AND change_pct IS NOT NULL"),
        ),
        CheckConstraint("unit_price >= 0", name="unit_price"),
        CheckConstraint("source IN ('invoice', 'manual')", name="source"),
        CheckConstraint(
            "source <> 'invoice' OR invoice_line_id IS NOT NULL", name="invoice_source"
        ),
        CheckConstraint(CHECK_MONEDA, name="currency"),
    )
