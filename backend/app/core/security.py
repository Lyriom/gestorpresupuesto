"""Hashing de contraseñas y emisión/verificación de tokens JWT."""

from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"
TokenType = Literal["access", "refresh"]

# bcrypt trunca en 72 bytes; recortamos antes de hashear para que una contraseña
# larguísima no falle con un error opaco de la librería.
_BCRYPT_MAX_BYTES = 72


def _truncate(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """Devuelve el hash bcrypt de una contraseña en claro."""
    return bcrypt.hashpw(_truncate(password), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Comprueba una contraseña contra su hash sin lanzar excepciones."""
    try:
        return bcrypt.checkpw(_truncate(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _create_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(subject: str, **extra_claims: Any) -> str:
    return _create_token(
        subject,
        "access",
        timedelta(minutes=settings.access_token_minutes),
        extra_claims or None,
    )


def create_refresh_token(subject: str, **extra_claims: Any) -> str:
    return _create_token(
        subject,
        "refresh",
        timedelta(days=settings.refresh_token_days),
        extra_claims or None,
    )


class TokenError(Exception):
    """El token es inválido, ha caducado o no es del tipo esperado."""


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Valida la firma, la caducidad y el tipo del token, y devuelve sus claims."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("El token ha caducado") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token inválido") from exc

    if payload.get("typ") != expected_type:
        raise TokenError("Tipo de token incorrecto")
    if not payload.get("sub"):
        raise TokenError("Token sin sujeto")
    return payload


# --- Protección CSRF para las cookies de sesión ----------------------------
# Patrón "double submit": el token va en una cookie legible por JS y también en
# la cabecera X-CSRF-Token; el servidor comprueba que coinciden.

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_tokens_match(cookie_token: str | None, header_token: str | None) -> bool:
    if not cookie_token or not header_token:
        return False
    return hmac.compare_digest(cookie_token, header_token)
