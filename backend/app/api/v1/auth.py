"""Identidad y sesión: §2 y §3.1 del contrato.

Todo el ciclo de vida de la sesión vive aquí: alta, login, refresco rotatorio,
cierre, cambio de contraseña y la lista de sesiones activas. Las tres cookies
(`access_token`, `refresh_token`, `csrf_token`) se emiten siempre desde
`_emitir_cookies()`, que es el único sitio del proyecto que decide sus atributos.

Los endpoints públicos (`register`, `login`, `csrf`) no pueden exigir CSRF por
doble envío porque la cookie aún no existe (§1.11); en su lugar comprueban el
origen de la petición.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy import func, select, text

from app.api.deps import (
    COOKIE_ACCESO,
    COOKIE_REFRESCO,
    Alcance,
    AlcanceHogar,
    PaginacionActual,
    Sesion,
    UsuarioActual,
    cliente_de,
    verificar_csrf,
)
from app.core.config import settings
from app.core.errors import (
    Conflicto,
    DemasiadasPeticiones,
    NoAutenticado,
    NoEncontrado,
    SinPermiso,
)
from app.core.security import (
    CSRF_COOKIE_NAME,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_csrf_token,
    hash_password,
    verify_password,
)
from app.models.alerta import Alert
from app.models.categoria import Category
from app.models.cuenta import Account
from app.models.hogar import Household, HouseholdMember
from app.models.usuario import RefreshToken, User
from app.schemas.auth import (
    CambioContrasenyaCrear,
    CsrfRespuesta,
    LoginCrear,
    RefrescoRespuesta,
    RegistroCrear,
    SesionRespuesta,
)
from app.schemas.comun import Pagina
from app.schemas.usuario import UsuarioRespuesta, YoRespuesta
from app.services.presupuesto import Granularidad, periodo_de

logger = logging.getLogger("app.auth")

router = APIRouter(tags=["auth"])

# --- Cookies (§2.1) --------------------------------------------------------- #
# El refresco solo viaja a `/api/v1/auth`: así no aparece en las cientos de
# peticiones normales de la aplicación ni en los logs del proxy.
RUTA_ACCESO = settings.api_prefix
RUTA_REFRESCO = f"{settings.api_prefix}/auth"
RUTA_CSRF = "/"

#: RN-05 y §2.4: cinco fallos consecutivos y espera creciente 1, 2, 4, 8, 15 min.
INTENTOS_ANTES_DE_BLOQUEO = 5
ESPERAS_BLOQUEO_MINUTOS = (1, 2, 4, 8, 15)

MENSAJE_CREDENCIALES = "El correo o la contraseña no son correctos."


# --------------------------------------------------------------------------- #
# Límite de tasa (§2.4)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class _Cubo:
    fichas: float
    visto: float


class LimitadorEnMemoria:
    """Cubo con fichas por clave, en memoria del proceso.

    El despliegue es un único contenedor (§2.4), así que un contador compartido
    en Redis no aportaría nada. Nunca es un punto de fallo: si algo va mal se
    registra y se deja pasar la petición, porque el resto de defensas siguen.
    """

    def __init__(self) -> None:
        self._cubos: dict[str, _Cubo] = {}

    def espera(self, clave: str, limite: int, ventana_segundos: float) -> float | None:
        """Consume una ficha. Devuelve los segundos que faltan si no quedaba."""
        try:
            ahora = time.monotonic()
            ritmo = limite / ventana_segundos
            cubo = self._cubos.get(clave)
            if cubo is None:
                self._cubos[clave] = _Cubo(fichas=limite - 1, visto=ahora)
                return None
            cubo.fichas = min(limite, cubo.fichas + (ahora - cubo.visto) * ritmo)
            cubo.visto = ahora
            if cubo.fichas < 1:
                return (1 - cubo.fichas) / ritmo
            cubo.fichas -= 1
            return None
        except Exception:  # noqa: BLE001 - el limitador no puede tumbar la API
            logger.warning("El limitador de tasa ha fallado; se permite la petición", exc_info=True)
            return None

    def reiniciar(self) -> None:
        """Vacía los cubos. Solo lo usan las pruebas, que comparten proceso."""
        self._cubos.clear()


limitador = LimitadorEnMemoria()


def exigir_cuota(peticion: Request, nombre: str, limite: int, ventana_segundos: float) -> None:
    ip, _ = cliente_de(peticion)
    espera = limitador.espera(f"{nombre}:{ip or 'desconocida'}", limite, ventana_segundos)
    if espera is not None:
        segundos = max(1, round(espera))
        # `Retry-After` es obligatorio en un 429 (§2.4): sin él el cliente no sabe
        # cuánto esperar. `AppError` sí transporta cabeceras.
        raise DemasiadasPeticiones(
            f"Demasiados intentos. Vuelve a probar en {segundos} segundos.",
            cabeceras={"Retry-After": str(segundos)},
        )


# --------------------------------------------------------------------------- #
# Origen de las peticiones públicas (§1.11)
# --------------------------------------------------------------------------- #


def _exigir_origen_propio(peticion: Request) -> None:
    """Sustituto del doble envío en los endpoints que aún no tienen cookie CSRF.

    Sin `Origin` no se rechaza: las peticiones desde un cliente que no es un
    navegador (curl, un script de copia de seguridad) no la envían y tampoco
    están expuestas a CSRF.
    """
    if peticion.headers.get("sec-fetch-site") == "cross-site":
        raise SinPermiso("Petición de origen no permitido.", codigo="csrf_invalido")
    origen = peticion.headers.get("origin")
    if not origen:
        return
    propio = f"{peticion.url.scheme}://{peticion.url.netloc}"
    if origen != propio and origen not in settings.cors_origins:
        raise SinPermiso("Petición de origen no permitido.", codigo="csrf_invalido")


# --------------------------------------------------------------------------- #
# Emisión de cookies
# --------------------------------------------------------------------------- #


def _fijar(
    respuesta: Response, clave: str, valor: str, *, ruta: str, segundos: int, legible: bool = False
) -> None:
    respuesta.set_cookie(
        key=clave,
        value=valor,
        max_age=segundos,
        path=ruta,
        domain=settings.cookie_domain or None,
        secure=settings.cookie_secure,
        httponly=not legible,
        # `Lax` y no `Strict`: con `Strict` entrar desde un enlace externo (el
        # correo del resumen semanal) mostraría el login pese a tener sesión.
        samesite="lax",
    )


def _emitir_cookies(respuesta: Response, usuario: User, jti: uuid.UUID) -> str:
    """Emite las tres cookies de la sesión y devuelve el token CSRF nuevo."""
    vida_refresco = settings.refresh_token_days * 86_400
    csrf = generate_csrf_token()
    _fijar(
        respuesta,
        COOKIE_ACCESO,
        create_access_token(str(usuario.id)),
        ruta=RUTA_ACCESO,
        segundos=settings.access_token_minutes * 60,
    )
    _fijar(
        respuesta,
        COOKIE_REFRESCO,
        create_refresh_token(str(usuario.id), jti=str(jti)),
        ruta=RUTA_REFRESCO,
        segundos=vida_refresco,
    )
    # La única que el JavaScript debe poder leer para copiarla en la cabecera.
    _fijar(respuesta, CSRF_COOKIE_NAME, csrf, ruta=RUTA_CSRF, segundos=vida_refresco, legible=True)
    return csrf


def _borrar_cookies(respuesta: Response) -> None:
    for clave, ruta in (
        (COOKIE_ACCESO, RUTA_ACCESO),
        (COOKIE_REFRESCO, RUTA_REFRESCO),
        (CSRF_COOKIE_NAME, RUTA_CSRF),
    ):
        respuesta.delete_cookie(
            key=clave,
            path=ruta,
            domain=settings.cookie_domain or None,
            secure=settings.cookie_secure,
            httponly=clave != CSRF_COOKIE_NAME,
            samesite="lax",
        )


async def _abrir_sesion(
    sesion: Sesion, usuario: User, peticion: Request, respuesta: Response
) -> datetime:
    """Registra una familia de refresco nueva y emite las cookies."""
    jti = uuid.uuid4()
    expira = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    ip, agente = cliente_de(peticion)
    sesion.add(
        RefreshToken(
            user_id=usuario.id, jti=jti, expires_at=expira, ip_address=ip, user_agent=agente
        )
    )
    _emitir_cookies(respuesta, usuario, jti)
    return expira


# --------------------------------------------------------------------------- #
# Respuestas de usuario
# --------------------------------------------------------------------------- #


async def moneda_del_hogar(sesion: Sesion, usuario: User) -> str:
    """Divisa del hogar por defecto del usuario, o la de la instalación."""
    consulta = (
        select(Household.currency)
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .where(HouseholdMember.user_id == usuario.id, HouseholdMember.is_default.is_(True))
        .limit(1)
    )
    return (await sesion.execute(consulta)).scalar_one_or_none() or settings.default_currency


async def granularidad_del_hogar(sesion: Sesion, usuario: User) -> str:
    """Si el hogar por defecto presupuesta por meses o por semanas."""
    consulta = (
        select(Household.budget_granularity)
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .where(HouseholdMember.user_id == usuario.id, HouseholdMember.is_default.is_(True))
        .limit(1)
    )
    return (await sesion.execute(consulta)).scalar_one_or_none() or Granularidad.MES.value


async def usuario_respuesta(
    sesion: Sesion, usuario: User, moneda: str, granularidad: str = Granularidad.MES.value
) -> UsuarioRespuesta:
    """`UserOut`: el modelo no guarda ni la divisa ni un booleano de onboarding.

    Se refresca la fila antes de leerla porque `updated_at` lleva
    `onupdate=func.now()`: tras un `UPDATE` el ORM la marca como caducada y leerla
    a secas dispararía una consulta perezosa que en asíncrono no se puede esperar.
    """
    await sesion.refresh(usuario)
    return UsuarioRespuesta(
        id=usuario.id,
        created_at=usuario.created_at,
        updated_at=usuario.updated_at,
        email=usuario.email,
        name=usuario.display_name,
        locale=usuario.locale,
        timezone=usuario.timezone,
        currency=moneda,
        budget_granularity=granularidad,
        theme=usuario.theme,
        onboarding_completed=usuario.onboarded_at is not None,
    )


def periodo_actual(zona: str, granularidad: str = Granularidad.MES.value) -> str:
    """El periodo de hoy en la zona del hogar (§1.8): `2026-08` o `2026-W33`.

    Lo calcula el servidor y no la SPA para que las dos vean el mismo «hoy»: el
    navegador está en la zona del portátil y el hogar puede estar en otra, y en la
    frontera de la semana eso son dos periodos distintos.
    """
    try:
        ahora = datetime.now(ZoneInfo(zona))
    except Exception:  # noqa: BLE001 - una zona inválida no debe romper «yo»
        ahora = datetime.now(ZoneInfo(settings.default_timezone))
    return periodo_de(ahora.date(), Granularidad(granularidad))


async def yo_respuesta(alcance: AlcanceHogar) -> YoRespuesta:
    """«Yo» con los contadores que la SPA necesita al arrancar, en una llamada."""
    sesion = alcance.sesion
    hogar = await sesion.get(Household, alcance.household_id)
    cuentas = await sesion.scalar(
        select(func.count())
        .select_from(Account)
        .where(Account.household_id == alcance.household_id, Account.archived_at.is_(None))
    )
    tematicas = await sesion.scalar(
        select(func.count())
        .select_from(Category)
        .where(
            Category.household_id == alcance.household_id,
            Category.archived_at.is_(None),
            Category.merged_into_id.is_(None),
        )
    )
    avisos = await sesion.scalar(
        select(func.count())
        .select_from(Alert)
        .where(
            Alert.household_id == alcance.household_id,
            Alert.read_at.is_(None),
            Alert.dismissed_at.is_(None),
        )
    )
    zona = hogar.timezone if hogar else alcance.usuario.timezone
    granularidad = hogar.budget_granularity if hogar else Granularidad.MES.value
    base = await usuario_respuesta(
        sesion,
        alcance.usuario,
        hogar.currency if hogar else settings.default_currency,
        granularidad,
    )
    return YoRespuesta(
        **base.model_dump(),
        accounts_count=cuentas or 0,
        categories_count=tematicas or 0,
        unread_alerts=avisos or 0,
        current_period=periodo_actual(zona, granularidad),
        session_expires_at=datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes),
    )


# --------------------------------------------------------------------------- #
# Bloqueo por credencial (§2.4)
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _hash_senyuelo() -> str:
    """Hash contra el que verificar cuando el correo no existe.

    Sin él, un correo desconocido responde sin pagar los ~250 ms de bcrypt y el
    tiempo de respuesta revela qué direcciones están registradas.
    """
    return hash_password("senyuelo-de-tiempo-constante-0123456789")


def _espera_de_bloqueo(fallos: int) -> timedelta:
    indice = min(fallos - INTENTOS_ANTES_DE_BLOQUEO, len(ESPERAS_BLOQUEO_MINUTOS) - 1)
    return timedelta(minutes=ESPERAS_BLOQUEO_MINUTOS[max(0, indice)])


def _bloqueado(usuario: User) -> bool:
    return usuario.locked_until is not None and usuario.locked_until > datetime.now(UTC)


def _segundos_de_bloqueo(usuario: User) -> int:
    """Lo que le queda de bloqueo, para el `Retry-After` del 429."""
    if usuario.locked_until is None:
        return 1
    return max(1, round((usuario.locked_until - datetime.now(UTC)).total_seconds()))


async def _anotar_fallo(sesion: Sesion, usuario: User) -> None:
    usuario.failed_login_count += 1
    if usuario.failed_login_count >= INTENTOS_ANTES_DE_BLOQUEO:
        usuario.locked_until = datetime.now(UTC) + _espera_de_bloqueo(usuario.failed_login_count)
    await sesion.commit()


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.get("/auth/csrf", response_model=CsrfRespuesta, summary="Emitir la cookie CSRF")
async def csrf(
    peticion: Request,
    respuesta: Response,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE_NAME)] = None,
) -> CsrfRespuesta:
    """Devuelve el token CSRF, creándolo si la cookie aún no existía."""
    exigir_cuota(peticion, "csrf", 120, 60)
    valor = csrf_cookie or generate_csrf_token()
    if not csrf_cookie:
        _fijar(
            respuesta,
            CSRF_COOKIE_NAME,
            valor,
            ruta=RUTA_CSRF,
            segundos=settings.refresh_token_days * 86_400,
            legible=True,
        )
    return CsrfRespuesta(csrf_token=valor)


@router.post(
    "/auth/register",
    response_model=UsuarioRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar usuario",
)
async def registrar(
    datos: RegistroCrear, peticion: Request, respuesta: Response, sesion: Sesion
) -> UsuarioRespuesta:
    """Alta del usuario con su hogar y su pertenencia `owner` (RN-06)."""
    _exigir_origen_propio(peticion)
    exigir_cuota(peticion, "register", 5, 3_600)

    hay_usuarios = bool(await sesion.scalar(select(func.count()).select_from(User)))
    if not settings.allow_registration and hay_usuarios:
        raise SinPermiso(
            "El registro de nuevos usuarios está deshabilitado en esta instalación.",
            codigo="registro_deshabilitado",
        )

    existe = await sesion.scalar(
        select(func.count()).select_from(User).where(func.lower(User.email) == datos.email)
    )
    if existe:
        raise Conflicto("Ya existe una cuenta con ese correo.", codigo="email_ya_registrado")

    ahora = datetime.now(UTC)
    usuario = User(
        email=datos.email,
        password_hash=hash_password(datos.password),
        display_name=datos.name,
        locale=settings.default_locale,
        timezone=settings.default_timezone,
        password_changed_at=ahora,
        # El primer usuario de una instalación self-hosted es su administrador.
        is_admin=not hay_usuarios,
    )
    sesion.add(usuario)
    await sesion.flush()

    hogar = Household(
        name=f"Hogar de {datos.name}",
        currency=settings.default_currency,
        locale=settings.default_locale,
        timezone=settings.default_timezone,
        created_by_id=usuario.id,
    )
    sesion.add(hogar)
    await sesion.flush()
    sesion.add(
        HouseholdMember(
            household_id=hogar.id,
            user_id=usuario.id,
            role="owner",
            is_default=True,
            accepted_at=ahora,
        )
    )

    await _abrir_sesion(sesion, usuario, peticion, respuesta)
    await sesion.commit()
    return await usuario_respuesta(sesion, usuario, hogar.currency, hogar.budget_granularity)


@router.post("/auth/login", response_model=UsuarioRespuesta, summary="Iniciar sesión")
async def login(
    datos: LoginCrear, peticion: Request, respuesta: Response, sesion: Sesion
) -> UsuarioRespuesta:
    """Comprueba las credenciales y emite las tres cookies.

    Correo inexistente y contraseña equivocada dan exactamente la misma respuesta
    y tardan lo mismo: el hash señuelo evita el oráculo por tiempo (§2.4).
    """
    _exigir_origen_propio(peticion)
    exigir_cuota(peticion, "login", 10, 60)

    usuario = (
        await sesion.execute(select(User).where(func.lower(User.email) == datos.email).limit(1))
    ).scalar_one_or_none()

    if usuario is None:
        verify_password(datos.password, _hash_senyuelo())
        raise NoAutenticado(MENSAJE_CREDENCIALES, codigo="credenciales_invalidas")

    if _bloqueado(usuario):
        # El mensaje es el genérico: no dice si el correo existe (§2.4).
        raise DemasiadasPeticiones(cabeceras={"Retry-After": str(_segundos_de_bloqueo(usuario))})

    if not verify_password(datos.password, usuario.password_hash) or not usuario.is_active:
        await _anotar_fallo(sesion, usuario)
        raise NoAutenticado(MENSAJE_CREDENCIALES, codigo="credenciales_invalidas")

    usuario.failed_login_count = 0
    usuario.locked_until = None
    usuario.last_login_at = datetime.now(UTC)
    await _abrir_sesion(sesion, usuario, peticion, respuesta)
    await sesion.commit()
    return await usuario_respuesta(
        sesion,
        usuario,
        await moneda_del_hogar(sesion, usuario),
        await granularidad_del_hogar(sesion, usuario),
    )


async def _revocar_familia(sesion: Sesion, token_id: uuid.UUID) -> None:
    """Revoca la cadena de rotación completa a la que pertenece un token.

    Se recorre `replaced_by_id` en los dos sentidos: un `jti` reutilizado puede
    ser cualquier eslabón, y lo que hay que invalidar es la sesión entera.
    """
    await sesion.execute(
        text(
            """
            WITH RECURSIVE familia AS (
                SELECT id, replaced_by_id FROM refresh_tokens WHERE id = :id
                UNION
                SELECT r.id, r.replaced_by_id
                  FROM refresh_tokens r
                  JOIN familia f ON r.id = f.replaced_by_id OR r.replaced_by_id = f.id
            )
            UPDATE refresh_tokens SET revoked_at = now()
             WHERE id IN (SELECT id FROM familia) AND revoked_at IS NULL
            """
        ),
        {"id": token_id},
    )


@router.post(
    "/auth/refresh",
    response_model=RefrescoRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Renovar la sesión rotando el refresco",
)
async def refrescar(
    peticion: Request,
    respuesta: Response,
    sesion: Sesion,
    refresh_token: Annotated[str | None, Cookie(alias=COOKIE_REFRESCO)] = None,
) -> RefrescoRespuesta:
    """RN-04: el refresco es de un solo uso; reutilizarlo revoca la familia."""
    exigir_cuota(peticion, "refresh", 60, 3_600)
    expirada = NoAutenticado(
        "Tu sesión ha caducado. Vuelve a iniciar sesión.", codigo="sesion_expirada"
    )

    if not refresh_token:
        _borrar_cookies(respuesta)
        raise expirada
    try:
        claims = decode_token(refresh_token, "refresh")
        jti = uuid.UUID(claims["jti"])
    except (TokenError, KeyError, TypeError, ValueError):
        _borrar_cookies(respuesta)
        raise expirada from None

    fila = (
        await sesion.execute(select(RefreshToken).where(RefreshToken.jti == jti).limit(1))
    ).scalar_one_or_none()
    if fila is None:
        _borrar_cookies(respuesta)
        raise expirada

    if fila.revoked_at is not None:
        # Un `jti` ya consumido solo puede llegar de una copia robada.
        await _revocar_familia(sesion, fila.id)
        await sesion.commit()
        _borrar_cookies(respuesta)
        raise expirada

    usuario = await sesion.get(User, fila.user_id)
    if fila.expires_at <= datetime.now(UTC) or usuario is None or not usuario.is_active:
        _borrar_cookies(respuesta)
        raise expirada

    ip, agente = cliente_de(peticion)
    nuevo = RefreshToken(
        id=uuid.uuid4(),
        user_id=usuario.id,
        jti=uuid.uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        ip_address=ip,
        user_agent=agente,
    )
    sesion.add(nuevo)
    # El eslabón nuevo tiene que existir en la tabla antes de que el viejo le
    # apunte: en un mismo `flush` el ORM emite los UPDATE antes que los INSERT.
    await sesion.flush()
    fila.revoked_at = datetime.now(UTC)
    fila.replaced_by_id = nuevo.id
    _emitir_cookies(respuesta, usuario, nuevo.jti)
    await sesion.commit()
    return RefrescoRespuesta(expires_at=nuevo.expires_at)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verificar_csrf)],
    summary="Cerrar la sesión actual",
)
async def logout(
    respuesta: Response,
    sesion: Sesion,
    refresh_token: Annotated[str | None, Cookie(alias=COOKIE_REFRESCO)] = None,
) -> None:
    """Revoca el `jti` actual y borra las tres cookies. Nunca falla."""
    if refresh_token:
        try:
            jti = uuid.UUID(decode_token(refresh_token, "refresh")["jti"])
        except (TokenError, KeyError, TypeError, ValueError):
            jti = None
        if jti is not None:
            await sesion.execute(
                text(
                    "UPDATE refresh_tokens SET revoked_at = now() "
                    "WHERE jti = :jti AND revoked_at IS NULL"
                ),
                {"jti": jti},
            )
            await sesion.commit()
    _borrar_cookies(respuesta)


@router.post(
    "/auth/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verificar_csrf)],
    summary="Cerrar todas las sesiones",
)
async def logout_de_todas(respuesta: Response, sesion: Sesion, usuario: UsuarioActual) -> None:
    """Revoca todas las familias del usuario, incluida la que hace la petición."""
    await sesion.execute(
        text(
            "UPDATE refresh_tokens SET revoked_at = now() "
            "WHERE user_id = :usuario AND revoked_at IS NULL"
        ),
        {"usuario": usuario.id},
    )
    await sesion.commit()
    _borrar_cookies(respuesta)


@router.post(
    "/auth/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verificar_csrf)],
    summary="Cambiar la contraseña",
)
async def cambiar_contrasenya(
    datos: CambioContrasenyaCrear,
    peticion: Request,
    respuesta: Response,
    sesion: Sesion,
    usuario: UsuarioActual,
) -> None:
    """Revoca las demás sesiones y reemite la actual con cookies nuevas."""
    exigir_cuota(peticion, f"change-password:{usuario.id}", 10, 3_600)
    if not verify_password(datos.current_password, usuario.password_hash):
        raise NoAutenticado("La contraseña actual no es correcta.", codigo="contrasenya_incorrecta")

    usuario.password_hash = hash_password(datos.new_password)
    usuario.password_changed_at = datetime.now(UTC)
    usuario.must_change_password = False
    # Cambiar la contraseña expulsa cualquier sesión abierta con la anterior.
    await sesion.execute(
        text(
            "UPDATE refresh_tokens SET revoked_at = now() "
            "WHERE user_id = :usuario AND revoked_at IS NULL"
        ),
        {"usuario": usuario.id},
    )
    await _abrir_sesion(sesion, usuario, peticion, respuesta)
    await sesion.commit()


@router.get("/auth/me", response_model=YoRespuesta, summary="Usuario de la sesión")
async def yo(alcance: Alcance) -> YoRespuesta:
    return await yo_respuesta(alcance)


def _pista_de_ip(ip: object | None) -> str | None:
    """IP truncada para la lista de dispositivos. Nunca la completa (§9).

    La columna es `INET`, así que asyncpg devuelve un `IPv4Address`, no una cadena.
    """
    if not ip:
        return None
    texto = str(ip)
    if ":" in texto:
        return ":".join(texto.split(":")[:4]) + "::x"
    partes = texto.split(".")
    return ".".join([*partes[:3], "x"]) if len(partes) == 4 else None


@router.get("/auth/sessions", response_model=Pagina[SesionRespuesta], summary="Sesiones activas")
async def sesiones(
    sesion: Sesion,
    usuario: UsuarioActual,
    paginacion: PaginacionActual,
    refresh_token: Annotated[str | None, Cookie(alias=COOKIE_REFRESCO)] = None,
) -> Pagina[SesionRespuesta]:
    """Familias de refresco vivas, para «cerrar sesión en el otro dispositivo»."""
    jti_actual: uuid.UUID | None = None
    if refresh_token:
        try:
            jti_actual = uuid.UUID(decode_token(refresh_token, "refresh")["jti"])
        except (TokenError, KeyError, TypeError, ValueError):
            jti_actual = None

    condiciones = (
        RefreshToken.user_id == usuario.id,
        RefreshToken.revoked_at.is_(None),
        RefreshToken.expires_at > datetime.now(UTC),
    )
    total = await sesion.scalar(select(func.count()).select_from(RefreshToken).where(*condiciones))
    filas = (
        (
            await sesion.execute(
                select(RefreshToken)
                .where(*condiciones)
                .order_by(RefreshToken.issued_at.desc(), RefreshToken.id.desc())
                .offset(paginacion.offset)
                .limit(paginacion.limit)
            )
        )
        .scalars()
        .all()
    )
    return Pagina.crear(
        [
            SesionRespuesta(
                id=fila.id,
                created_at=fila.issued_at,
                # No hay columna de «último uso»: la rotación crea una fila nueva,
                # así que `updated_at` es la mejor aproximación disponible.
                last_used_at=fila.updated_at,
                expires_at=fila.expires_at,
                user_agent=fila.user_agent,
                ip_hint=_pista_de_ip(fila.ip_address),
                is_current=fila.jti == jti_actual,
            )
            for fila in filas
        ],
        page=paginacion.page,
        size=paginacion.size,
        total=total or 0,
    )


@router.delete(
    "/auth/sessions/{sesion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verificar_csrf)],
    summary="Revocar una sesión",
)
async def revocar_sesion(sesion_id: uuid.UUID, sesion: Sesion, usuario: UsuarioActual) -> None:
    """RN-02: una sesión de otro usuario da 404, no 403."""
    fila = (
        await sesion.execute(
            select(RefreshToken)
            .where(RefreshToken.id == sesion_id, RefreshToken.user_id == usuario.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa sesión no existe.")
    await _revocar_familia(sesion, fila.id)
    await sesion.commit()
