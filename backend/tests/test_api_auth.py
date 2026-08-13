"""Pruebas de identidad y sesión, y **utillaje compartido de las pruebas de API**.

Las pruebas van contra PostgreSQL de verdad (`docker compose up -d db`): la mitad
de lo que hay que comprobar —vistas, disparadores, índices parciales, funciones del
árbol— no existe en SQLite, así que probar contra otro motor daría una confianza
falsa.

**Aislamiento.** Cada prueba abre una conexión, arranca una transacción y la
descarta al terminar; la sesión de la aplicación se une a ella con
`join_transaction_mode="create_savepoint"`, de modo que los `commit()` de los
endpoints son reales para la prueba y no dejan nada escrito en la base de datos.

Las tres pruebas restantes de API importan de aquí las fixtures (`from
test_api_auth import cliente  # noqa: F401`) porque `conftest.py` es territorio
compartido con el resto de módulos y no se toca.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1 import auth, categorias, cuentas, usuarios
from app.core.config import settings
from app.core.errors import registrar_manejadores
from app.core.security import CSRF_COOKIE_NAME
from app.db.session import get_session
from app.models.hogar import HouseholdMember
from app.models.usuario import RefreshToken, User

#: `conftest.py` fija `DATABASE_URL` a SQLite para las pruebas de servicios puros,
#: así que aquí se usa una URL propia y se sustituye la dependencia de sesión.
URL_PRUEBAS = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://presupuesto:presupuesto@localhost:5432/presupuesto",
)

PREFIJO = settings.api_prefix
CONTRASENYA = "Contrasenya1"


def _crear_app() -> FastAPI:
    """Aplicación con solo los routers de este lote.

    No se usa `app.main:app`: el agregador `app/api/v1/__init__.py` lo rellena
    quien integra, y hay más agentes escribiendo routers en paralelo.
    """
    aplicacion = FastAPI()
    registrar_manejadores(aplicacion)
    ruteador = APIRouter()
    for modulo in (auth, usuarios, cuentas, categorias):
        ruteador.include_router(modulo.router)
    aplicacion.include_router(ruteador, prefix=PREFIJO)
    return aplicacion


APP = _crear_app()


@pytest.fixture(autouse=True)
def limitador_limpio() -> None:
    """El cubo de fichas es global al proceso: sin esto, la prueba 11 daría 429."""
    auth.limitador.reiniciar()


@pytest.fixture
async def sesion_bd() -> AsyncIterator[AsyncSession]:
    """Sesión de la aplicación atada a una transacción que se descarta al final."""
    motor = create_async_engine(URL_PRUEBAS, poolclass=NullPool)
    async with motor.connect() as conexion:
        transaccion = await conexion.begin()
        fabrica = async_sessionmaker(
            bind=conexion,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        sesion = fabrica()

        async def _dependencia() -> AsyncIterator[AsyncSession]:
            yield sesion

        APP.dependency_overrides[get_session] = _dependencia
        try:
            yield sesion
        finally:
            APP.dependency_overrides.clear()
            await sesion.close()
            await transaccion.rollback()
    await motor.dispose()


@pytest.fixture
async def navegadores(sesion_bd: AsyncSession) -> AsyncIterator[Callable[[], AsyncClient]]:
    """Fábrica de clientes HTTP: cada uno con su propio tarro de cookies."""
    abiertos: list[AsyncClient] = []

    def abrir() -> AsyncClient:
        cliente = AsyncClient(transport=ASGITransport(app=APP), base_url="http://pruebas")
        abiertos.append(cliente)
        return cliente

    yield abrir
    for cliente in abiertos:
        await cliente.aclose()


@pytest.fixture
async def cliente(navegadores: Callable[[], AsyncClient]) -> AsyncClient:
    return navegadores()


def cabeceras(cliente: AsyncClient) -> dict[str, str]:
    """Doble envío del CSRF: copia la cookie legible en la cabecera (§1.11)."""
    token = cliente.cookies.get(CSRF_COOKIE_NAME)
    return {"X-CSRF-Token": token} if token else {}


def sustituir_cookie(cliente: AsyncClient, nombre: str, valor: str) -> None:
    """Cambia el valor de una cookie **sin tocar su dominio ni su ruta**.

    Pasar `cookies=` en la petición o escribir la cabecera `Cookie` a mano hace que
    httpx descarte el resto del tarro, y entonces el fallo que se observa es el del
    CSRF y no el que se quería provocar.
    """
    for galleta in cliente.cookies.jar:
        if galleta.name == nombre:
            galleta.value = valor
            return
    raise AssertionError(f"El cliente no tiene la cookie {nombre}")


def correo_nuevo() -> str:
    return f"prueba-{uuid.uuid4().hex[:12]}@example.com"


async def registrar(
    cliente: AsyncClient, *, email: str | None = None, nombre: str = "Ana Pérez"
) -> str:
    """Alta completa: deja al cliente con sesión abierta y su hogar creado."""
    correo = email or correo_nuevo()
    await cliente.get(f"{PREFIJO}/auth/csrf")
    respuesta = await cliente.post(
        f"{PREFIJO}/auth/register",
        json={"email": correo, "password": CONTRASENYA, "name": nombre},
    )
    assert respuesta.status_code == 201, respuesta.text
    return correo


async def hogar_de(sesion: AsyncSession, correo: str) -> uuid.UUID:
    """Hogar por defecto del usuario, para sembrar datos que aún no tienen endpoint."""
    identificador = await sesion.scalar(
        select(HouseholdMember.household_id)
        .join(User, User.id == HouseholdMember.user_id)
        .where(func.lower(User.email) == correo, HouseholdMember.is_default.is_(True))
    )
    assert identificador is not None
    return identificador


async def usuario_de(sesion: AsyncSession, correo: str) -> uuid.UUID:
    identificador = await sesion.scalar(select(User.id).where(func.lower(User.email) == correo))
    assert identificador is not None
    return identificador


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #


async def test_registro_crea_hogar_miembro_owner_y_tres_cookies(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    correo = correo_nuevo()
    await cliente.get(f"{PREFIJO}/auth/csrf")
    respuesta = await cliente.post(
        f"{PREFIJO}/auth/register",
        json={"email": correo, "password": CONTRASENYA, "name": "Ana Pérez"},
    )

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["email"] == correo
    assert cuerpo["name"] == "Ana Pérez"
    assert cuerpo["onboarding_completed"] is False
    assert set(cliente.cookies) >= {"access_token", "refresh_token", CSRF_COOKIE_NAME}

    # El hogar y la pertenencia `owner` por defecto existen y son operativos.
    yo = await cliente.get(f"{PREFIJO}/auth/me")
    assert yo.status_code == 200, yo.text
    assert yo.json()["current_period"][:4].isdigit()
    assert yo.json()["accounts_count"] == 0


async def test_cookie_de_refresco_solo_viaja_a_auth(cliente: AsyncClient) -> None:
    await registrar(cliente)
    galleta = next(g for g in cliente.cookies.jar if g.name == "refresh_token")
    assert galleta.path == f"{PREFIJO}/auth"
    acceso = next(g for g in cliente.cookies.jar if g.name == "access_token")
    assert acceso.path == PREFIJO


async def test_registro_rechaza_un_correo_ya_usado(cliente: AsyncClient) -> None:
    correo = await registrar(cliente)
    respuesta = await cliente.post(
        f"{PREFIJO}/auth/register",
        json={"email": correo, "password": CONTRASENYA, "name": "Otra"},
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["codigo"] == "email_ya_registrado"


async def test_registro_deshabilitado_cuando_ya_hay_usuarios(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """RN-06: cerrado salvo que la instalación esté todavía sin estrenar."""
    await registrar(cliente)
    monkeypatch.setattr(settings, "allow_registration", False)

    otro = navegadores()
    await otro.get(f"{PREFIJO}/auth/csrf")
    respuesta = await otro.post(
        f"{PREFIJO}/auth/register",
        json={"email": correo_nuevo(), "password": CONTRASENYA, "name": "Nadie"},
    )
    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["codigo"] == "registro_deshabilitado"


async def test_contrasenya_debil_se_rechaza(cliente: AsyncClient) -> None:
    await cliente.get(f"{PREFIJO}/auth/csrf")
    respuesta = await cliente.post(
        f"{PREFIJO}/auth/register",
        json={"email": correo_nuevo(), "password": "1234567890", "name": "Ana"},
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["detalles"][0]["campo"] == "password"


# --------------------------------------------------------------------------- #
# Login y bloqueo
# --------------------------------------------------------------------------- #


async def test_login_no_revela_si_el_correo_existe(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient]
) -> None:
    """§2.4: correo inexistente y contraseña errónea dan exactamente lo mismo."""
    correo = await registrar(cliente)

    otro = navegadores()
    await otro.get(f"{PREFIJO}/auth/csrf")
    desconocido = await otro.post(
        f"{PREFIJO}/auth/login",
        json={"email": correo_nuevo(), "password": CONTRASENYA},
    )
    equivocada = await otro.post(
        f"{PREFIJO}/auth/login", json={"email": correo, "password": "Equivocada9"}
    )

    assert desconocido.status_code == equivocada.status_code == 401
    assert desconocido.json() == equivocada.json()
    assert desconocido.json()["error"]["codigo"] == "credenciales_invalidas"


async def test_login_bloquea_con_espera_creciente(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient], sesion_bd: AsyncSession
) -> None:
    """Cinco fallos consecutivos y el correo queda bloqueado con 429."""
    correo = await registrar(cliente)
    otro = navegadores()
    await otro.get(f"{PREFIJO}/auth/csrf")

    for _ in range(5):
        fallo = await otro.post(
            f"{PREFIJO}/auth/login", json={"email": correo, "password": "Equivocada9"}
        )
        assert fallo.status_code == 401

    bloqueado = await otro.post(
        f"{PREFIJO}/auth/login", json={"email": correo, "password": CONTRASENYA}
    )
    assert bloqueado.status_code == 429
    assert bloqueado.json()["error"]["codigo"] == "demasiadas_peticiones"
    # El mensaje no dice si el correo existe.
    assert correo not in bloqueado.json()["error"]["mensaje"]

    sesion_bd.expire_all()
    fila = (
        await sesion_bd.execute(
            select(User.failed_login_count, User.locked_until).where(User.email == correo)
        )
    ).one()
    assert fila.failed_login_count == 5
    assert fila.locked_until is not None


async def test_login_correcto_reinicia_el_contador(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient], sesion_bd: AsyncSession
) -> None:
    correo = await registrar(cliente)
    otro = navegadores()
    await otro.get(f"{PREFIJO}/auth/csrf")
    await otro.post(f"{PREFIJO}/auth/login", json={"email": correo, "password": "Equivocada9"})

    bien = await otro.post(f"{PREFIJO}/auth/login", json={"email": correo, "password": CONTRASENYA})
    assert bien.status_code == 200
    assert "access_token" in otro.cookies

    sesion_bd.expire_all()
    fallos = await sesion_bd.scalar(select(User.failed_login_count).where(User.email == correo))
    assert fallos == 0


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #


async def test_csrf_bloquea_una_peticion_mutante_sin_cabecera(cliente: AsyncClient) -> None:
    """§1.11: la cookie viaja sola, pero un sitio ajeno no puede leerla."""
    await registrar(cliente)

    sin_cabecera = await cliente.post(f"{PREFIJO}/auth/logout")
    assert sin_cabecera.status_code == 403
    assert sin_cabecera.json()["error"]["codigo"] == "csrf_invalido"

    con_cabecera = await cliente.post(f"{PREFIJO}/auth/logout", headers=cabeceras(cliente))
    assert con_cabecera.status_code == 204


async def test_csrf_rechaza_una_cabecera_que_no_coincide(cliente: AsyncClient) -> None:
    await registrar(cliente)
    respuesta = await cliente.post(
        f"{PREFIJO}/auth/logout", headers={"X-CSRF-Token": "valor-inventado"}
    )
    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["codigo"] == "csrf_invalido"


async def test_csrf_emite_la_cookie_si_no_existia(cliente: AsyncClient) -> None:
    respuesta = await cliente.get(f"{PREFIJO}/auth/csrf")
    assert respuesta.status_code == 200
    assert respuesta.json()["csrf_token"] == cliente.cookies.get(CSRF_COOKIE_NAME)


# --------------------------------------------------------------------------- #
# Refresco rotatorio (RN-04)
# --------------------------------------------------------------------------- #


async def test_refresh_rota_el_token_y_el_viejo_deja_de_valer(cliente: AsyncClient) -> None:
    await registrar(cliente)
    antiguo = cliente.cookies.get("refresh_token")

    primero = await cliente.post(f"{PREFIJO}/auth/refresh", headers=cabeceras(cliente))
    assert primero.status_code == 200, primero.text
    nuevo = cliente.cookies.get("refresh_token")
    assert nuevo != antiguo
    assert "expires_at" in primero.json()

    # Reutilizar el consumido: se asume robo y se revoca la familia entera.
    sustituir_cookie(cliente, "refresh_token", antiguo)
    reutilizado = await cliente.post(f"{PREFIJO}/auth/refresh", headers=cabeceras(cliente))
    assert reutilizado.status_code == 401
    assert reutilizado.json()["error"]["codigo"] == "sesion_expirada"

    # Y el token que sí era válido tampoco sirve ya.
    sustituir_cookie(cliente, "refresh_token", nuevo)
    tras_el_robo = await cliente.post(f"{PREFIJO}/auth/refresh", headers=cabeceras(cliente))
    assert tras_el_robo.status_code == 401


async def test_refresh_sin_cookie_devuelve_sesion_expirada(cliente: AsyncClient) -> None:
    await cliente.get(f"{PREFIJO}/auth/csrf")
    respuesta = await cliente.post(f"{PREFIJO}/auth/refresh", headers=cabeceras(cliente))
    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["codigo"] == "sesion_expirada"


# --------------------------------------------------------------------------- #
# Cierre de sesión, contraseña y dispositivos
# --------------------------------------------------------------------------- #


async def test_logout_borra_las_cookies_y_revoca_el_refresco(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    correo = await registrar(cliente)
    respuesta = await cliente.post(f"{PREFIJO}/auth/logout", headers=cabeceras(cliente))
    assert respuesta.status_code == 204
    assert not cliente.cookies.get("access_token")

    # Acotado a este usuario: la comprobación global fallaba en cuanto otro test
    # dejaba una sesión abierta en la misma base de datos.
    vivos = await sesion_bd.scalar(
        select(RefreshToken.id)
        .join(User, User.id == RefreshToken.user_id)
        .where(User.email == correo, RefreshToken.revoked_at.is_(None))
    )
    assert vivos is None


async def test_logout_all_cierra_todas_las_sesiones(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient]
) -> None:
    correo = await registrar(cliente)
    movil = navegadores()
    await movil.get(f"{PREFIJO}/auth/csrf")
    await movil.post(f"{PREFIJO}/auth/login", json={"email": correo, "password": CONTRASENYA})

    lista = await cliente.get(f"{PREFIJO}/auth/sessions")
    assert lista.json()["total"] == 2

    assert (
        await cliente.post(f"{PREFIJO}/auth/logout-all", headers=cabeceras(cliente))
    ).status_code == 204
    # El otro dispositivo ya no puede refrescar.
    caido = await movil.post(f"{PREFIJO}/auth/refresh", headers=cabeceras(movil))
    assert caido.status_code == 401


async def test_cambio_de_contrasenya_expulsa_las_demas_sesiones(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient]
) -> None:
    correo = await registrar(cliente)
    movil = navegadores()
    await movil.get(f"{PREFIJO}/auth/csrf")
    await movil.post(f"{PREFIJO}/auth/login", json={"email": correo, "password": CONTRASENYA})

    respuesta = await cliente.post(
        f"{PREFIJO}/auth/change-password",
        headers=cabeceras(cliente),
        json={"current_password": CONTRASENYA, "new_password": "OtraClave2026"},
    )
    assert respuesta.status_code == 204
    # La sesión que hizo el cambio sigue viva, con cookies nuevas.
    assert (await cliente.get(f"{PREFIJO}/auth/me")).status_code == 200
    assert (
        await movil.post(f"{PREFIJO}/auth/refresh", headers=cabeceras(movil))
    ).status_code == 401

    with_wrong = await cliente.post(
        f"{PREFIJO}/auth/change-password",
        headers=cabeceras(cliente),
        json={"current_password": CONTRASENYA, "new_password": "TerceraClave3"},
    )
    assert with_wrong.status_code == 401
    assert with_wrong.json()["error"]["codigo"] == "contrasenya_incorrecta"


async def test_sesiones_se_listan_y_se_revocan_una_a_una(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient]
) -> None:
    correo = await registrar(cliente)
    movil = navegadores()
    await movil.get(f"{PREFIJO}/auth/csrf")
    await movil.post(f"{PREFIJO}/auth/login", json={"email": correo, "password": CONTRASENYA})

    lista = (await cliente.get(f"{PREFIJO}/auth/sessions")).json()
    assert lista["total"] == 2
    actual = [s for s in lista["items"] if s["is_current"]]
    otra = [s for s in lista["items"] if not s["is_current"]]
    assert len(actual) == 1 and len(otra) == 1

    borrada = await cliente.delete(
        f"{PREFIJO}/auth/sessions/{otra[0]['id']}", headers=cabeceras(cliente)
    )
    assert borrada.status_code == 204
    assert (
        await movil.post(f"{PREFIJO}/auth/refresh", headers=cabeceras(movil))
    ).status_code == 401

    ajena = await cliente.delete(
        f"{PREFIJO}/auth/sessions/{uuid.uuid4()}", headers=cabeceras(cliente)
    )
    assert ajena.status_code == 404


async def test_sin_cookie_de_acceso_no_hay_datos(cliente: AsyncClient) -> None:
    respuesta = await cliente.get(f"{PREFIJO}/auth/me")
    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["codigo"] == "no_autenticado"


async def test_un_token_de_refresco_no_sirve_como_acceso(cliente: AsyncClient) -> None:
    """RN-03: `decode_token()` comprueba `typ`, así que no se pueden intercambiar."""
    await registrar(cliente)
    refresco = cliente.cookies.get("refresh_token")
    sustituir_cookie(cliente, "access_token", refresco)
    assert (await cliente.get(f"{PREFIJO}/auth/me")).status_code == 401


# --------------------------------------------------------------------------- #
# Perfil, preferencias y puesta en marcha
# --------------------------------------------------------------------------- #


async def test_meta_es_publico(cliente: AsyncClient) -> None:
    respuesta = await cliente.get(f"{PREFIJO}/meta")
    assert respuesta.status_code == 200
    assert respuesta.json()["default_currency"] == "EUR"


async def test_perfil_guarda_idioma_zona_y_tema(cliente: AsyncClient) -> None:
    await registrar(cliente)
    respuesta = await cliente.patch(
        f"{PREFIJO}/users/me",
        headers=cabeceras(cliente),
        json={
            "name": "Ana R.",
            "locale": "gl-ES",
            "timezone": "Atlantic/Canary",
            "theme": "light",
            "currency": "USD",
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert (cuerpo["name"], cuerpo["locale"], cuerpo["theme"]) == ("Ana R.", "gl-ES", "light")
    assert cuerpo["timezone"] == "Atlantic/Canary"
    assert cuerpo["currency"] == "USD"

    # La divisa vive en el hogar, así que «yo» la devuelve ya cambiada.
    assert (await cliente.get(f"{PREFIJO}/users/me")).json()["currency"] == "USD"


async def test_perfil_rechaza_un_correo_de_otro(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient]
) -> None:
    ajeno = await registrar(navegadores())
    await registrar(cliente)
    respuesta = await cliente.patch(
        f"{PREFIJO}/users/me", headers=cabeceras(cliente), json={"email": ajeno}
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["codigo"] == "email_ya_registrado"


async def test_onboarding_se_siembra_y_se_completa(cliente: AsyncClient) -> None:
    await registrar(cliente)
    inicial = (await cliente.get(f"{PREFIJO}/onboarding/status")).json()
    assert inicial == {
        "completed": False,
        "seeded": False,
        "steps": inicial["steps"],
        "next_step": "account",
    }
    assert [p["key"] for p in inicial["steps"]] == [
        "account",
        "categories",
        "income",
        "budget",
        "first_expense",
    ]

    sembrado = await cliente.post(
        f"{PREFIJO}/onboarding/seed",
        headers=cabeceras(cliente),
        json={
            "preset": "es_basico",
            "accounts": [{"name": "Cuenta corriente", "type": "checking"}],
        },
    )
    assert sembrado.status_code == 200, sembrado.text
    assert sembrado.json()["seeded"] is True
    hechos = {p["key"]: p["done"] for p in sembrado.json()["steps"]}
    assert hechos["account"] is True
    assert hechos["categories"] is True

    repetido = await cliente.post(
        f"{PREFIJO}/onboarding/seed", headers=cabeceras(cliente), json={"preset": "es_basico"}
    )
    assert repetido.status_code == 409

    terminado = await cliente.post(f"{PREFIJO}/onboarding/complete", headers=cabeceras(cliente))
    assert terminado.status_code == 200
    assert terminado.json()["completed"] is True
    assert (await cliente.get(f"{PREFIJO}/auth/me")).json()["onboarding_completed"] is True


async def test_borrar_la_cuenta_exige_la_contrasenya(cliente: AsyncClient) -> None:
    await registrar(cliente)
    mal = await cliente.request(
        "DELETE",
        f"{PREFIJO}/users/me",
        headers=cabeceras(cliente),
        json={"password": "Equivocada9"},
    )
    assert mal.status_code == 401
    assert mal.json()["error"]["codigo"] == "contrasenya_incorrecta"

    bien = await cliente.request(
        "DELETE", f"{PREFIJO}/users/me", headers=cabeceras(cliente), json={"password": CONTRASENYA}
    )
    assert bien.status_code == 204
    assert (await cliente.get(f"{PREFIJO}/auth/me")).status_code == 401
