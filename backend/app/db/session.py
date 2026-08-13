"""Motor asíncrono de SQLAlchemy, dependencia de sesión y alcance del RLS.

Aquí vive la mitad de cliente de la tercera capa de tenencia: fijar
`app.household_id` —la variable que leen las políticas— y cambiar al rol `app_rw`,
que es un rol sin `BYPASSRLS` y que no es dueño de ninguna tabla, así que las
políticas **sí** le aplican. La otra mitad la pone la migración
`9a1c4f27b8d5`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

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


#: Rol al que se cambia en cada petición. No es el rol con el que se conecta: es
#: `NOLOGIN` y sin contraseña, solo se llega a él con `SET ROLE` desde el propietario.
#: Debe coincidir con `ROL` de la migración `9a1c4f27b8d5`.
ROL_APLICACION = "app_rw"

#: Dónde se guarda el hogar activo dentro de `Session.info`.
#:
#: Hace falta porque `set_config(..., true)` y `SET LOCAL ROLE` son **transaccionales**:
#: al confirmar se pierden los dos. Hay cuarenta y tantos endpoints que hacen `commit()`
#: y siguen leyendo o escribiendo (`categorias.py`, `presupuestos.py`, `objetivos.py`,
#: `facturas.py`…), y las dos tareas de segundo plano confirman tres o cuatro veces.
#: El oyente de `after_begin` de más abajo vuelve a fijar el alcance en cada transacción
#: nueva de la misma sesión, así que ninguno de esos sitios necesita acordarse.
CLAVE_HOGAR = "app_household_id"

_SQL_FIJAR_HOGAR = text("SELECT set_config('app.household_id', :hogar, true)")
_SQL_FIJAR_ROL = f"SET LOCAL ROLE {ROL_APLICACION}"


def _es_postgres(conexion: Connection) -> bool:
    """Las pruebas de servicios puros corren sobre SQLite, que no tiene ni RLS ni roles."""
    return conexion.dialect.name == "postgresql"


def _aplicar_alcance(conexion: Connection, household_id: uuid.UUID) -> None:
    """Fija el hogar y cambia de rol en la transacción abierta de esa conexión.

    El orden importa poco —un parámetro personalizado lo puede fijar cualquier rol—,
    pero se deja el hogar primero para que nunca exista un instante en que la sesión
    sea `app_rw` sin saber a qué hogar pertenece.
    """
    if not _es_postgres(conexion):
        return
    conexion.execute(_SQL_FIJAR_HOGAR, {"hogar": str(household_id)})
    conexion.exec_driver_sql(_SQL_FIJAR_ROL)


def _restaurar_alcance(conexion: Connection) -> None:
    """Vuelve al rol propietario y deja el hogar sin fijar."""
    if not _es_postgres(conexion):
        return
    conexion.exec_driver_sql("RESET ROLE")
    conexion.execute(_SQL_FIJAR_HOGAR, {"hogar": ""})


@event.listens_for(Session, "after_begin")
def _reaplicar_alcance(
    sesion: Session, transaccion: SessionTransaction, conexion: Connection
) -> None:
    """Reinstala el alcance cada vez que la sesión abre una transacción.

    Es lo que hace inofensivo el patrón «`commit()` y sigo leyendo»: sin esto la
    lectura de después iría sin `app.household_id` y devolvería cero filas, que es
    mucho peor que un error porque no se nota. Está registrado en la clase `Session`,
    no en la fábrica, para que valga también para las sesiones que abren por su cuenta
    las tareas de segundo plano de facturas e importaciones.
    """
    hogar = sesion.info.get(CLAVE_HOGAR)
    if hogar is not None:
        _aplicar_alcance(conexion, hogar)


async def fijar_alcance(sesion: AsyncSession, household_id: uuid.UUID) -> None:
    """Ata la sesión a un hogar: `app.household_id` más `SET LOCAL ROLE app_rw`.

    Se llama una vez por petición desde `app.api.deps.alcance_hogar`, y al principio
    de cada tarea de segundo plano. A partir de ahí el oyente de `after_begin` se
    encarga de que siga en pie después de cada `commit()`.
    """
    sesion.info[CLAVE_HOGAR] = household_id
    conexion = await sesion.connection()
    await conexion.run_sync(_aplicar_alcance, household_id)


async def limpiar_alcance(sesion: AsyncSession) -> None:
    """Deshace lo anterior al terminar la petición.

    En producción sería innecesario: `SET LOCAL` muere con la transacción y la conexión
    vuelve al pool limpia. Se hace igualmente porque las pruebas de API comparten una
    única transacción entre la aplicación y el propio test, y ahí `SET LOCAL ROLE`
    sobrevive a los `commit()` (que son liberaciones de savepoint); sin esto, el test
    seguiría sembrando datos como `app_rw` y atado al último hogar que vio la API.
    """
    if sesion.info.pop(CLAVE_HOGAR, None) is None:
        return
    try:
        conexion = await sesion.connection()
        await conexion.run_sync(_restaurar_alcance)
    except Exception:  # noqa: BLE001 - si la transacción ya está abortada, no hay nada que restaurar
        pass


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
