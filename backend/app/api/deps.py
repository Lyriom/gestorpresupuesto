"""Dependencias compartidas por todos los routers.

Aquí vive la puerta de entrada de la seguridad: quién eres, en qué hogar estás y
con qué permiso. Todos los endpoints que tocan datos del usuario dependen de
`AlcanceHogar`, de modo que no haya forma de escribir una consulta que se salte
la tenencia por descuido.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Cookie, Depends, Header, Query, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflicto, NoAutenticado, SinPermiso
from app.core.security import (
    CSRF_COOKIE_NAME,
    TokenError,
    csrf_tokens_match,
    decode_token,
)
from app.db.session import get_session
from app.models.hogar import HouseholdMember
from app.models.usuario import User

COOKIE_ACCESO = "access_token"
COOKIE_REFRESCO = "refresh_token"

Rol = Literal["owner", "editor", "viewer"]

# Quién puede escribir. Un invitado (`viewer`) solo consulta.
ROLES_DE_ESCRITURA: frozenset[str] = frozenset({"owner", "editor"})

Sesion = Annotated[AsyncSession, Depends(get_session)]

METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})


async def verificar_csrf(
    peticion: Request,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE_NAME)] = None,
    csrf_cabecera: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    """Comprueba el doble envío del token CSRF en las peticiones que modifican.

    La sesión viaja en una cookie, así que el navegador la manda también en las
    peticiones que origine otro sitio; lo que ese sitio no puede hacer es leer la
    cookie CSRF para copiarla en la cabecera.
    """
    if peticion.method in METODOS_SEGUROS:
        return
    if not csrf_tokens_match(csrf_cookie, csrf_cabecera):
        raise SinPermiso(
            "La comprobación de seguridad ha fallado. Recarga la página y vuelve a intentarlo.",
            codigo="csrf_invalido",
        )


async def usuario_actual(
    sesion: Sesion,
    access_token: Annotated[str | None, Cookie(alias=COOKIE_ACCESO)] = None,
) -> User:
    """El usuario de la sesión, a partir de la cookie de acceso."""
    if not access_token:
        raise NoAutenticado()

    try:
        claims = decode_token(access_token, "access")
    except TokenError as exc:
        raise NoAutenticado(str(exc)) from exc

    try:
        usuario_id = uuid.UUID(claims["sub"])
    except (ValueError, TypeError) as exc:
        raise NoAutenticado("Token inválido") from exc

    usuario = await sesion.get(User, usuario_id)
    if usuario is None or not usuario.is_active:
        # Mismo mensaje que un token inválido: no se revela si el usuario existe.
        raise NoAutenticado()
    return usuario


UsuarioActual = Annotated[User, Depends(usuario_actual)]


@dataclass(slots=True)
class AlcanceHogar:
    """Identidad ya resuelta: usuario, hogar y rol dentro de ese hogar.

    Los repositorios y servicios reciben esto y filtran por `household_id`. Es la
    primera de las tres capas de tenencia; las otras dos son las claves ajenas
    compuestas del esquema y las políticas de row level security.
    """

    usuario: User
    household_id: uuid.UUID
    rol: str
    sesion: AsyncSession

    @property
    def puede_escribir(self) -> bool:
        return self.rol in ROLES_DE_ESCRITURA

    def exigir_escritura(self) -> None:
        if not self.puede_escribir:
            raise SinPermiso("Tu acceso a este hogar es de solo lectura.")


async def alcance_hogar(
    sesion: Sesion,
    usuario: UsuarioActual,
    hogar: Annotated[
        uuid.UUID | None,
        Query(alias="household_id", description="Hogar sobre el que operar; el suyo por defecto."),
    ] = None,
) -> AlcanceHogar:
    """Resuelve el hogar activo y deja la sesión marcada para el RLS.

    Si no se pide uno concreto se usa el hogar por defecto del usuario. La
    pertenencia se comprueba siempre contra `household_members`, así que pasar el
    identificador de un hogar ajeno da 403, no datos.
    """
    consulta = select(HouseholdMember).where(
        HouseholdMember.user_id == usuario.id,
        HouseholdMember.accepted_at.is_not(None),
    )
    consulta = (
        consulta.where(HouseholdMember.household_id == hogar)
        if hogar is not None
        else consulta.where(HouseholdMember.is_default.is_(True))
    )

    miembro = (await sesion.execute(consulta.limit(1))).scalar_one_or_none()
    if miembro is None:
        if hogar is not None:
            raise SinPermiso("No tienes acceso a este hogar.")
        raise Conflicto(
            "Tu cuenta no tiene ningún hogar activo. Completa la puesta en marcha.",
            codigo="sin_hogar",
        )

    # Tercera capa de tenencia: las políticas de row level security leen esta
    # variable. `set_config(..., true)` la deja atada a la transacción en curso,
    # así que no se filtra a la siguiente petición que reuse la conexión.
    await sesion.execute(
        text("SELECT set_config('app.household_id', :valor, true)"),
        {"valor": str(miembro.household_id)},
    )

    return AlcanceHogar(
        usuario=usuario,
        household_id=miembro.household_id,
        rol=miembro.role,
        sesion=sesion,
    )


Alcance = Annotated[AlcanceHogar, Depends(alcance_hogar)]


async def alcance_escritura(alcance: Alcance) -> AlcanceHogar:
    """Como `Alcance`, pero rechaza a los miembros de solo lectura."""
    alcance.exigir_escritura()
    return alcance


AlcanceEscritura = Annotated[AlcanceHogar, Depends(alcance_escritura)]


@dataclass(slots=True)
class Paginacion:
    """Página solicitada, ya validada."""

    page: int
    size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size


async def paginacion(
    page: Annotated[int, Query(ge=1, le=10_000, description="Página, empezando en 1.")] = 1,
    size: Annotated[int, Query(ge=1, le=200, description="Elementos por página.")] = 50,
) -> Paginacion:
    return Paginacion(page=page, size=size)


PaginacionActual = Annotated[Paginacion, Depends(paginacion)]


def cliente_de(peticion: Request) -> tuple[str | None, str | None]:
    """Dirección IP y agente de usuario, para la lista de sesiones activas.

    Se mira `X-Forwarded-For` porque en EasyPanel la aplicación está detrás de un
    proxy y la IP directa sería siempre la del proxy.
    """
    reenviada = peticion.headers.get("x-forwarded-for")
    ip = reenviada.split(",")[0].strip() if reenviada else None
    if not ip and peticion.client:
        ip = peticion.client.host
    agente = peticion.headers.get("user-agent")
    return ip, (agente[:500] if agente else None)
