"""Registro de auditoría de los cambios sensibles."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mixins import GlobalBase, uuid_fk


class AuditLog(GlobalBase):
    """Cambios sensibles: autenticación, miembros, fusiones, archivado, borrados.

    **No** es un historial de todos los `UPDATE`: un gestor doméstico no necesita
    una base de datos temporal, y los dos casos que de verdad requieren
    reversibilidad (fusión e importación) tienen su propio diario detallado.

    Es una tabla **solo de inserción**: el rol de la aplicación tiene `INSERT` y
    `SELECT`, nunca `UPDATE` ni `DELETE`.
    """

    __tablename__ = "audit_log"

    # `NULL` en los eventos de autenticación previos a tener un hogar. Lleva FK con
    # CASCADE porque borrar el hogar es «borra mis datos» y la auditoría de un hogar
    # inexistente no tiene a quién servir.
    household_id: Mapped[uuid.UUID | None] = uuid_fk(
        "households.id", ondelete="CASCADE", index=True
    )
    # Sin FK a `users` a propósito: un registro de auditoría que se puede modificar
    # borrando al actor no es un registro de auditoría. `NULL` = trabajo programado.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_table: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Nombre congelado, legible sin resolver la FK.
    entity_label: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_audit_log_household_id_occurred_at", "household_id", text("occurred_at DESC")),
        Index(
            "ix_audit_log_entity_table_entity_id",
            "entity_table",
            "entity_id",
            postgresql_where=text("entity_id IS NOT NULL"),
        ),
        Index(
            "ix_audit_log_actor_user_id_occurred_at",
            "actor_user_id",
            text("occurred_at DESC"),
        ),
        Index("ix_audit_log_action_occurred_at", "action", text("occurred_at DESC")),
        CheckConstraint(r"action ~ '^[a-z_]+\.[a-z_]+$'", name="action_format"),
    )
