"""Pruebas de la API de transacciones, splits, transferencias y lotes.

Contra PostgreSQL de verdad y sobre el esquema que construye Alembic: lo que se
comprueba aquí son reglas que viven a medias en el código y en la base —el
invariante de splits, las claves ajenas compuestas de tenencia, la vista de
movimientos— y ninguna de ellas existe en SQLite.

Este módulo guarda además los útiles compartidos por las otras dos suites de
API (`test_api_presupuestos.py` y `test_api_recurrentes.py`), que importan de
aquí las fixtures para no tener tres copias del montaje.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.v1 import (
    comercios,
    etiquetas,
    objetivos,
    presupuestos,
    recurrentes,
    reglas,
    transacciones,
    transferencias,
)
from app.core.config import settings
from app.core.errors import registrar_manejadores
from app.core.security import CSRF_COOKIE_NAME, create_access_token, hash_password
from app.db.session import get_session
from app.models.categoria import Category
from app.models.cuenta import Account
from app.models.hogar import Household, HouseholdMember
from app.models.usuario import User

BACKEND = Path(__file__).resolve().parents[1]

# Base propia, distinta de la de `test_modelos.py`: esa se borra y se recrea al
# empezar su sesión y arrastraría por delante las conexiones de estas pruebas.
BASE_PRUEBAS = os.environ.get("TEST_API_DB_NAME", "presupuesto_test_api")
URL_ADMIN = os.environ.get(
    "TEST_ADMIN_URL", "postgresql+asyncpg://presupuesto:presupuesto@localhost:5432/postgres"
)
URL_PRUEBAS = URL_ADMIN.rsplit("/", 1)[0] + f"/{BASE_PRUEBAS}"

# Estas pruebas ejecutan DROP DATABASE. Si alguien apunta la variable de entorno
# a la base real, se lleva por delante los datos del usuario: más vale abortar
# aquí que descubrirlo después.
if not BASE_PRUEBAS.endswith(("_test", "_test_api")):
    raise RuntimeError(
        f"TEST_API_DB_NAME='{BASE_PRUEBAS}' no parece una base de pruebas. "
        "Tiene que acabar en '_test' o '_test_api': estas pruebas la borran y la recrean."
    )

MOTIVO_SIN_POSTGRES = (
    "Hace falta PostgreSQL en marcha: `docker compose up -d db` en la raíz del repositorio."
)

RUTA = settings.api_prefix
CSRF = "token-csrf-de-pruebas"
HOY = date.today()
PERIODO = f"{HOY.year:04d}-{HOY.month:02d}"

MODULOS = (
    transacciones,
    transferencias,
    presupuestos,
    recurrentes,
    comercios,
    etiquetas,
    reglas,
    objetivos,
)


# --------------------------------------------------------------------------- #
# Montaje
# --------------------------------------------------------------------------- #


async def _crear_base_vacia() -> None:
    motor = create_async_engine(URL_ADMIN, isolation_level="AUTOCOMMIT")
    try:
        async with motor.connect() as conexion:
            await conexion.execute(text(f'DROP DATABASE IF EXISTS "{BASE_PRUEBAS}" WITH (FORCE)'))
            await conexion.execute(text(f'CREATE DATABASE "{BASE_PRUEBAS}"'))
    finally:
        await motor.dispose()


# Las tres suites de API importan esta fixture, así que pytest la registra tres
# veces (una por módulo) y la ejecutaría tres veces aunque sea de sesión. Este
# candado hace que la base se cree y se migre **una sola vez**: recrearla a mitad
# de la sesión mataría las conexiones de las pruebas ya en marcha.
_ESQUEMA_LISTO: list[str] = []


@pytest.fixture(scope="session")
def esquema() -> str:
    """Base de datos de pruebas con todas las migraciones aplicadas."""
    import asyncio

    if _ESQUEMA_LISTO:
        return _ESQUEMA_LISTO[0]

    try:
        asyncio.run(_crear_base_vacia())
    except Exception as error:  # pragma: no cover - depende del entorno
        pytest.skip(f"{MOTIVO_SIN_POSTGRES} ({error})")

    proceso = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": URL_PRUEBAS},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proceso.returncode == 0, proceso.stderr
    _ESQUEMA_LISTO.append(URL_PRUEBAS)
    return URL_PRUEBAS


@pytest_asyncio.fixture
async def motor(esquema: str) -> AsyncIterator[AsyncEngine]:
    motor = create_async_engine(esquema)
    yield motor
    await motor.dispose()


@pytest_asyncio.fixture
async def sesion(motor: AsyncEngine) -> AsyncIterator[AsyncSession]:
    fabrica = async_sessionmaker(motor, expire_on_commit=False, autoflush=False)
    async with fabrica() as sesion:
        yield sesion
        await sesion.rollback()


def crear_app() -> FastAPI:
    """Una aplicación con los routers de este grupo y los manejadores de error.

    No se usa `app.main:app` a propósito: el agregador de `app/api/v1/__init__.py`
    lo mantiene otra persona y estas pruebas deben poder ejecutarse antes de que
    registre nada.
    """
    app = FastAPI()
    registrar_manejadores(app)
    for modulo in MODULOS:
        app.include_router(modulo.router, prefix=RUTA)
    return app


async def crear_tematica(
    sesion: AsyncSession,
    hogar: Household,
    nombre: str,
    madre: Category | None = None,
    **extra: Any,
) -> Category:
    """Temática con la caché derivada (`depth`, `path_ids`, `sort_key`) coherente."""
    identificador = uuid.uuid4()
    ruta = [*madre.path_ids, identificador] if madre else [identificador]
    categoria = Category(
        id=identificador,
        household_id=hogar.id,
        parent_id=madre.id if madre else None,
        name=nombre,
        depth=len(ruta) - 1,
        path_ids=ruta,
        sort_key=".".join(f"{i:04d}" for i in range(len(ruta))),
        **extra,
    )
    sesion.add(categoria)
    await sesion.commit()
    return categoria


async def crear_hogar(sesion: AsyncSession, correo: str) -> tuple[Household, User]:
    hogar = Household(name=f"Hogar {correo}")
    usuario = User(
        email=correo,
        password_hash=hash_password("contrasenya-larga-de-pruebas"),
        display_name="Persona de pruebas",
    )
    sesion.add_all([hogar, usuario])
    await sesion.flush()
    sesion.add(
        HouseholdMember(
            household_id=hogar.id,
            user_id=usuario.id,
            role="owner",
            is_default=True,
            accepted_at=datetime.now(UTC),
        )
    )
    await sesion.commit()
    return hogar, usuario


@dataclass(slots=True)
class Entorno:
    """Un hogar con lo mínimo para poder apuntar dinero."""

    hogar: Household
    usuario: User
    corriente: Account
    ahorro: Account
    alimentacion: Category
    supermercado: Category
    ocio: Category
    nomina: Category


@pytest_asyncio.fixture
async def entorno(sesion: AsyncSession) -> Entorno:
    hogar, usuario = await crear_hogar(sesion, f"{uuid.uuid4().hex[:10]}@ejemplo.es")
    corriente = Account(
        household_id=hogar.id, name="BBVA Nómina", type="checking", account_class="asset"
    )
    ahorro = Account(household_id=hogar.id, name="Ahorro", type="savings", account_class="asset")
    sesion.add_all([corriente, ahorro])
    await sesion.commit()

    alimentacion = await crear_tematica(sesion, hogar, "Alimentación")
    supermercado = await crear_tematica(sesion, hogar, "Supermercado", alimentacion)
    ocio = await crear_tematica(sesion, hogar, "Ocio")
    nomina = await crear_tematica(sesion, hogar, "Nómina", kind="income")
    return Entorno(
        hogar=hogar,
        usuario=usuario,
        corriente=corriente,
        ahorro=ahorro,
        alimentacion=alimentacion,
        supermercado=supermercado,
        ocio=ocio,
        nomina=nomina,
    )


def cliente_de(sesion: AsyncSession, usuario: User) -> AsyncClient:
    """Cliente HTTP con la cookie de sesión y el doble envío de CSRF ya puestos."""
    app = crear_app()

    async def _sesion() -> AsyncIterator[AsyncSession]:
        yield sesion

    app.dependency_overrides[get_session] = _sesion
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://pruebas",
        cookies={"access_token": create_access_token(str(usuario.id)), CSRF_COOKIE_NAME: CSRF},
        headers={"X-CSRF-Token": CSRF},
    )


@pytest_asyncio.fixture
async def cliente(sesion: AsyncSession, entorno: Entorno) -> AsyncIterator[AsyncClient]:
    async with cliente_de(sesion, entorno.usuario) as cliente:
        yield cliente


@pytest.fixture
def sin_subidas(tmp_path: Path) -> Iterator[Path]:
    """Redirige el almacén de adjuntos a un directorio temporal."""
    original = settings.upload_dir
    settings.upload_dir = tmp_path
    yield tmp_path
    settings.upload_dir = original


async def alta_gasto(
    cliente: AsyncClient,
    entorno: Entorno,
    *,
    importe: str = "25.40",
    tematica: uuid.UUID | None = None,
    fecha: date | None = None,
    **extra: Any,
) -> dict[str, Any]:
    cuerpo = {
        "account_id": str(entorno.corriente.id),
        "date": (fecha or HOY).isoformat(),
        "amount": importe,
        "category_id": str(tematica or entorno.alimentacion.id),
        **extra,
    }
    respuesta = await cliente.post(f"{RUTA}/transactions", json=cuerpo)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def codigo_de(respuesta: Any) -> str:
    return respuesta.json()["error"]["codigo"]


def es_error(respuesta: Any, codigo: str, pista: str) -> bool:
    """Acepta el código de negocio o su equivalente de validación de esquema.

    Las mismas reglas se comprueban en dos capas. Cuando el cuerpo trae todo lo
    necesario las ve el validador de Pydantic, y `app/core/errors.py` publica
    siempre `datos_invalidos` con el mensaje propio dentro de `detalles`; cuando
    hacen falta datos guardados —el importe en `PUT .../splits`, la cuenta en una
    transferencia— las ve el servicio y salen con su `codigo` del catálogo de
    §1.2.
    """
    if respuesta.status_code != 422:
        return False
    error = respuesta.json()["error"]
    if error["codigo"] == codigo:
        return True
    return error["codigo"] == "datos_invalidos" and any(
        pista.lower() in f"{detalle['campo']} {detalle['mensaje']}".lower()
        for detalle in error["detalles"]
    )


def es_error_de_splits(respuesta: Any) -> bool:
    return es_error(respuesta, "splits_no_cuadran", "split")


# --------------------------------------------------------------------------- #
# Alta y listado
# --------------------------------------------------------------------------- #


async def test_un_gasto_se_guarda_en_negativo_y_se_devuelve_en_positivo(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """§1.7: `amount` es lo que se teclea y `signed_amount` el efecto en el saldo."""
    datos = await alta_gasto(cliente, entorno, importe="25.40")
    assert datos["amount"] == "25.40"
    assert datos["signed_amount"] == "-25.40"
    assert datos["kind"] == "expense"
    assert datos["is_split"] is False
    assert datos["category"]["name"] == "Alimentación"


async def test_una_devolucion_es_un_gasto_en_negativo(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """RN-26: reduce el gastado de su temática en vez de inflar los ingresos."""
    datos = await alta_gasto(cliente, entorno, importe="-12.00")
    assert datos["kind"] == "expense"
    assert datos["signed_amount"] == "12.00"


async def test_el_importe_como_numero_json_se_rechaza(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    respuesta = await cliente.post(
        f"{RUTA}/transactions",
        json={
            "account_id": str(entorno.corriente.id),
            "date": HOY.isoformat(),
            "amount": 25.4,
            "category_id": str(entorno.alimentacion.id),
        },
    )
    assert respuesta.status_code == 422
    assert codigo_de(respuesta) == "datos_invalidos"


async def test_sin_cookie_de_sesion_no_se_lista_nada(
    sesion: AsyncSession, entorno: Entorno
) -> None:
    app = crear_app()

    async def _sesion() -> AsyncIterator[AsyncSession]:
        yield sesion

    app.dependency_overrides[get_session] = _sesion
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://pruebas") as anonimo:
        respuesta = await anonimo.get(f"{RUTA}/transactions")
    assert respuesta.status_code == 401


async def test_una_peticion_mutante_sin_csrf_se_rechaza(
    sesion: AsyncSession, entorno: Entorno
) -> None:
    app = crear_app()

    async def _sesion() -> AsyncIterator[AsyncSession]:
        yield sesion

    app.dependency_overrides[get_session] = _sesion
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://pruebas",
        cookies={"access_token": create_access_token(str(entorno.usuario.id))},
    ) as sin_token:
        respuesta = await sin_token.post(
            f"{RUTA}/transactions",
            json={
                "account_id": str(entorno.corriente.id),
                "date": HOY.isoformat(),
                "amount": "10.00",
                "category_id": str(entorno.alimentacion.id),
            },
        )
    assert respuesta.status_code == 403
    assert codigo_de(respuesta) == "csrf_invalido"


async def test_los_filtros_se_combinan(cliente: AsyncClient, entorno: Entorno) -> None:
    """F-42: temática, rango de fechas, rango de importes y texto libre a la vez."""
    await alta_gasto(cliente, entorno, importe="10.00", description="Mercadona centro")
    await alta_gasto(
        cliente, entorno, importe="90.00", description="Cine Verdi", tematica=entorno.ocio.id
    )
    await alta_gasto(
        cliente,
        entorno,
        importe="40.00",
        description="Mercadona barrio",
        fecha=date(HOY.year, 1, 2),
    )

    respuesta = await cliente.get(
        f"{RUTA}/transactions",
        params={
            "q": "mercadona",
            "category_id": str(entorno.alimentacion.id),
            "min_amount": "5.00",
            "max_amount": "50.00",
            "date_from": date(HOY.year, 1, 1).isoformat(),
            "date_to": HOY.isoformat(),
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 2
    assert {item["description"] for item in cuerpo["items"]} == {
        "Mercadona centro",
        "Mercadona barrio",
    }


async def test_la_busqueda_no_distingue_acentos(cliente: AsyncClient, entorno: Entorno) -> None:
    await alta_gasto(cliente, entorno, description="Farmacia Ángeles")
    respuesta = await cliente.get(f"{RUTA}/transactions", params={"q": "angeles"})
    assert respuesta.json()["total"] == 1


async def test_el_filtro_por_tematica_es_jerarquico(cliente: AsyncClient, entorno: Entorno) -> None:
    """§7.3: filtrar por la madre incluye a las hijas salvo `include_children=false`."""
    await alta_gasto(cliente, entorno, tematica=entorno.supermercado.id)
    con_hijas = await cliente.get(
        f"{RUTA}/transactions", params={"category_id": str(entorno.alimentacion.id)}
    )
    sin_hijas = await cliente.get(
        f"{RUTA}/transactions",
        params={"category_id": str(entorno.alimentacion.id), "include_children": "false"},
    )
    assert con_hijas.json()["total"] == 1
    assert sin_hijas.json()["total"] == 0


async def test_el_rango_de_fechas_invertido_es_error_de_solicitud(
    cliente: AsyncClient,
) -> None:
    respuesta = await cliente.get(
        f"{RUTA}/transactions", params={"date_from": "2026-03-01", "date_to": "2026-01-01"}
    )
    assert respuesta.status_code == 400


async def test_la_ordenacion_solo_admite_la_lista_blanca(cliente: AsyncClient) -> None:
    respuesta = await cliente.get(f"{RUTA}/transactions", params={"sort": "password"})
    assert respuesta.status_code == 422


# --------------------------------------------------------------------------- #
# Splits (RN-15, RN-16)
# --------------------------------------------------------------------------- #


async def test_rn15_los_splits_se_validan_al_centimo(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """La suma tiene que ser exactamente el importe: un céntimo de más no pasa."""
    cuerpo = {
        "account_id": str(entorno.corriente.id),
        "date": HOY.isoformat(),
        "amount": "48.50",
        "splits": [
            {"category_id": str(entorno.supermercado.id), "amount": "45.00"},
            {"category_id": str(entorno.ocio.id), "amount": "3.51"},
        ],
    }
    respuesta = await cliente.post(f"{RUTA}/transactions", json=cuerpo)
    assert es_error_de_splits(respuesta), respuesta.text

    cuerpo["splits"][1]["amount"] = "3.50"
    respuesta = await cliente.post(f"{RUTA}/transactions", json=cuerpo)
    assert respuesta.status_code == 201, respuesta.text
    datos = respuesta.json()
    assert datos["is_split"] is True
    assert datos["category_id"] is None
    assert sorted(split["amount"] for split in datos["splits"]) == ["3.50", "45.00"]


async def test_rn15_el_reparto_completo_se_sustituye_y_es_idempotente(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await alta_gasto(cliente, entorno, importe="60.00")
    cuerpo = {
        "splits": [
            {"category_id": str(entorno.supermercado.id), "amount": "20.00"},
            {"category_id": str(entorno.ocio.id), "amount": "40.00"},
        ]
    }
    primera = await cliente.put(f"{RUTA}/transactions/{datos['id']}/splits", json=cuerpo)
    assert primera.status_code == 200, primera.text
    segunda = await cliente.put(f"{RUTA}/transactions/{datos['id']}/splits", json=cuerpo)
    assert segunda.status_code == 200
    assert len(segunda.json()["splits"]) == 2
    assert segunda.json()["category_id"] is None

    descuadrado = await cliente.put(
        f"{RUTA}/transactions/{datos['id']}/splits",
        json={"splits": [{"category_id": str(entorno.ocio.id), "amount": "59.99"}]},
    )
    assert es_error_de_splits(descuadrado), descuadrado.text


async def test_deshacer_el_reparto_devuelve_una_sola_tematica(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """El invariante no admite estados intermedios: la cabecera recupera temática."""
    datos = await alta_gasto(cliente, entorno, importe="30.00")
    await cliente.put(
        f"{RUTA}/transactions/{datos['id']}/splits",
        json={
            "splits": [
                {"category_id": str(entorno.supermercado.id), "amount": "10.00"},
                {"category_id": str(entorno.ocio.id), "amount": "20.00"},
            ]
        },
    )
    respuesta = await cliente.delete(
        f"{RUTA}/transactions/{datos['id']}/splits",
        params={"category_id": str(entorno.ocio.id)},
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["is_split"] is False
    assert respuesta.json()["category_id"] == str(entorno.ocio.id)


async def test_rn16_cambiar_el_importe_de_un_reparto_obliga_a_reenviarlo(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await alta_gasto(cliente, entorno, importe="30.00")
    await cliente.put(
        f"{RUTA}/transactions/{datos['id']}/splits",
        json={
            "splits": [
                {"category_id": str(entorno.supermercado.id), "amount": "10.00"},
                {"category_id": str(entorno.ocio.id), "amount": "20.00"},
            ]
        },
    )
    solo_importe = await cliente.patch(
        f"{RUTA}/transactions/{datos['id']}", json={"amount": "48.50"}
    )
    assert es_error_de_splits(solo_importe), solo_importe.text

    con_reparto = await cliente.patch(
        f"{RUTA}/transactions/{datos['id']}",
        json={
            "amount": "48.50",
            "splits": [
                {"category_id": str(entorno.supermercado.id), "amount": "28.50"},
                {"category_id": str(entorno.ocio.id), "amount": "20.00"},
            ],
        },
    )
    assert con_reparto.status_code == 200, con_reparto.text
    assert con_reparto.json()["amount"] == "48.50"


async def test_una_tematica_repetida_en_el_reparto_se_rechaza(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    respuesta = await cliente.post(
        f"{RUTA}/transactions",
        json={
            "account_id": str(entorno.corriente.id),
            "date": HOY.isoformat(),
            "amount": "20.00",
            "splits": [
                {"category_id": str(entorno.ocio.id), "amount": "10.00"},
                {"category_id": str(entorno.ocio.id), "amount": "10.00"},
            ],
        },
    )
    assert es_error_de_splits(respuesta), respuesta.text


async def test_un_split_con_tematica_de_ingresos_se_rechaza(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """RN-15: ninguna temática de `kind` distinto al del movimiento."""
    respuesta = await cliente.post(
        f"{RUTA}/transactions",
        json={
            "account_id": str(entorno.corriente.id),
            "date": HOY.isoformat(),
            "amount": "20.00",
            "splits": [
                {"category_id": str(entorno.ocio.id), "amount": "15.00"},
                {"category_id": str(entorno.nomina.id), "amount": "5.00"},
            ],
        },
    )
    assert es_error_de_splits(respuesta), respuesta.text


# --------------------------------------------------------------------------- #
# Transferencias (RN-21 a RN-24)
# --------------------------------------------------------------------------- #


async def crear_transferencia(
    cliente: AsyncClient, entorno: Entorno, importe: str = "200.00", **extra: Any
) -> dict[str, Any]:
    respuesta = await cliente.post(
        f"{RUTA}/transfers",
        json={
            "from_account_id": str(entorno.corriente.id),
            "to_account_id": str(entorno.ahorro.id),
            "date": HOY.isoformat(),
            "amount": importe,
            **extra,
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


async def test_una_transferencia_tiene_dos_patas_que_suman_cero(
    cliente: AsyncClient, entorno: Entorno, sesion: AsyncSession
) -> None:
    datos = await crear_transferencia(cliente, entorno)
    assert datos["amount"] == "200.00"
    total = await sesion.scalar(
        text("SELECT SUM(amount) FROM transactions WHERE transfer_group_id = :grupo").bindparams(
            grupo=uuid.UUID(datos["transfer_group_id"])
        )
    )
    assert Decimal(total) == Decimal("0.00")

    detalle = await cliente.get(f"{RUTA}/transactions/{datos['out_transaction_id']}")
    assert detalle.json()["kind"] == "transfer"
    assert detalle.json()["category_id"] is None
    assert detalle.json()["transfer_counterpart_id"] == datos["in_transaction_id"]


async def test_rn21_una_transferencia_no_es_gasto_ni_ingreso(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """No aparece en el informe de gasto por temática ni en los ingresos del mes."""
    await alta_gasto(cliente, entorno, importe="30.00")
    await crear_transferencia(cliente, entorno, importe="500.00")

    barra = (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()
    assert barra["spent_total"] == "30.00"
    assert barra["income_actual"] == "0.00"

    ingresos = (await cliente.get(f"{RUTA}/budgets/{PERIODO}/incomes")).json()
    assert ingresos["total"] == 0

    gastos = (await cliente.get(f"{RUTA}/transactions", params={"kind": "expense"})).json()
    assert gastos["total"] == 1


async def test_rn22_no_se_transfiere_a_la_misma_cuenta(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    respuesta = await cliente.post(
        f"{RUTA}/transfers",
        json={
            "from_account_id": str(entorno.corriente.id),
            "to_account_id": str(entorno.corriente.id),
            "date": HOY.isoformat(),
            "amount": "10.00",
        },
    )
    assert es_error(respuesta, "transferencia_invalida", "misma"), respuesta.text


async def test_la_comision_de_una_transferencia_si_es_un_gasto(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await crear_transferencia(
        cliente,
        entorno,
        importe="100.00",
        fee="1.50",
        fee_category_id=str(entorno.ocio.id),
    )
    assert datos["fee"] == "1.50"
    assert datos["fee_transaction_id"] is not None
    barra = (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()
    assert barra["spent_total"] == "1.50"


async def test_rn24_borrar_una_pata_borra_las_dos(cliente: AsyncClient, entorno: Entorno) -> None:
    datos = await crear_transferencia(cliente, entorno)
    respuesta = await cliente.delete(f"{RUTA}/transactions/{datos['out_transaction_id']}")
    assert respuesta.status_code == 204
    assert (await cliente.get(f"{RUTA}/transfers/{datos['transfer_group_id']}")).status_code == 404
    restantes = (await cliente.get(f"{RUTA}/transactions", params={"kind": "transfer"})).json()
    assert restantes["total"] == 0


async def test_una_transferencia_se_edita_por_las_dos_patas(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await crear_transferencia(cliente, entorno, importe="100.00")
    respuesta = await cliente.patch(
        f"{RUTA}/transfers/{datos['transfer_group_id']}", json={"amount": "150.00"}
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["amount"] == "150.00"
    salida = await cliente.get(f"{RUTA}/transactions/{datos['out_transaction_id']}")
    entrada = await cliente.get(f"{RUTA}/transactions/{datos['in_transaction_id']}")
    assert salida.json()["signed_amount"] == "-150.00"
    assert entrada.json()["signed_amount"] == "150.00"


async def test_una_transaccion_no_se_convierte_en_transferencia(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await alta_gasto(cliente, entorno)
    respuesta = await cliente.patch(f"{RUTA}/transactions/{datos['id']}", json={"kind": "transfer"})
    assert es_error(respuesta, "transferencia_invalida", "transferencia"), respuesta.text


async def test_una_pata_de_transferencia_no_se_reparte(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await crear_transferencia(cliente, entorno, importe="50.00")
    respuesta = await cliente.put(
        f"{RUTA}/transactions/{datos['out_transaction_id']}/splits",
        json={"splits": [{"category_id": str(entorno.ocio.id), "amount": "50.00"}]},
    )
    assert respuesta.status_code == 422
    assert codigo_de(respuesta) == "transferencia_invalida"


async def test_las_transferencias_se_listan_agrupadas(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await crear_transferencia(cliente, entorno, importe="10.00")
    await crear_transferencia(cliente, entorno, importe="20.00")
    listado = (await cliente.get(f"{RUTA}/transfers")).json()
    assert listado["total"] == 2
    assert {item["amount"] for item in listado["items"]} == {"10.00", "20.00"}


# --------------------------------------------------------------------------- #
# Etiquetas, comercios, lotes y duplicados
# --------------------------------------------------------------------------- #


async def test_el_comercio_se_crea_al_vuelo_por_nombre(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await alta_gasto(cliente, entorno, payee_name="Mercadona")
    assert datos["payee"]["name"] == "Mercadona"
    otra = await alta_gasto(cliente, entorno, payee_name="MERCADONA")
    assert otra["payee"]["id"] == datos["payee"]["id"]


async def test_las_etiquetas_se_asignan_y_se_quitan_en_lote(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    etiqueta = (
        await cliente.post(f"{RUTA}/tags", json={"name": "Roma", "color": "#568ef9"})
    ).json()
    primera = await alta_gasto(cliente, entorno, importe="10.00")
    segunda = await alta_gasto(cliente, entorno, importe="20.00")

    respuesta = await cliente.post(
        f"{RUTA}/transactions/bulk-tag",
        json={"ids": [primera["id"], segunda["id"]], "add": [etiqueta["id"]]},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["affected"] == 2

    con_etiqueta = (
        await cliente.get(f"{RUTA}/transactions", params={"tag_id": etiqueta["id"]})
    ).json()
    assert con_etiqueta["total"] == 2

    await cliente.post(
        f"{RUTA}/transactions/bulk-tag",
        json={"ids": [primera["id"]], "remove": [etiqueta["id"]]},
    )
    quedan = (await cliente.get(f"{RUTA}/transactions", params={"tag_id": etiqueta["id"]})).json()
    assert quedan["total"] == 1


async def test_categorizar_en_lote_no_toca_transferencias(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    gasto = await alta_gasto(cliente, entorno)
    transferencia = await crear_transferencia(cliente, entorno)
    respuesta = await cliente.post(
        f"{RUTA}/transactions/bulk-categorize",
        json={
            "ids": [gasto["id"], transferencia["out_transaction_id"]],
            "category_id": str(entorno.ocio.id),
        },
    )
    cuerpo = respuesta.json()
    assert cuerpo["affected"] == 1
    assert cuerpo["skipped"] == 1


async def test_los_duplicados_se_marcan_pero_no_se_borran(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await alta_gasto(cliente, entorno, importe="12.30", description="Cafe")
    await alta_gasto(cliente, entorno, importe="12.30", description="Cafe")
    respuesta = await cliente.get(f"{RUTA}/transactions/duplicates")
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 1
    assert len(cuerpo["items"][0]["transactions"]) == 2
    # Nada se ha borrado: siguen las dos.
    assert (await cliente.get(f"{RUTA}/transactions")).json()["total"] == 2


async def test_fusionar_un_duplicado_conserva_lo_mejor_de_cada_uno(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    principal = await alta_gasto(cliente, entorno, importe="12.30", description="Cafe")
    duplicada = await alta_gasto(
        cliente, entorno, importe="12.30", description="Cafetería del centro"
    )
    respuesta = await cliente.post(
        f"{RUTA}/transactions/{principal['id']}/merge",
        json={"duplicate_id": duplicada["id"], "keep": {"description": "duplicate"}},
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["description"] == "Cafetería del centro"
    assert (await cliente.get(f"{RUTA}/transactions")).json()["total"] == 1


async def test_el_borrado_en_lote_devuelve_lo_afectado(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    primera = await alta_gasto(cliente, entorno, importe="10.00")
    segunda = await alta_gasto(cliente, entorno, importe="20.00")
    respuesta = await cliente.post(
        f"{RUTA}/transactions/bulk-delete", json={"ids": [primera["id"], segunda["id"]]}
    )
    assert respuesta.json()["affected"] == 2
    assert (await cliente.get(f"{RUTA}/transactions")).json()["total"] == 0


async def test_borrar_dos_veces_devuelve_204(cliente: AsyncClient, entorno: Entorno) -> None:
    """§1.9: `DELETE` es idempotente."""
    datos = await alta_gasto(cliente, entorno)
    assert (await cliente.delete(f"{RUTA}/transactions/{datos['id']}")).status_code == 204
    assert (await cliente.delete(f"{RUTA}/transactions/{datos['id']}")).status_code == 204


async def test_las_reglas_categorizan_el_alta_sin_tematica(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """F-27: si no se da temática, deciden las reglas."""
    regla = await cliente.post(
        f"{RUTA}/rules",
        json={
            "name": "Mercadona",
            "conditions": [{"field": "description", "operator": "contains", "value": "mercadona"}],
            "actions": {"set_category_id": str(entorno.supermercado.id)},
        },
    )
    assert regla.status_code == 201, regla.text

    respuesta = await cliente.post(
        f"{RUTA}/transactions",
        json={
            "account_id": str(entorno.corriente.id),
            "date": HOY.isoformat(),
            "amount": "31.20",
            "description": "COMPRA 4021 MERCADONA SA",
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["category"]["name"] == "Supermercado"
    assert respuesta.json()["categorized_by"] == "rule"


async def test_probar_una_regla_no_la_guarda(cliente: AsyncClient, entorno: Entorno) -> None:
    await alta_gasto(cliente, entorno, description="Netflix mensual")
    respuesta = await cliente.post(
        f"{RUTA}/rules/test",
        json={
            "rule": {
                "name": "Netflix",
                "conditions": [
                    {"field": "description", "operator": "contains", "value": "netflix"}
                ],
                "actions": {"set_category_id": str(entorno.ocio.id)},
            },
            "sample_text": "NETFLIX.COM 4021",
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["sample_matched"] is True
    assert cuerpo["matches"] == 1
    assert (await cliente.get(f"{RUTA}/rules")).json()["total"] == 0


async def test_aplicar_reglas_en_seco_no_cambia_nada(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await alta_gasto(cliente, entorno, description="Netflix", importe="12.99")
    await cliente.post(
        f"{RUTA}/rules",
        json={
            "name": "Netflix",
            "conditions": [{"field": "description", "operator": "contains", "value": "netflix"}],
            "actions": {"set_category_id": str(entorno.ocio.id)},
        },
    )
    seco = await cliente.post(f"{RUTA}/rules/apply", json={"scope": "all", "dry_run": True})
    assert seco.status_code == 200, seco.text
    cuerpo = seco.json()
    assert cuerpo["dry_run"] is True
    # La transacción se categorizó a mano, así que la regla la respeta (RN-56).
    assert cuerpo["manual_preserved"] == 1
    assert cuerpo["updated"] == 0
    sin_cambios = await cliente.get(f"{RUTA}/transactions/{datos['id']}")
    assert sin_cambios.json()["category_id"] == str(entorno.alimentacion.id)


async def test_un_adjunto_se_valida_por_su_firma(
    cliente: AsyncClient, entorno: Entorno, sin_subidas: Path
) -> None:
    """RN-76: el tipo lo decide el contenido, no el nombre ni la cabecera."""
    datos = await alta_gasto(cliente, entorno)
    falso = await cliente.post(
        f"{RUTA}/transactions/{datos['id']}/attachments",
        files={"fichero": ("recibo.pdf", b"esto no es un pdf", "application/pdf")},
    )
    assert falso.status_code == 415

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    bueno = await cliente.post(
        f"{RUTA}/transactions/{datos['id']}/attachments",
        files={"fichero": ("recibo.txt", png, "text/plain")},
    )
    assert bueno.status_code == 201, bueno.text
    assert bueno.json()["content_type"] == "image/png"
    con_adjunto = await cliente.get(f"{RUTA}/transactions/{datos['id']}")
    assert con_adjunto.json()["attachments_count"] == 1


# --------------------------------------------------------------------------- #
# Fondos objetivo: la aportación con cuenta es una transferencia real (RN-53)
# --------------------------------------------------------------------------- #


async def crear_fondo(cliente: AsyncClient, entorno: Entorno, **extra: Any) -> dict[str, Any]:
    respuesta = await cliente.post(
        f"{RUTA}/goals",
        json={
            "name": extra.pop("name", "Vacaciones"),
            "target_amount": extra.pop("target_amount", "2400.00"),
            "account_id": str(entorno.ahorro.id),
            **extra,
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


async def test_una_aportacion_con_cuenta_genera_una_transferencia(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """Y por tanto no cuenta como gasto en la barra del mes (RN-21)."""
    fondo = await crear_fondo(cliente, entorno)
    respuesta = await cliente.post(
        f"{RUTA}/goals/{fondo['id']}/contribute",
        json={
            "amount": "200.00",
            "date": HOY.isoformat(),
            "account_id": str(entorno.corriente.id),
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["current_amount"] == "200.00"
    assert respuesta.json()["remaining"] == "2200.00"

    assert (await cliente.get(f"{RUTA}/transfers")).json()["total"] == 1
    assert (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()["spent_total"] == "0.00"

    movimientos = (await cliente.get(f"{RUTA}/goals/{fondo['id']}/movements")).json()
    assert movimientos["total"] == 1
    assert movimientos["items"][0]["kind"] == "contribution"
    assert movimientos["items"][0]["transaction_id"] is not None
    assert movimientos["items"][0]["balance_after"] == "200.00"


async def test_rn52_no_se_retira_mas_de_lo_acumulado(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    fondo = await crear_fondo(cliente, entorno, name="Coche", initial_amount="100.00")
    respuesta = await cliente.post(
        f"{RUTA}/goals/{fondo['id']}/withdraw",
        json={"amount": "150.00", "date": HOY.isoformat()},
    )
    assert respuesta.status_code == 422
    assert codigo_de(respuesta) == "saldo_insuficiente"

    valida = await cliente.post(
        f"{RUTA}/goals/{fondo['id']}/withdraw",
        json={"amount": "40.00", "date": HOY.isoformat()},
    )
    assert valida.status_code == 200, valida.text
    assert valida.json()["current_amount"] == "60.00"


async def test_rn54_un_fondo_se_marca_completado_y_sigue_admitiendo_dinero(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    fondo = await crear_fondo(cliente, entorno, name="Portátil", target_amount="100.00")
    lleno = await cliente.post(
        f"{RUTA}/goals/{fondo['id']}/contribute",
        json={"amount": "100.00", "date": HOY.isoformat()},
    )
    assert lleno.json()["is_completed"] is True
    assert lleno.json()["remaining"] == "0.00"

    de_mas = await cliente.post(
        f"{RUTA}/goals/{fondo['id']}/contribute",
        json={"amount": "25.00", "date": HOY.isoformat()},
    )
    assert de_mas.status_code == 200
    assert de_mas.json()["current_amount"] == "125.00"


# --------------------------------------------------------------------------- #
# Aislamiento entre hogares (RN-01, RN-02)
# --------------------------------------------------------------------------- #


async def test_rn02_una_transaccion_de_otro_hogar_da_404(
    sesion: AsyncSession, entorno: Entorno
) -> None:
    """Nunca 403: distinguirlos permitiría enumerar identificadores."""
    otro_hogar, otro_usuario = await crear_hogar(sesion, f"{uuid.uuid4().hex[:10]}@otro.es")
    otra_cuenta = Account(
        household_id=otro_hogar.id, name="Santander", type="checking", account_class="asset"
    )
    sesion.add(otra_cuenta)
    await sesion.commit()
    otra_tematica = await crear_tematica(sesion, otro_hogar, "Alimentación")

    async with cliente_de(sesion, otro_usuario) as ajeno:
        suya = await ajeno.post(
            f"{RUTA}/transactions",
            json={
                "account_id": str(otra_cuenta.id),
                "date": HOY.isoformat(),
                "amount": "9.99",
                "category_id": str(otra_tematica.id),
            },
        )
        assert suya.status_code == 201, suya.text

    async with cliente_de(sesion, entorno.usuario) as propio:
        assert (await propio.get(f"{RUTA}/transactions")).json()["total"] == 0
        assert (await propio.get(f"{RUTA}/transactions/{suya.json()['id']}")).status_code == 404
        borrado = await propio.delete(f"{RUTA}/transactions/{suya.json()['id']}")
        assert borrado.status_code == 204  # idempotente, pero no ha borrado nada

    async with cliente_de(sesion, otro_usuario) as ajeno:
        assert (await ajeno.get(f"{RUTA}/transactions")).json()["total"] == 1


async def test_pedir_un_hogar_ajeno_da_403(sesion: AsyncSession, entorno: Entorno) -> None:
    otro_hogar, _ = await crear_hogar(sesion, f"{uuid.uuid4().hex[:10]}@ajeno.es")
    async with cliente_de(sesion, entorno.usuario) as propio:
        respuesta = await propio.get(
            f"{RUTA}/transactions", params={"household_id": str(otro_hogar.id)}
        )
    assert respuesta.status_code == 403


async def test_no_se_puede_usar_una_cuenta_de_otro_hogar(
    sesion: AsyncSession, entorno: Entorno, cliente: AsyncClient
) -> None:
    """La tercera capa de tenencia son las FK compuestas; la primera, este 404."""
    otro_hogar, _ = await crear_hogar(sesion, f"{uuid.uuid4().hex[:10]}@fuga.es")
    ajena = Account(household_id=otro_hogar.id, name="Ajena", type="cash", account_class="asset")
    sesion.add(ajena)
    await sesion.commit()

    respuesta = await cliente.post(
        f"{RUTA}/transactions",
        json={
            "account_id": str(ajena.id),
            "date": HOY.isoformat(),
            "amount": "5.00",
            "category_id": str(entorno.alimentacion.id),
        },
    )
    assert respuesta.status_code == 404


async def test_un_invitado_no_escribe(sesion: AsyncSession, entorno: Entorno) -> None:
    """`AlcanceEscritura` rechaza a los miembros de solo lectura."""
    invitado = User(
        email=f"{uuid.uuid4().hex[:10]}@invitado.es",
        password_hash=hash_password("contrasenya-larga-de-pruebas"),
        display_name="Invitado",
    )
    sesion.add(invitado)
    await sesion.flush()
    sesion.add(
        HouseholdMember(
            household_id=entorno.hogar.id,
            user_id=invitado.id,
            role="viewer",
            is_default=True,
            accepted_at=datetime.now(UTC),
        )
    )
    await sesion.commit()

    async with cliente_de(sesion, invitado) as solo_lectura:
        assert (await solo_lectura.get(f"{RUTA}/transactions")).status_code == 200
        respuesta = await solo_lectura.post(
            f"{RUTA}/transactions",
            json={
                "account_id": str(entorno.corriente.id),
                "date": HOY.isoformat(),
                "amount": "5.00",
                "category_id": str(entorno.alimentacion.id),
            },
        )
    assert respuesta.status_code == 403
