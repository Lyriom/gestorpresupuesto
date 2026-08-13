"""Perfil, preferencias, metadatos públicos y puesta en marcha: §3.2 del contrato.

Las preferencias personales (idioma, zona horaria, tema) viven en `users`; la
divisa es del **hogar**, porque es la unidad de la que se informa. El estado de la
puesta en marcha (F-50) se deriva de los datos que ya hay: `onboarded_at` solo
guarda «el usuario dijo que había terminado», no la lista de pasos, que se
recalcula en cada consulta y así nunca miente.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select

from app.api.deps import (
    Alcance,
    AlcanceHogar,
    Sesion,
    UsuarioActual,
    verificar_csrf,
)
from app.api.v1.auth import (
    exigir_cuota,
    moneda_del_hogar,
    usuario_respuesta,
    yo_respuesta,
)
from app.api.v1.cuentas import crear_cuenta_en_hogar
from app.core.config import settings
from app.core.errors import Conflicto, NoAutenticado, SinPermiso
from app.core.security import verify_password
from app.db.semillas import copiar_plantillas_a_hogar
from app.models.categoria import Category
from app.models.cuenta import Account
from app.models.hogar import Household, HouseholdMember
from app.models.presupuesto import BudgetAllocation, BudgetPeriod
from app.models.transaccion import Transaction
from app.models.usuario import User
from app.schemas.auth import ConfirmarContrasenyaCrear
from app.schemas.usuario import (
    MetaRespuesta,
    OnboardingRespuesta,
    OnboardingSembrarCrear,
    PasoOnboardingRespuesta,
    UsuarioActualizar,
    UsuarioRespuesta,
    YoRespuesta,
)

router = APIRouter(tags=["users"])

#: Los cinco pasos del asistente inicial, en el orden en que se muestran (F-50).
ETIQUETAS_PASOS: tuple[tuple[str, str, bool], ...] = (
    ("account", "Crea tu primera cuenta", False),
    ("categories", "Revisa tus temáticas", False),
    ("income", "Indica tus ingresos del mes", False),
    ("budget", "Reparte el presupuesto", False),
    ("first_expense", "Anota tu primer gasto", True),
)


@router.get("/users/me", response_model=YoRespuesta, summary="Perfil de la sesión")
async def perfil(alcance: Alcance) -> YoRespuesta:
    """Alias de `/auth/me`, por coherencia REST."""
    return await yo_respuesta(alcance)


@router.patch(
    "/users/me",
    response_model=UsuarioRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Cambiar perfil y preferencias",
)
async def editar_perfil(
    datos: UsuarioActualizar, sesion: Sesion, usuario: UsuarioActual
) -> UsuarioRespuesta:
    """Nombre, correo, idioma, zona horaria, tema y divisa del hogar."""
    cambios = datos.model_dump(exclude_unset=True)

    if "email" in cambios and cambios["email"] and cambios["email"] != usuario.email.lower():
        repetido = await sesion.scalar(
            select(func.count())
            .select_from(User)
            .where(func.lower(User.email) == cambios["email"], User.id != usuario.id)
        )
        if repetido:
            raise Conflicto("Ya existe una cuenta con ese correo.", codigo="email_ya_registrado")
        usuario.email = cambios["email"]

    if cambios.get("name"):
        usuario.display_name = cambios["name"]
    for campo in ("locale", "timezone"):
        if cambios.get(campo):
            setattr(usuario, campo, cambios[campo])
    if cambios.get("theme"):
        usuario.theme = str(cambios["theme"])

    moneda = await moneda_del_hogar(sesion, usuario)
    if cambios.get("currency"):
        moneda = await _cambiar_divisa_del_hogar(sesion, usuario, cambios["currency"])

    await sesion.commit()
    return await usuario_respuesta(sesion, usuario, moneda)


async def _cambiar_divisa_del_hogar(sesion: Sesion, usuario: User, moneda: str) -> str:
    """La divisa es del hogar, así que solo la toca quien puede escribir en él."""
    miembro = (
        await sesion.execute(
            select(HouseholdMember)
            .where(
                HouseholdMember.user_id == usuario.id,
                HouseholdMember.is_default.is_(True),
                HouseholdMember.accepted_at.is_not(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if miembro is None:
        raise Conflicto(
            "Tu cuenta no tiene ningún hogar activo. Completa la puesta en marcha.",
            codigo="sin_hogar",
        )
    if miembro.role not in ("owner", "editor"):
        raise SinPermiso("Tu acceso a este hogar es de solo lectura.")
    hogar = await sesion.get(Household, miembro.household_id)
    if hogar is not None:
        hogar.currency = moneda
    return moneda


@router.delete(
    "/users/me",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verificar_csrf)],
    summary="Borrar la cuenta y todos sus datos",
)
async def borrar_cuenta(
    datos: ConfirmarContrasenyaCrear,
    peticion: Request,
    sesion: Sesion,
    usuario: UsuarioActual,
) -> None:
    """Irreversible: exige la contraseña y arrastra los hogares sin nadie más."""
    exigir_cuota(peticion, f"delete-account:{usuario.id}", 3, 3_600)
    if not verify_password(datos.password, usuario.password_hash):
        raise NoAutenticado("La contraseña no es correcta.", codigo="contrasenya_incorrecta")

    pertenencias = (
        (await sesion.execute(select(HouseholdMember).where(HouseholdMember.user_id == usuario.id)))
        .scalars()
        .all()
    )
    for pertenencia in pertenencias:
        companyeros = await sesion.scalar(
            select(func.count())
            .select_from(HouseholdMember)
            .where(
                HouseholdMember.household_id == pertenencia.household_id,
                HouseholdMember.user_id != usuario.id,
            )
        )
        if companyeros:
            # El hogar sigue vivo para el resto: solo se va este miembro.
            await sesion.delete(pertenencia)
            continue
        hogar = await sesion.get(Household, pertenencia.household_id)
        if hogar is not None:
            # Borrar el hogar arrastra en cascada todas sus tablas de dominio.
            await sesion.delete(hogar)

    await sesion.delete(usuario)
    await sesion.commit()


@router.get("/meta", response_model=MetaRespuesta, summary="Metadatos públicos")
async def meta(peticion: Request, sesion: Sesion) -> MetaRespuesta:
    """Lo que se puede saber sin sesión, para pintar la pantalla de entrada."""
    exigir_cuota(peticion, "meta", 120, 60)
    hay_usuarios = bool(await sesion.scalar(select(func.count()).select_from(User)))
    return MetaRespuesta(
        app_name=settings.app_name,
        # RN-06: en el primer arranque el registro está abierto aunque la
        # configuración lo cierre, o la instalación no se podría estrenar.
        allow_registration=settings.allow_registration or not hay_usuarios,
        first_run=not hay_usuarios,
        default_currency=settings.default_currency,
        default_locale=settings.default_locale,
        max_upload_mb=settings.max_upload_mb,
        max_pdf_pages=settings.max_pdf_pages,
        ocr_enabled=settings.ocr_enabled,
    )


async def _estado_onboarding(alcance: AlcanceHogar) -> OnboardingRespuesta:
    """Recalcula los cinco pasos mirando los datos, no una bandera guardada."""
    sesion = alcance.sesion
    hogar = alcance.household_id

    async def cuantos(consulta) -> int:  # noqa: ANN001 - select() no tiene tipo público estable
        return await sesion.scalar(consulta) or 0

    cuentas = await cuantos(
        select(func.count()).select_from(Account).where(Account.household_id == hogar)
    )
    tematicas = await cuantos(
        select(func.count())
        .select_from(Category)
        .where(Category.household_id == hogar, Category.merged_into_id.is_(None))
    )
    ingresos = await cuantos(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.household_id == hogar, Transaction.kind == "income")
    )
    ingresos += await cuantos(
        select(func.count())
        .select_from(BudgetPeriod)
        .where(BudgetPeriod.household_id == hogar, BudgetPeriod.expected_income.is_not(None))
    )
    asignaciones = await cuantos(
        select(func.count())
        .select_from(BudgetAllocation)
        .where(BudgetAllocation.household_id == hogar)
    )
    gastos = await cuantos(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.household_id == hogar, Transaction.kind == "expense")
    )

    hechos = {
        "account": cuentas > 0,
        "categories": tematicas > 0,
        "income": ingresos > 0,
        "budget": asignaciones > 0,
        "first_expense": gastos > 0,
    }
    pasos = [
        PasoOnboardingRespuesta(key=clave, label=etiqueta, done=hechos[clave], optional=opcional)
        for clave, etiqueta, opcional in ETIQUETAS_PASOS
    ]
    siguiente = next((p.key for p in pasos if not p.done and not p.optional), None)
    return OnboardingRespuesta(
        completed=alcance.usuario.onboarded_at is not None,
        seeded=tematicas > 0,
        steps=pasos,
        next_step=siguiente,
    )


@router.get(
    "/onboarding/status",
    response_model=OnboardingRespuesta,
    summary="Estado de la puesta en marcha",
)
async def estado_onboarding(alcance: Alcance) -> OnboardingRespuesta:
    return await _estado_onboarding(alcance)


@router.post(
    "/onboarding/seed",
    response_model=OnboardingRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Sembrar temáticas y cuentas iniciales",
)
async def sembrar_onboarding(
    datos: OnboardingSembrarCrear, alcance: Alcance
) -> OnboardingRespuesta:
    """Copia el árbol de temáticas por defecto y crea las cuentas indicadas.

    El catálogo de `category_templates` tiene una sola variante marcada como
    `is_default`, así que los tres presets siembran el mismo árbol; `preset` se
    acepta ya para cuando el catálogo tenga más de una.
    """
    alcance.exigir_escritura()
    sesion = alcance.sesion
    ya_hay = await sesion.scalar(
        select(func.count())
        .select_from(Category)
        .where(Category.household_id == alcance.household_id)
    )
    if ya_hay:
        raise Conflicto("Este hogar ya tiene temáticas. No se vuelve a sembrar.")

    await copiar_plantillas_a_hogar(sesion, alcance.household_id)
    for cuenta in datos.accounts:
        await crear_cuenta_en_hogar(alcance, cuenta)
    await sesion.commit()
    return await _estado_onboarding(alcance)


@router.post(
    "/onboarding/complete",
    response_model=OnboardingRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Marcar la puesta en marcha como terminada",
)
async def completar_onboarding(alcance: Alcance) -> OnboardingRespuesta:
    """Idempotente: repetirlo no mueve la fecha ya guardada."""
    if alcance.usuario.onboarded_at is None:
        alcance.usuario.onboarded_at = datetime.now(UTC)
        await alcance.sesion.commit()
    return await _estado_onboarding(alcance)


# Se exporta para los tests y para el agregador: el identificador del hogar por
# defecto es lo único que un cliente necesita saber del concepto «hogar» hoy.
async def hogar_por_defecto(sesion: Sesion, usuario: User) -> uuid.UUID | None:
    return (
        await sesion.execute(
            select(HouseholdMember.household_id)
            .where(
                HouseholdMember.user_id == usuario.id,
                HouseholdMember.is_default.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
