"""Temáticas: el árbol jerárquico del hogar y su catálogo de plantillas."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Money
from app.models.hogar import CHECK_MODOS_ARRASTRE
from app.models.mixins import DomainBase, GlobalBase, fk_tenencia, uuid_fk

CLASES = ("expense", "income")
CHECK_CLASES = "kind IN ('expense', 'income')"

# Profundidad máxima. No es una limitación funcional (F-03 pide N niveles) sino un
# cortafuegos contra un bucle de programación.
PROFUNDIDAD_MAXIMA = 8


class Category(DomainBase):
    """Una temática del hogar. Jerárquica a N niveles (F-03).

    Estructura: lista de adyacencia (`parent_id`) como única fuente de verdad más
    tres columnas derivadas (`depth`, `path_ids`, `sort_key`) que son caché
    reconstruible con `refresh_category_paths()`.
    """

    __tablename__ = "categories"

    # Una temática con hijas no se borra: se archiva o se fusiona. RESTRICT hace
    # que un DELETE accidental falle en voz alta en vez de decapitar el subárbol.
    parent_id: Mapped[uuid.UUID | None] = uuid_fk("categories.id", ondelete="RESTRICT")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False, server_default="expense")
    color_slot: Mapped[int | None] = mapped_column(SmallInteger)
    color_hex: Mapped[str | None] = mapped_column(CHAR(7))
    icon: Mapped[str] = mapped_column(Text, nullable=False, server_default="circle")
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    depth: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    path_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    sort_key: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    default_rollover_mode: Mapped[str | None] = mapped_column(String(16))
    monthly_target: Mapped[Decimal | None] = mapped_column(Money)
    notes: Mapped[str | None] = mapped_column(Text)
    template_key: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None]
    # Lápida de fusión: el destino no puede desaparecer mientras haya lápidas
    # apuntándole, o el histórico dejaría de resolver.
    merged_into_id: Mapped[uuid.UUID | None] = uuid_fk("categories.id", ondelete="RESTRICT")

    parent: Mapped[Category | None] = relationship(
        back_populates="children", remote_side="Category.id", foreign_keys=[parent_id]
    )
    children: Mapped[list[Category]] = relationship(
        back_populates="parent", foreign_keys=[parent_id], viewonly=False
    )

    __table_args__ = (
        # PostgreSQL 16 permite NULLS NOT DISTINCT, imprescindible aquí: sin ello
        # dos raíces podrían llamarse igual, porque los NULL de parent_id se
        # considerarían distintos entre sí.
        Index(
            "uq_categories_household_id_parent_id_name",
            "household_id",
            "parent_id",
            text("lower(name)"),
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("archived_at IS NULL AND merged_into_id IS NULL"),
        ),
        # Subárbol en una sola pasada, sin CTE recursiva.
        Index("ix_categories_path_ids", "path_ids", postgresql_using="gin"),
        # Recorrido ordenado del árbol para el selector y la BudgetBar.
        Index(
            "ix_categories_household_id_sort_key",
            "household_id",
            "sort_key",
            postgresql_where=text("archived_at IS NULL AND merged_into_id IS NULL"),
        ),
        Index("ix_categories_parent_id", "parent_id"),
        # Clave compuesta que habilita las FK compuestas anti-fuga de tenencia.
        UniqueConstraint("household_id", "id"),
        # Ni la madre ni el destino de una fusión pueden estar en otro hogar: es la
        # fuga que la CTE recursiva del subárbol no podría detectar por sí sola.
        fk_tenencia("categories", "parent_id", "categories", ondelete="RESTRICT"),
        fk_tenencia("categories", "merged_into_id", "categories", ondelete="RESTRICT"),
        # Búsqueda difusa de temática al teclear.
        Index(
            "ix_categories_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        CheckConstraint(CHECK_CLASES, name="kind"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        CheckConstraint("color_slot IS NULL OR color_slot BETWEEN 1 AND 12", name="color_slot"),
        CheckConstraint("color_hex IS NULL OR color_hex ~ '^#[0-9A-Fa-f]{6}$'", name="color_hex"),
        CheckConstraint(f"depth BETWEEN 0 AND {PROFUNDIDAD_MAXIMA}", name="depth"),
        # Los dos CHECK siguientes son la red de seguridad del árbol: convierten en
        # imposible que la caché derivada quede incoherente o que un ciclo
        # sobreviva a una fusión mal ejecutada.
        CheckConstraint(
            "cardinality(path_ids) = depth + 1 AND path_ids[cardinality(path_ids)] = id",
            name="path_consistent",
        ),
        CheckConstraint(
            "parent_id IS NULL OR NOT (path_ids[1:cardinality(path_ids) - 1] @> ARRAY[id])",
            name="no_cycle",
        ),
        CheckConstraint(
            "merged_into_id IS NULL OR archived_at IS NOT NULL", name="merged_is_archived"
        ),
        CheckConstraint("merged_into_id IS NULL OR merged_into_id <> id", name="merge_not_self"),
        CheckConstraint(
            f"default_rollover_mode IS NULL OR default_rollover_mode {CHECK_MODOS_ARRASTRE}",
            name="default_rollover_mode",
        ),
    )


class CategoryTemplate(GlobalBase):
    """Árbol de temáticas por defecto en español de España, global y sin hogar.

    Se separa de `categories` porque una migración de datos no puede sembrar filas
    para usuarios que aún no existen. Con plantillas, el mismo árbol sirve para el
    onboarding (F-50), para «restaurar temáticas por defecto» y para proponer las
    temáticas nuevas de una versión posterior.
    """

    __tablename__ = "category_templates"

    template_key: Mapped[str] = mapped_column(Text, nullable=False)
    # El catálogo solo lo modifican las migraciones y las semillas: una
    # modificación que rompa el árbol debe fallar.
    parent_key: Mapped[str | None] = mapped_column(
        Text, ForeignKey("category_templates.template_key", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False, server_default="expense")
    icon: Mapped[str] = mapped_column(Text, nullable=False)
    color_slot: Mapped[int | None] = mapped_column(SmallInteger)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    depth: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))

    __table_args__ = (
        UniqueConstraint("template_key"),
        CheckConstraint(CHECK_CLASES, name="kind"),
        Index("ix_category_templates_parent_key", "parent_key"),
    )
