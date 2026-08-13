"""Pruebas de la tercera capa de tenencia: que el row level security aísla de verdad.

Las políticas existían desde `3f6b7dd10b1e`, pero estaban **inertes**: se aplicaban
sin `FORCE` y la aplicación se conectaba con el rol propietario de las tablas, que en
PostgreSQL está exento de sus propias políticas. Un `SELECT` sin `WHERE` devolvía los
datos de todos los hogares. La revisión `9a1c4f27b8d5` lo cierra con un rol `app_rw`
al que la aplicación se cambia con `SET LOCAL ROLE`.

Estas pruebas van contra PostgreSQL de verdad (`docker compose up -d db`) y **con las
migraciones aplicadas**: no hay forma de probar RLS sin RLS. Cada prueba trabaja dentro
de una transacción que se descarta al terminar, salvo la que necesita un `commit()`
auténtico, que limpia lo suyo borrando los dos hogares (todo cuelga de ellos con
`ON DELETE CASCADE`).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.db.session import ROL_APLICACION, fijar_alcance, limpiar_alcance

#: La misma base que usan las pruebas de API: la de desarrollo, ya migrada.
URL_PRUEBAS = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://presupuesto:presupuesto@localhost:5432/presupuesto",
)

MOTIVO_SIN_POSTGRES = (
    "Hace falta PostgreSQL en marcha: `docker compose up -d db` en la raíz del repositorio."
)

#: Las cuatro tablas de la prueba de fuego: movimientos, temáticas, facturas y
#: presupuestos. Son las que pide la auditoría y las que más duele filtrar.
TABLAS_DE_FUEGO = ("transactions", "categories", "invoices", "budget_periods")


class Hogares(NamedTuple):
    """Dos hogares vecinos, cada uno con una fila en cada tabla de la prueba de fuego."""

    a: uuid.UUID
    b: uuid.UUID
    filas_a: dict[str, uuid.UUID]
    filas_b: dict[str, uuid.UUID]


# --------------------------------------------------------------------------- #
# Utillaje
# --------------------------------------------------------------------------- #


async def _sembrar_hogar(ejecutor: AsyncConnection | AsyncSession, etiqueta: str) -> tuple:
    """Un hogar con una cuenta, una temática, un movimiento, una factura y un periodo.

    Se escribe con SQL a pelo y no con el ORM porque lo que se está comprobando es
    exactamente lo que la base de datos deja pasar, sin la ayuda de ninguna capa.
    """
    hogar = uuid.uuid4()
    cuenta = uuid.uuid4()
    tematica = uuid.uuid4()
    movimiento = uuid.uuid4()
    factura = uuid.uuid4()
    periodo = uuid.uuid4()

    await ejecutor.execute(
        text("INSERT INTO households (id, name) VALUES (CAST(:id AS uuid), :nombre)"),
        {"id": str(hogar), "nombre": f"Hogar {etiqueta}"},
    )
    await ejecutor.execute(
        text(
            "INSERT INTO accounts (id, household_id, name, type, account_class) "
            "VALUES (CAST(:id AS uuid), CAST(:hogar AS uuid), :nombre, 'checking', 'asset')"
        ),
        {"id": str(cuenta), "hogar": str(hogar), "nombre": f"Cuenta {etiqueta}"},
    )
    # `ck_categories_path_consistent` exige que `path_ids` acabe en el propio id y que
    # su longitud sea `depth + 1`.
    await ejecutor.execute(
        text(
            "INSERT INTO categories (id, household_id, name, depth, path_ids, sort_key) "
            "VALUES (CAST(:id AS uuid), CAST(:hogar AS uuid), :nombre, 0, "
            "        ARRAY[CAST(:id AS uuid)], '0001')"
        ),
        {"id": str(tematica), "hogar": str(hogar), "nombre": f"Alimentación {etiqueta}"},
    )
    await ejecutor.execute(
        text(
            "INSERT INTO transactions "
            "  (id, household_id, account_id, category_id, kind, booked_on, amount, notes) "
            "VALUES (CAST(:id AS uuid), CAST(:hogar AS uuid), CAST(:cuenta AS uuid), "
            "        CAST(:tematica AS uuid), 'expense', DATE '2026-08-01', -25.40, :nota)"
        ),
        {
            "id": str(movimiento),
            "hogar": str(hogar),
            "cuenta": str(cuenta),
            "tematica": str(tematica),
            "nota": f"nota original {etiqueta}",
        },
    )
    await ejecutor.execute(
        text(
            "INSERT INTO invoices "
            "  (id, household_id, file_name, storage_key, byte_size, content_sha256) "
            "VALUES (CAST(:id AS uuid), CAST(:hogar AS uuid), :fichero, :clave, 2048, :huella)"
        ),
        {
            "id": str(factura),
            "hogar": str(hogar),
            "fichero": f"luz-{etiqueta}.pdf",
            "clave": f"{hogar}/2026/{factura}.pdf",
            "huella": uuid.uuid4().hex + uuid.uuid4().hex,  # 64 dígitos hex minúsculos
        },
    )
    await ejecutor.execute(
        text(
            "INSERT INTO budget_periods (id, household_id, period_month) "
            "VALUES (CAST(:id AS uuid), CAST(:hogar AS uuid), DATE '2026-08-01')"
        ),
        {"id": str(periodo), "hogar": str(hogar)},
    )

    filas = {
        "transactions": movimiento,
        "categories": tematica,
        "invoices": factura,
        "budget_periods": periodo,
    }
    return hogar, filas


async def _sembrar(ejecutor: AsyncConnection | AsyncSession) -> Hogares:
    hogar_a, filas_a = await _sembrar_hogar(ejecutor, "A")
    hogar_b, filas_b = await _sembrar_hogar(ejecutor, "B")
    return Hogares(a=hogar_a, b=hogar_b, filas_a=filas_a, filas_b=filas_b)


async def _contar(ejecutor: AsyncConnection | AsyncSession, consulta: str) -> int:
    return int((await ejecutor.execute(text(consulta))).scalar_one())


@asynccontextmanager
async def _como_app_rw(
    conexion: AsyncConnection, hogar: uuid.UUID | None
) -> AsyncIterator[AsyncConnection]:
    """Reproduce a mano lo que hace `fijar_alcance` en cada petición.

    Con `hogar=None` se fija la cadena vacía, que es el estado real de una conexión del
    pool que ya ha servido una petición: `current_setting('app.household_id', true)` no
    vuelve a `NULL` al acabar la transacción, se queda en `''`.
    """
    await conexion.execute(
        text("SELECT set_config('app.household_id', :valor, true)"),
        {"valor": str(hogar) if hogar else ""},
    )
    await conexion.exec_driver_sql(f"SET LOCAL ROLE {ROL_APLICACION}")
    try:
        yield conexion
    finally:
        await conexion.exec_driver_sql("RESET ROLE")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def conexion() -> AsyncIterator[AsyncConnection]:
    """Conexión con una transacción que se descarta: la siembra no llega a la base."""
    motor = create_async_engine(URL_PRUEBAS, poolclass=NullPool)
    try:
        async with motor.connect() as conexion:
            transaccion = await conexion.begin()
            existe = await conexion.execute(
                text("SELECT count(*) FROM pg_roles WHERE rolname = :rol"),
                {"rol": ROL_APLICACION},
            )
            assert existe.scalar_one() == 1, (
                f"No existe el rol {ROL_APLICACION}. Aplica las migraciones: "
                "`./.venv/bin/alembic upgrade head`."
            )
            try:
                yield conexion
            finally:
                await transaccion.rollback()
    except OSError as error:  # pragma: no cover - depende del entorno
        pytest.skip(f"{MOTIVO_SIN_POSTGRES} ({error})")
    finally:
        await motor.dispose()


@pytest_asyncio.fixture
async def motor_real() -> AsyncIterator[AsyncEngine]:
    """Motor sin transacción envolvente, para la prueba que necesita `commit()` de verdad."""
    motor = create_async_engine(URL_PRUEBAS, poolclass=NullPool)
    try:
        yield motor
    finally:
        await motor.dispose()


# --------------------------------------------------------------------------- #
# La prueba de fuego
# --------------------------------------------------------------------------- #


async def test_select_sin_where_no_devuelve_ni_una_fila_del_hogar_vecino(
    conexion: AsyncConnection,
) -> None:
    """El agujero que había: un `SELECT` sin filtro devolvía los dos hogares.

    Se mide antes y después en la misma transacción y con los mismos datos, así que la
    diferencia no puede venir de otra parte.
    """
    hogares = await _sembrar(conexion)

    # Antes: como propietario de las tablas se ve todo, `FORCE` incluido (en desarrollo
    # el usuario único es además superusuario, y un superusuario nunca pasa por RLS).
    ajenas_antes = {
        tabla: await _contar(
            conexion, f"SELECT count(*) FROM {tabla} WHERE household_id <> '{hogares.a}'"
        )
        for tabla in TABLAS_DE_FUEGO
    }
    assert all(n >= 1 for n in ajenas_antes.values()), (
        f"La siembra no ha dejado filas del hogar vecino: {ajenas_antes}"
    )

    # Después: con `SET LOCAL ROLE app_rw` y el hogar A fijado.
    async with _como_app_rw(conexion, hogares.a):
        ajenas_despues = {
            tabla: await _contar(
                conexion, f"SELECT count(*) FROM {tabla} WHERE household_id <> '{hogares.a}'"
            )
            for tabla in TABLAS_DE_FUEGO
        }
        # Sin ninguna cláusula WHERE, que es la prueba que pide la auditoría.
        a_pelo = {
            tabla: await _contar(conexion, f"SELECT count(*) FROM {tabla}")
            for tabla in TABLAS_DE_FUEGO
        }
        propias = {
            tabla: await _contar(
                conexion, f"SELECT count(*) FROM {tabla} WHERE household_id = '{hogares.a}'"
            )
            for tabla in TABLAS_DE_FUEGO
        }
        # Y la fila concreta del vecino, buscada por su clave primaria.
        por_id = {
            tabla: await _contar(
                conexion, f"SELECT count(*) FROM {tabla} WHERE id = '{hogares.filas_b[tabla]}'"
            )
            for tabla in TABLAS_DE_FUEGO
        }

    assert ajenas_despues == dict.fromkeys(TABLAS_DE_FUEGO, 0)
    assert por_id == dict.fromkeys(TABLAS_DE_FUEGO, 0)
    # El aislamiento no puede consistir en no ver nada: lo propio sigue visible.
    assert a_pelo == propias
    assert all(n >= 1 for n in propias.values())


async def test_la_vista_de_movimientos_tambien_filtra(conexion: AsyncConnection) -> None:
    """`security_invoker`: sin él, la vista consultaría con las políticas de su dueño.

    `vw_movement_lines` es de donde sale todo el gasto de presupuestos, informes,
    temáticas y comercios. Una vista normal lee sus tablas con los permisos y las
    políticas de **su propietario**, que aquí es el dueño de las tablas: el `SET ROLE`
    de la aplicación no habría servido de nada al otro lado de la vista.
    """
    hogares = await _sembrar(conexion)

    async with _como_app_rw(conexion, hogares.a):
        ajenas = await _contar(
            conexion,
            f"SELECT count(*) FROM vw_movement_lines WHERE household_id <> '{hogares.a}'",
        )
        propias = await _contar(conexion, "SELECT count(*) FROM vw_movement_lines")

    assert ajenas == 0
    assert propias >= 1


# --------------------------------------------------------------------------- #
# Escrituras sin filtro
# --------------------------------------------------------------------------- #


async def test_update_sin_filtro_no_alcanza_al_hogar_vecino(conexion: AsyncConnection) -> None:
    """`WITH CHECK` y `USING`: un UPDATE a toda la tabla solo toca lo propio."""
    hogares = await _sembrar(conexion)

    async with _como_app_rw(conexion, hogares.a):
        resultado = await conexion.execute(text("UPDATE transactions SET notes = 'tocado'"))
        tocadas = resultado.rowcount
        resultado = await conexion.execute(text("UPDATE categories SET name = 'renombrada'"))
        renombradas = resultado.rowcount

    # De vuelta como propietario: la fila del vecino sigue como estaba.
    nota_vecina = (
        await conexion.execute(
            text("SELECT notes FROM transactions WHERE id = CAST(:id AS uuid)"),
            {"id": str(hogares.filas_b["transactions"])},
        )
    ).scalar_one()
    nombre_vecino = (
        await conexion.execute(
            text("SELECT name FROM categories WHERE id = CAST(:id AS uuid)"),
            {"id": str(hogares.filas_b["categories"])},
        )
    ).scalar_one()

    assert nota_vecina == "nota original B"
    assert nombre_vecino == "Alimentación B"
    assert tocadas >= 1
    assert renombradas >= 1
    # Y lo propio sí se ha escrito: el UPDATE no ha fallado en silencio.
    assert (
        await conexion.execute(
            text("SELECT notes FROM transactions WHERE id = CAST(:id AS uuid)"),
            {"id": str(hogares.filas_a["transactions"])},
        )
    ).scalar_one() == "tocado"


async def test_delete_sin_filtro_no_alcanza_al_hogar_vecino(conexion: AsyncConnection) -> None:
    """Lo mismo con el borrado, que es el que no se puede deshacer."""
    hogares = await _sembrar(conexion)

    async with _como_app_rw(conexion, hogares.a):
        await conexion.execute(text("DELETE FROM invoices"))
        await conexion.execute(text("DELETE FROM transactions"))
        assert await _contar(conexion, "SELECT count(*) FROM transactions") == 0

    sobrevive_movimiento = await _contar(
        conexion,
        f"SELECT count(*) FROM transactions WHERE id = '{hogares.filas_b['transactions']}'",
    )
    sobrevive_factura = await _contar(
        conexion, f"SELECT count(*) FROM invoices WHERE id = '{hogares.filas_b['invoices']}'"
    )
    borrada_propia = await _contar(
        conexion,
        f"SELECT count(*) FROM transactions WHERE id = '{hogares.filas_a['transactions']}'",
    )

    assert sobrevive_movimiento == 1
    assert sobrevive_factura == 1
    assert borrada_propia == 0


async def test_insert_de_un_hogar_ajeno_lo_rechaza_la_politica(
    conexion: AsyncConnection,
) -> None:
    """`WITH CHECK`: con solo `USING`, escribir en el hogar del vecino pasaría."""
    hogares = await _sembrar(conexion)

    async with _como_app_rw(conexion, hogares.a):
        # En un savepoint: el rechazo aborta la transacción, y sin acotarlo no se podría
        # ni volver al rol propietario después.
        with pytest.raises(DBAPIError, match="row-level security"):
            async with conexion.begin_nested():
                await conexion.execute(
                    text(
                        "INSERT INTO budget_periods (id, household_id, period_month) "
                        "VALUES (gen_random_uuid(), CAST(:hogar AS uuid), DATE '2026-09-01')"
                    ),
                    {"hogar": str(hogares.b)},
                )


# --------------------------------------------------------------------------- #
# Sin hogar fijado
# --------------------------------------------------------------------------- #


async def test_sin_hogar_fijado_no_se_ve_nada_en_vez_de_verse_todo(
    conexion: AsyncConnection,
) -> None:
    """El caso que hay que acertar: si falta el alcance, cero filas.

    Y además tiene que ser **cero filas y no un error**: al acabar una transacción que
    fijó la variable con `set_config(..., true)`, `current_setting` no vuelve a `NULL`,
    se queda en la cadena vacía, y `''::uuid` es `invalid input syntax for type uuid`.
    Con el pool de conexiones eso reventaría en la segunda petición de cada conexión.
    Por eso la política compara contra `nullif(current_setting(...), '')`.
    """
    await _sembrar(conexion)

    async with _como_app_rw(conexion, None):
        for tabla in TABLAS_DE_FUEGO:
            assert await _contar(conexion, f"SELECT count(*) FROM {tabla}") == 0, tabla
        assert await _contar(conexion, "SELECT count(*) FROM vw_movement_lines") == 0


async def test_el_rol_de_la_aplicacion_no_puede_saltarse_el_rls(
    conexion: AsyncConnection,
) -> None:
    """`app_rw` es `NOLOGIN`, no es superusuario y no tiene `BYPASSRLS`.

    Si alguien se lo concediera, todo lo de arriba seguiría pasando en verde mientras el
    aislamiento habría desaparecido.
    """
    fila = (
        await conexion.execute(
            text("SELECT rolcanlogin, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :rol"),
            {"rol": ROL_APLICACION},
        )
    ).one()

    assert fila.rolcanlogin is False
    assert fila.rolsuper is False
    assert fila.rolbypassrls is False


async def test_las_tablas_con_politica_llevan_force(conexion: AsyncConnection) -> None:
    """Cinturón además del tirante: con `FORCE` tampoco se libra el propietario."""
    sin_force = (
        (
            await conexion.execute(
                text(
                    "SELECT c.relname FROM pg_class c "
                    "  JOIN pg_namespace n ON n.oid = c.relnamespace "
                    " WHERE n.nspname = 'public' AND c.relrowsecurity "
                    "   AND NOT c.relforcerowsecurity"
                )
            )
        )
        .scalars()
        .all()
    )

    assert list(sin_force) == []


# --------------------------------------------------------------------------- #
# El alcance sobrevive a un `commit()`
# --------------------------------------------------------------------------- #


async def test_el_alcance_sobrevive_a_un_commit_de_verdad(motor_real: AsyncEngine) -> None:
    """El otro medio agujero: `set_config(..., true)` y `SET LOCAL` mueren al confirmar.

    Cuarenta y tantos endpoints confirman y siguen leyendo (`categorias.py:456`,
    `objetivos.py:395`, `presupuestos.py:671`, `facturas.py:1483`…) y las dos tareas de
    segundo plano confirman tres o cuatro veces. Sin reinstalar el alcance, esas lecturas
    devolverían **cero filas sin ningún error**, que es la peor forma de romperse.

    Esta prueba no puede vivir dentro de una transacción que se descarta: ahí un
    `commit()` es una liberación de savepoint y no deshace el `SET LOCAL`. Así que
    confirma de verdad y limpia borrando los dos hogares, de los que cuelga todo con
    `ON DELETE CASCADE`.
    """
    fabrica = async_sessionmaker(motor_real, expire_on_commit=False, autoflush=False)
    hogares: Hogares | None = None
    try:
        async with fabrica() as sesion:
            hogares = await _sembrar(sesion)
            await sesion.commit()

            await fijar_alcance(sesion, hogares.a)
            antes = await _contar(sesion, "SELECT count(*) FROM transactions")
            rol_antes = (await sesion.execute(text("SELECT current_user"))).scalar_one()

            # El `commit()` se lleva por delante la variable y el rol. Lo que sigue es
            # exactamente el patrón de `categorias.py:456`: confirmar y volver a leer.
            await sesion.commit()

            despues = await _contar(sesion, "SELECT count(*) FROM transactions")
            rol_despues = (await sesion.execute(text("SELECT current_user"))).scalar_one()
            ajenas = await _contar(
                sesion,
                f"SELECT count(*) FROM transactions WHERE household_id = '{hogares.b}'",
            )

            # Y una escritura después del commit, que es lo que haría un `refresh`.
            await sesion.execute(text("UPDATE transactions SET notes = 'tras el commit'"))
            await sesion.commit()

            await limpiar_alcance(sesion)
            rol_final = (await sesion.execute(text("SELECT current_user"))).scalar_one()
            nota_vecina = (
                await sesion.execute(
                    text("SELECT notes FROM transactions WHERE id = CAST(:id AS uuid)"),
                    {"id": str(hogares.filas_b["transactions"])},
                )
            ).scalar_one()

        assert rol_antes == ROL_APLICACION
        assert rol_despues == ROL_APLICACION, "el rol no se ha reinstalado tras el commit"
        assert antes == despues == 1, "la lectura de después del commit ha perdido el alcance"
        assert ajenas == 0
        assert rol_final != ROL_APLICACION, "`limpiar_alcance` no ha devuelto el rol propietario"
        assert nota_vecina == "nota original B", "el UPDATE ha cruzado al hogar vecino"
    finally:
        if hogares is not None:
            async with fabrica() as limpieza:
                await limpieza.execute(
                    text(
                        "DELETE FROM households  WHERE id IN (CAST(:a AS uuid), CAST(:b AS uuid))"
                    ),
                    {"a": str(hogares.a), "b": str(hogares.b)},
                )
                await limpieza.commit()
