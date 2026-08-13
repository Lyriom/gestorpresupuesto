"""Reglas de auto-categorización: «si el concepto contiene X → temática Y»."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mixins import DomainBase, fk_tenencia, uuid_fk

AMBITOS = ("transaction", "invoice_line", "both")


class CategorizationRule(DomainBase):
    """Regla de categorización con editor en texto simple (F-27, F-59).

    Doble representación: `text_form` es lo que el usuario escribe y ve;
    `conditions` es lo que se ejecuta. El compilador va **siempre** de `text_form` a
    `conditions`, nunca al revés, y ambos se escriben en la misma transacción; así
    la regla ejecutada no puede diferir de la mostrada.
    """

    __tablename__ = "categorization_rules"

    name: Mapped[str | None] = mapped_column(Text)
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False)
    text_form: Mapped[str] = mapped_column(Text, nullable=False)
    match_mode: Mapped[str] = mapped_column(String(3), nullable=False, server_default="all")
    # La fusión de temáticas las reasigna, no las rompe.
    set_category_id: Mapped[uuid.UUID | None] = uuid_fk("categories.id", ondelete="RESTRICT")
    set_payee_id: Mapped[uuid.UUID | None] = uuid_fk("payees.id", ondelete="SET NULL")
    # Array sin FK: única concesión de integridad referencial del modelo. Una
    # etiqueta borrada degrada la regla, no los datos; lo limpia el barrendero.
    add_tag_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    set_notes: Mapped[str | None] = mapped_column(Text)
    set_excluded_from_reports: Mapped[bool | None] = mapped_column(Boolean)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("100"))
    stop_processing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    applies_to: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="transaction"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Sirve para detectar reglas muertas.
    last_matched_at: Mapped[datetime | None]

    __table_args__ = (
        fk_tenencia("categorization_rules", "set_category_id", "categories", ondelete="RESTRICT"),
        fk_tenencia("categorization_rules", "set_payee_id", "payees", ondelete="SET NULL"),
        Index(
            "uq_categorization_rules_household_id_text_form",
            "household_id",
            text("lower(text_form)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
        # Carga de reglas en orden de evaluación: la consulta de cada alta.
        Index(
            "ix_categorization_rules_household_id_priority",
            "household_id",
            "priority",
            "id",
            postgresql_where=text("is_active"),
        ),
        Index(
            "ix_categorization_rules_household_id_set_category_id",
            "household_id",
            "set_category_id",
            postgresql_where=text("set_category_id IS NOT NULL"),
        ),
        Index(
            "ix_categorization_rules_conditions",
            "conditions",
            postgresql_using="gin",
            postgresql_ops={"conditions": "jsonb_path_ops"},
        ),
        CheckConstraint("match_mode IN ('all', 'any')", name="match_mode"),
        CheckConstraint("applies_to IN ('transaction', 'invoice_line', 'both')", name="applies_to"),
        CheckConstraint(
            "jsonb_typeof(conditions) = 'array' AND jsonb_array_length(conditions) > 0",
            name="conditions_array",
        ),
        # Una regla que no hace nada no debe poder guardarse.
        CheckConstraint(
            "num_nonnulls(set_category_id, set_payee_id, add_tag_ids, set_notes, "
            "set_excluded_from_reports) >= 1",
            name="has_action",
        ),
        CheckConstraint("priority BETWEEN 0 AND 32000", name="priority"),
    )
