"""Identidad: usuarios y tokens de refresco."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.mixins import GlobalBase, uuid_fk

TEMAS = ("dark", "light", "system")


class User(GlobalBase):
    """Credenciales y preferencias personales.

    Junto a `households` y `household_members` es el vértice del modelo: no está
    sujeta a multi-tenencia porque es quien la define.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    locale: Mapped[str] = mapped_column(String(10), nullable=False, server_default="es-ES")
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="Europe/Madrid")
    theme: Mapped[str] = mapped_column(String(10), nullable=False, server_default="dark")
    last_login_at: Mapped[datetime | None]
    failed_login_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    locked_until: Mapped[datetime | None]
    password_changed_at: Mapped[datetime | None]
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    onboarded_at: Mapped[datetime | None]

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # Índice funcional en lugar de CITEXT: no merece una extensión más por un
        # único caso de uso. El repositorio normaliza el email antes de consultar.
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        CheckConstraint(
            r"email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'",
            name="email_format",
        ),
        CheckConstraint("theme IN ('dark', 'light', 'system')", name="theme"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count"),
    )


class RefreshToken(GlobalBase):
    """Sesión revocable: convierte el `jti` del JWT en algo invalidable."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = uuid_fk("users.id", ondelete="CASCADE", nullable=False)
    jti: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None]
    # La cadena de rotación se poda sola cuando el barrendero borra los caducados;
    # perder el eslabón no invalida nada.
    replaced_by_id: Mapped[uuid.UUID | None] = uuid_fk("refresh_tokens.id", ondelete="SET NULL")
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)

    user: Mapped[User] = relationship(back_populates="refresh_tokens", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("jti", name="uq_refresh_tokens_jti"),
        Index("ix_refresh_tokens_user_id_expires_at", "user_id", text("expires_at DESC")),
        Index(
            "ix_refresh_tokens_expires_at",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )
