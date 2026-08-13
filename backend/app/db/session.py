"""Motor asíncrono de SQLAlchemy y dependencia de sesión para FastAPI."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _create_engine() -> AsyncEngine:
    # SQLite (en los tests) no admite los parámetros de pool de Postgres.
    if settings.database_url.startswith("sqlite"):
        return create_async_engine(settings.database_url, echo=settings.db_echo, future=True)
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        future=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,  # descarta conexiones muertas tras un reinicio de la BD
    )


engine: AsyncEngine = _create_engine()

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # permite leer los objetos después del commit
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia de FastAPI: una sesión por petición, con rollback si algo falla."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Cierra el pool de conexiones al apagar la aplicación."""
    await engine.dispose()
