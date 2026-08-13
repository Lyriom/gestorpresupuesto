"""Pruebas de la carga de configuración desde el entorno.

Son la red de seguridad del arranque: un fallo aquí no rompe una pantalla, deja
la aplicación sin levantar en el servidor.
"""

import pytest

from app.core.config import Settings

BASE = {"SECRET_KEY": "clave-de-pruebas-suficientemente-larga-1234"}


def ajustes(**entorno: str) -> Settings:
    return Settings(_env_file=None, **{**BASE, **entorno})  # type: ignore[arg-type]


class TestCorsOrigins:
    def test_un_solo_origen_sin_comillas_ni_json(self):
        # Este era el caso que impedía arrancar: pydantic-settings intentaba
        # interpretar el valor como JSON y lanzaba SettingsError.
        s = ajustes(CORS_ORIGINS="http://localhost:5173")
        assert s.cors_origins == ["http://localhost:5173"]

    def test_varios_origenes_separados_por_comas(self):
        s = ajustes(CORS_ORIGINS="http://localhost:5173, https://presupuesto.example")
        assert s.cors_origins == ["http://localhost:5173", "https://presupuesto.example"]

    def test_vacio_no_habilita_cors(self):
        assert ajustes(CORS_ORIGINS="").cors_origins == []

    def test_sin_definir(self):
        assert ajustes().cors_origins == []

    def test_ignora_las_comas_sueltas(self):
        assert ajustes(CORS_ORIGINS="a.com,,b.com,").cors_origins == ["a.com", "b.com"]


class TestDatabaseUrl:
    def test_convierte_el_esquema_de_postgres_al_driver_asincrono(self):
        # Los proveedores de hosting dan la URL en formato postgres://, que con
        # SQLAlchemy asíncrono no funciona.
        s = ajustes(DATABASE_URL="postgres://u:p@host:5432/db")
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_convierte_postgresql_a_asyncpg(self):
        s = ajustes(DATABASE_URL="postgresql://u:p@host:5432/db")
        assert s.database_url == "postgresql+asyncpg://u:p@host:5432/db"

    def test_respeta_una_url_que_ya_trae_driver(self):
        url = "postgresql+asyncpg://u:p@host:5432/db"
        assert ajustes(DATABASE_URL=url).database_url == url

    def test_respeta_sqlite_de_los_tests(self):
        url = "sqlite+aiosqlite:///:memory:"
        assert ajustes(DATABASE_URL=url).database_url == url


class TestSecretKey:
    def test_rechaza_una_clave_corta(self):
        with pytest.raises(ValueError, match="secret_key|at least"):
            Settings(_env_file=None, SECRET_KEY="corta")  # type: ignore[arg-type]


class TestDerivados:
    def test_limite_de_subida_en_bytes(self):
        assert ajustes(MAX_UPLOAD_MB="20").max_upload_bytes == 20 * 1024 * 1024

    def test_produccion(self):
        assert ajustes(APP_ENV="production").is_production
        assert not ajustes(APP_ENV="development").is_production
