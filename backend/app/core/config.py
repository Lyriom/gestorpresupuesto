"""Configuración de la aplicación, cargada de variables de entorno."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes leídos de las variables de entorno o del fichero .env."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Aplicación ---------------------------------------------------------
    app_env: Literal["development", "production", "test"] = "development"
    app_name: str = "Gestor de Presupuesto"
    api_prefix: str = "/api/v1"

    # --- Seguridad ----------------------------------------------------------
    secret_key: str = Field(min_length=16)
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    cookie_secure: bool = False
    cookie_domain: str = ""
    allow_registration: bool = True

    # --- Base de datos ------------------------------------------------------
    database_url: str = "postgresql+asyncpg://presupuesto:presupuesto@localhost:5432/presupuesto"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- CORS ---------------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=list)

    # --- Subida de facturas -------------------------------------------------
    upload_dir: Path = Path("./uploads")
    max_upload_mb: int = 20
    max_pdf_pages: int = 40
    ocr_enabled: bool = True
    ocr_languages: str = "spa+eng"

    # --- Localización -------------------------------------------------------
    default_currency: str = "EUR"
    default_locale: str = "es-ES"
    default_timezone: str = "Europe/Madrid"

    # --- Frontend compilado -------------------------------------------------
    # En producción el monolito sirve los estáticos de Vue desde este directorio.
    static_dir: Path = Path("./static")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Acepta una lista o una cadena separada por comas."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        """Evita el error silencioso de configurar un driver síncrono."""
        if value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql+asyncpg://", 1)
        elif value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Devuelve los ajustes en caché; se lee el entorno una única vez."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
