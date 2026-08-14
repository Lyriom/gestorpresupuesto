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
    # Se recibe como cadena, no como `list[str]`: pydantic-settings intenta
    # interpretar cualquier campo de tipo lista como JSON antes de que llegue a
    # ningún validador, así que "http://localhost:5173" hacía que la aplicación
    # no arrancara y obligaba a escribir la variable en JSON.
    cors_origins_crudo: str = Field(default="", validation_alias="CORS_ORIGINS")

    # --- Proxy de confianza -------------------------------------------------
    # `X-Forwarded-For` lo puede escribir cualquiera, así que solo se cree si la
    # conexión llega de uno de estos pares (§2.4). Vacío significa «no hay proxy»:
    # se usa la IP de la conexión. `*` confía en quien sea y solo vale si el
    # contenedor no está expuesto directamente a internet.
    trusted_proxies_crudo: str = Field(default="", validation_alias="TRUSTED_PROXIES")

    # --- Subida de facturas -------------------------------------------------
    upload_dir: Path = Path("./uploads")
    max_upload_mb: int = 20
    max_pdf_pages: int = 40
    ocr_enabled: bool = True
    ocr_languages: str = "spa+eng"

    # --- Localización -------------------------------------------------------
    # Ecuador: dólar estadounidense, español de Ecuador y hora de Guayaquil. Los
    # separadores de `es-EC` son los mismos que los de España (miles con punto y
    # decimales con coma); lo que cambia es el símbolo, que va delante y pegado.
    # Los tres son de la instalación y se cambian por entorno; la moneda de cada
    # hogar además se puede cambiar luego en Ajustes.
    default_currency: str = "USD"
    default_locale: str = "es-EC"
    default_timezone: str = "America/Guayaquil"

    # --- Frontend compilado -------------------------------------------------
    # En producción el monolito sirve los estáticos de Vue desde este directorio.
    static_dir: Path = Path("./static")

    @property
    def cors_origins(self) -> list[str]:
        """Orígenes permitidos, escritos separados por comas en el entorno."""
        return [origen.strip() for origen in self.cors_origins_crudo.split(",") if origen.strip()]

    @property
    def trusted_proxies(self) -> list[str]:
        """Pares de los que se acepta `X-Forwarded-For`, separados por comas."""
        return [par.strip() for par in self.trusted_proxies_crudo.split(",") if par.strip()]

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
