"""Ajustes del hogar, vistas guardadas, almacenamiento y exportación.

§3.18, §3.20 y §4.13 del contrato. Aquí vive también «tus datos son tuyos»
(F-43): la exportación completa de todo lo del hogar en JSON o CSV.

Nota de contrato: el esquema `AjustesRespuesta` pide cuatro preferencias para las
que el modelo no tiene columna (`first_day_of_week`, `duplicate_window_days`,
`product_match_threshold` y la periodicidad del digest, más las preferencias de
aviso por tipo). En lugar de inventarme una migración —el modelo no es mío— se
guardan en una fila de `saved_views` reservada, que es el único almacén
clave-valor por usuario y hogar que ya existe. Todo lo demás sale de
`households` y de `users`, que son su sitio natural.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid as uuidlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, verificar_csrf
from app.api.v1.productos import ahora, cargado
from app.core.config import settings
from app.core.errors import Conflicto, NoEncontrado, ReglaDeNegocio
from app.models.alerta import Alert
from app.models.categoria import Category
from app.models.comercio import Payee
from app.models.cuenta import Account
from app.models.factura import Invoice, InvoiceLine
from app.models.hogar import Household
from app.models.presupuesto import BudgetAllocation, BudgetPeriod
from app.models.producto import Product, ProductAlias, ProductPrice
from app.models.sistema import DataExport, SavedView
from app.models.transaccion import Attachment, Transaction, TransactionSplit
from app.schemas.ajustes import (
    AjustesActualizar,
    AjustesRespuesta,
    AlmacenamientoRespuesta,
    AmbitoExportacion,
    ArrastreNegativo,
    EstadoExportacion,
    ExportacionCrear,
    ExportacionRespuesta,
    FormatoExportacion,
    NotificacionesRespuesta,
    NotificacionesSustituirCrear,
    PeriodicidadDigest,
    PreferenciaAvisoRespuesta,
    VistaGuardadaActualizar,
    VistaGuardadaCrear,
    VistaGuardadaRespuesta,
)
from app.schemas.alerta import Severidad, TipoAlerta
from app.schemas.comun import Pagina
from app.schemas.usuario import Tema

router = APIRouter(dependencies=[Depends(verificar_csrf)])

#: Nombre de la fila de `saved_views` que hace de almacén de preferencias.
FILA_PREFERENCIAS = "__preferencias__"

#: Valores por defecto de las preferencias que no tienen columna propia.
PREFERENCIAS_POR_DEFECTO: dict[str, Any] = {
    "first_day_of_week": 1,  # lunes, como en España
    "duplicate_window_days": 3,
    "product_match_threshold": 88.0,
    "digest": PeriodicidadDigest.WEEKLY.value,
    "digest_weekday": 0,
    "digest_day_of_month": 1,
    "notifications": [],
    "last_digest_at": None,
}

#: Las exportaciones caducan a los 7 días (F-43).
DIAS_DE_CADUCIDAD = 7


# --------------------------------------------------------------------------- #
# Almacén de preferencias
# --------------------------------------------------------------------------- #


async def _preferencias(alcance: AlcanceHogar) -> SavedView:
    """La fila reservada de preferencias, creándola la primera vez."""
    fila = (
        await alcance.sesion.execute(
            select(SavedView).where(
                SavedView.household_id == alcance.household_id,
                SavedView.user_id == alcance.usuario.id,
                SavedView.name == FILA_PREFERENCIAS,
            )
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = SavedView(
            household_id=alcance.household_id,
            user_id=alcance.usuario.id,
            entity="transactions",
            name=FILA_PREFERENCIAS,
            filters=dict(PREFERENCIAS_POR_DEFECTO),
        )
        alcance.sesion.add(fila)
        await alcance.sesion.flush()
    return fila


def _valor(fila: SavedView, clave: str) -> Any:
    return (fila.filters or {}).get(clave, PREFERENCIAS_POR_DEFECTO[clave])


# --------------------------------------------------------------------------- #
# Ajustes
# --------------------------------------------------------------------------- #


def _respuesta_ajustes(hogar: Household, tema: str, preferencias: SavedView) -> AjustesRespuesta:
    arrastre = hogar.default_rollover_mode
    return AjustesRespuesta(
        currency=hogar.currency,
        budget_granularity=hogar.budget_granularity,
        locale=hogar.locale,
        timezone=hogar.timezone,
        first_day_of_week=int(_valor(preferencias, "first_day_of_week")),
        theme=Tema(tema),
        rollover_default=arrastre != "none",
        rollover_negative=(
            ArrastreNegativo.CARRY if arrastre == "carry_negative" else ArrastreNegativo.RESET
        ),
        budget_alert_pct=float(hogar.near_limit_pct / 100),
        price_increase_pct=float(hogar.price_alert_pct),
        anomaly_z=float(hogar.unusual_expense_sigma),
        duplicate_window_days=int(_valor(preferencias, "duplicate_window_days")),
        product_match_threshold=float(_valor(preferencias, "product_match_threshold")),
        digest=PeriodicidadDigest(_valor(preferencias, "digest")),
    )


@router.get("/settings", tags=["settings"], summary="Ajustes del hogar")
async def ajustes(alcance: Alcance) -> AjustesRespuesta:
    hogar = await alcance.sesion.get(Household, alcance.household_id)
    assert hogar is not None  # noqa: S101 - el alcance ya lo ha resuelto
    preferencias = await _preferencias(alcance)
    await alcance.sesion.commit()
    return _respuesta_ajustes(hogar, alcance.usuario.theme, preferencias)


@router.patch("/settings", tags=["settings"], summary="Cambia los ajustes")
async def actualizar_ajustes(
    alcance: AlcanceEscritura, datos: AjustesActualizar
) -> AjustesRespuesta:
    """Cambiar un umbral deja las alertas abiertas listas para recalcular (RN-71)."""
    hogar = await alcance.sesion.get(Household, alcance.household_id)
    assert hogar is not None  # noqa: S101
    preferencias = await _preferencias(alcance)
    campos = datos.model_dump(exclude_unset=True)
    guardadas = dict(preferencias.filters or PREFERENCIAS_POR_DEFECTO)

    for entrada, columna in (
        ("currency", "currency"),
        ("locale", "locale"),
        ("timezone", "timezone"),
        ("budget_granularity", "budget_granularity"),
    ):
        if entrada in campos and campos[entrada] is not None:
            setattr(hogar, columna, campos[entrada])
    if campos.get("budget_alert_pct") is not None:
        hogar.near_limit_pct = (Decimal(str(campos["budget_alert_pct"])) * 100).quantize(
            Decimal("0.01")
        )
    if campos.get("price_increase_pct") is not None:
        hogar.price_alert_pct = Decimal(str(campos["price_increase_pct"])).quantize(Decimal("0.01"))
    if campos.get("anomaly_z") is not None:
        hogar.unusual_expense_sigma = Decimal(str(campos["anomaly_z"])).quantize(Decimal("0.01"))
    if "rollover_default" in campos or "rollover_negative" in campos:
        activo = campos.get("rollover_default", hogar.default_rollover_mode != "none")
        negativo = campos.get(
            "rollover_negative",
            ArrastreNegativo.CARRY
            if hogar.default_rollover_mode == "carry_negative"
            else ArrastreNegativo.RESET,
        )
        if not activo:
            hogar.default_rollover_mode = "none"
        else:
            hogar.default_rollover_mode = (
                "carry_negative" if negativo == ArrastreNegativo.CARRY else "carry"
            )
    if campos.get("theme") is not None:
        alcance.usuario.theme = campos["theme"].value

    for clave in ("first_day_of_week", "duplicate_window_days", "product_match_threshold"):
        if campos.get(clave) is not None:
            guardadas[clave] = campos[clave]
    if campos.get("digest") is not None:
        guardadas["digest"] = campos["digest"].value
    preferencias.filters = guardadas

    if campos.get("price_increase_pct") is not None or campos.get("budget_alert_pct") is not None:
        # Un umbral nuevo invalida lo ya avisado: se reabre para el recálculo.
        await alcance.sesion.execute(
            update(Alert)
            .where(
                Alert.household_id == alcance.household_id,
                Alert.status == "resolved",
                Alert.type.in_(("budget_overspend", "budget_near_limit", "product_price_increase")),
            )
            .values(resolved_at=None, status="new")
        )
    await alcance.sesion.commit()
    return _respuesta_ajustes(hogar, alcance.usuario.theme, preferencias)


# --------------------------------------------------------------------------- #
# Preferencias de aviso
# --------------------------------------------------------------------------- #


def _respuesta_notificaciones(preferencias: SavedView) -> NotificacionesRespuesta:
    guardadas = _valor(preferencias, "notifications") or []
    ultimo = _valor(preferencias, "last_digest_at")
    return NotificacionesRespuesta(
        items=[
            PreferenciaAvisoRespuesta(
                type=TipoAlerta(item["type"]),
                enabled=bool(item.get("enabled", True)),
                min_severity=Severidad(item.get("min_severity", Severidad.INFO.value)),
                in_digest=bool(item.get("in_digest", True)),
            )
            for item in guardadas
        ],
        digest=PeriodicidadDigest(_valor(preferencias, "digest")),
        digest_weekday=int(_valor(preferencias, "digest_weekday")),
        digest_day_of_month=int(_valor(preferencias, "digest_day_of_month")),
        last_digest_at=datetime.fromisoformat(ultimo) if ultimo else None,
    )


@router.get("/settings/notifications", tags=["settings"], summary="Preferencias de aviso")
async def notificaciones(alcance: Alcance) -> NotificacionesRespuesta:
    preferencias = await _preferencias(alcance)
    await alcance.sesion.commit()
    return _respuesta_notificaciones(preferencias)


@router.put("/settings/notifications", tags=["settings"], summary="Sustituye las preferencias")
async def sustituir_notificaciones(
    alcance: AlcanceEscritura, datos: NotificacionesSustituirCrear
) -> NotificacionesRespuesta:
    preferencias = await _preferencias(alcance)
    preferencias.filters = {
        **(preferencias.filters or PREFERENCIAS_POR_DEFECTO),
        "notifications": [
            {
                "type": item.type.value,
                "enabled": item.enabled,
                "min_severity": item.min_severity.value,
                "in_digest": item.in_digest,
            }
            for item in datos.items
        ],
        "digest": datos.digest.value,
        "digest_weekday": datos.digest_weekday,
        "digest_day_of_month": datos.digest_day_of_month,
    }
    await alcance.sesion.commit()
    return _respuesta_notificaciones(preferencias)


# --------------------------------------------------------------------------- #
# Vistas guardadas
# --------------------------------------------------------------------------- #


def _respuesta_vista(vista: SavedView) -> VistaGuardadaRespuesta:
    recurso = vista.entity if vista.entity != "reports" else "transactions"
    return VistaGuardadaRespuesta(
        id=vista.id,
        created_at=vista.created_at,
        updated_at=vista.updated_at,
        name=vista.name,
        resource=recurso,  # type: ignore[arg-type]
        filters=vista.filters or {},
        is_pinned=vista.is_pinned,
        last_used_at=None,
    )


@router.get("/settings/views", tags=["settings"], summary="Vistas guardadas")
async def vistas(alcance: Alcance) -> list[VistaGuardadaRespuesta]:
    filas = (
        await alcance.sesion.execute(
            select(SavedView)
            .where(
                SavedView.household_id == alcance.household_id,
                SavedView.user_id == alcance.usuario.id,
                SavedView.name != FILA_PREFERENCIAS,
            )
            .order_by(SavedView.sort_order, SavedView.name)
        )
    ).scalars()
    return [_respuesta_vista(vista) for vista in filas]


@router.post(
    "/settings/views",
    tags=["settings"],
    status_code=status.HTTP_201_CREATED,
    summary="Guarda los filtros actuales",
)
async def crear_vista(
    alcance: AlcanceEscritura, datos: VistaGuardadaCrear
) -> VistaGuardadaRespuesta:
    if datos.name == FILA_PREFERENCIAS:
        raise ReglaDeNegocio("Ese nombre está reservado.", codigo="datos_invalidos")
    repetida = (
        await alcance.sesion.execute(
            select(SavedView.id).where(
                SavedView.user_id == alcance.usuario.id,
                SavedView.entity == datos.resource,
                func.lower(SavedView.name) == datos.name.lower(),
            )
        )
    ).scalar_one_or_none()
    if repetida is not None:
        raise Conflicto("Ya tienes una vista con ese nombre.", codigo="nombre_duplicado")
    vista = SavedView(
        household_id=alcance.household_id,
        user_id=alcance.usuario.id,
        entity=datos.resource,
        name=datos.name,
        filters=datos.filters,
        is_pinned=datos.is_pinned,
    )
    alcance.sesion.add(vista)
    await alcance.sesion.commit()
    await cargado(alcance.sesion, vista)
    return _respuesta_vista(vista)


@router.patch("/settings/views/{view_id}", tags=["settings"], summary="Edita una vista")
async def actualizar_vista(
    alcance: AlcanceEscritura, view_id: uuidlib.UUID, datos: VistaGuardadaActualizar
) -> VistaGuardadaRespuesta:
    vista = await _vista_o_404(alcance, view_id)
    campos = datos.model_dump(exclude_unset=True)
    if campos.get("name"):
        vista.name = campos["name"]
    if "filters" in campos and campos["filters"] is not None:
        vista.filters = campos["filters"]
    if "is_pinned" in campos and campos["is_pinned"] is not None:
        vista.is_pinned = campos["is_pinned"]
    await alcance.sesion.commit()
    await cargado(alcance.sesion, vista)
    return _respuesta_vista(vista)


@router.delete(
    "/settings/views/{view_id}",
    tags=["settings"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra una vista",
)
async def borrar_vista(alcance: AlcanceEscritura, view_id: uuidlib.UUID) -> Response:
    vista = await _vista_o_404(alcance, view_id)
    await alcance.sesion.delete(vista)
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _vista_o_404(alcance: AlcanceHogar, view_id: uuidlib.UUID) -> SavedView:
    vista = (
        await alcance.sesion.execute(
            select(SavedView).where(
                SavedView.household_id == alcance.household_id,
                SavedView.user_id == alcance.usuario.id,
                SavedView.id == view_id,
                SavedView.name != FILA_PREFERENCIAS,
            )
        )
    ).scalar_one_or_none()
    if vista is None:
        raise NoEncontrado("Esa vista no existe.")
    return vista


# --------------------------------------------------------------------------- #
# Almacenamiento
# --------------------------------------------------------------------------- #


@router.get("/settings/storage", tags=["settings"], summary="Espacio ocupado y cuota")
async def almacenamiento(alcance: Alcance) -> AlmacenamientoRespuesta:
    facturas, cuantas = (
        await alcance.sesion.execute(
            select(func.coalesce(func.sum(Invoice.byte_size), 0), func.count(Invoice.id)).where(
                Invoice.household_id == alcance.household_id
            )
        )
    ).one()
    adjuntos, cuantos = (
        await alcance.sesion.execute(
            select(
                func.coalesce(func.sum(Attachment.byte_size), 0), func.count(Attachment.id)
            ).where(Attachment.household_id == alcance.household_id)
        )
    ).one()
    exportaciones, cuantas_exp = (
        await alcance.sesion.execute(
            select(
                func.coalesce(func.sum(DataExport.byte_size), 0), func.count(DataExport.id)
            ).where(DataExport.household_id == alcance.household_id)
        )
    ).one()
    total = int(facturas) + int(adjuntos) + int(exportaciones)
    return AlmacenamientoRespuesta(
        invoices_bytes=int(facturas),
        attachments_bytes=int(adjuntos),
        exports_bytes=int(exportaciones),
        total_bytes=total,
        # RN-78: sin límite en self-hosted, que es el caso normal.
        quota_bytes=None,
        files_count=int(cuantas) + int(cuantos) + int(cuantas_exp),
        used_pct=None,
    )


# --------------------------------------------------------------------------- #
# Exportación de todos los datos (F-43)
# --------------------------------------------------------------------------- #

#: Qué tablas entran en cada ámbito de exportación.
AMBITOS: dict[AmbitoExportacion, tuple[str, ...]] = {
    AmbitoExportacion.ALL: (
        "accounts",
        "categories",
        "payees",
        "transactions",
        "transaction_splits",
        "invoices",
        "invoice_lines",
        "products",
        "product_aliases",
        "product_prices",
        "budget_periods",
        "budget_allocations",
        "alerts",
        "settings",
    ),
    AmbitoExportacion.TRANSACTIONS: ("accounts", "transactions", "transaction_splits"),
    AmbitoExportacion.INVOICES: ("invoices", "invoice_lines"),
    AmbitoExportacion.PRODUCTS: ("products", "product_aliases", "product_prices"),
    AmbitoExportacion.BUDGETS: ("budget_periods", "budget_allocations"),
    AmbitoExportacion.SETTINGS: ("settings",),
}

_MODELOS = {
    "accounts": Account,
    "categories": Category,
    "payees": Payee,
    "transactions": Transaction,
    "transaction_splits": TransactionSplit,
    "invoices": Invoice,
    "invoice_lines": InvoiceLine,
    "products": Product,
    "product_aliases": ProductAlias,
    "product_prices": ProductPrice,
    "budget_periods": BudgetPeriod,
    "budget_allocations": BudgetAllocation,
    "alerts": Alert,
}


def _serializable(valor: Any) -> Any:
    """Deja el valor listo para `json.dumps`, recursivamente.

    Las columnas `JSONB` y los `ARRAY(UUID)` (el `path_ids` de las temáticas)
    llevan dentro identificadores y decimales, así que no basta con mirar el
    valor de primer nivel.
    """
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, uuidlib.UUID):
        return str(valor)
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    if isinstance(valor, list | tuple):
        return [_serializable(elemento) for elemento in valor]
    if isinstance(valor, dict):
        return {str(clave): _serializable(dato) for clave, dato in valor.items()}
    if isinstance(valor, bytes):
        return valor.hex()
    return valor


async def _volcar(
    sesion: AsyncSession,
    household_id: uuidlib.UUID,
    tablas: tuple[str, ...],
    *,
    desde: date | None,
    hasta: date | None,
) -> dict[str, list[dict[str, Any]]]:
    """Todas las filas del hogar de las tablas pedidas, ya serializables."""
    volcado: dict[str, list[dict[str, Any]]] = {}
    for tabla in tablas:
        modelo = _MODELOS.get(tabla)
        if modelo is None:
            continue
        consulta = select(modelo).where(modelo.household_id == household_id)
        if desde is not None:
            consulta = consulta.where(
                modelo.created_at >= datetime.combine(desde, datetime.min.time(), UTC)
            )
        if hasta is not None:
            consulta = consulta.where(
                modelo.created_at <= datetime.combine(hasta, datetime.max.time(), UTC)
            )
        filas = (await sesion.execute(consulta)).scalars().all()
        volcado[tabla] = [
            {
                columna.name: _serializable(getattr(fila, columna.name))
                for columna in modelo.__table__.columns
            }
            for fila in filas
        ]
    return volcado


async def _datos_de_exportacion(alcance: AlcanceHogar, datos: ExportacionCrear) -> dict[str, Any]:
    tablas = AMBITOS[datos.scope]
    volcado = await _volcar(
        alcance.sesion,
        alcance.household_id,
        tablas,
        desde=datos.date_from,
        hasta=datos.date_to,
    )
    if "settings" in tablas:
        preferencias = await _preferencias(alcance)
        hogar = await alcance.sesion.get(Household, alcance.household_id)
        assert hogar is not None  # noqa: S101
        volcado["settings"] = [
            _respuesta_ajustes(hogar, alcance.usuario.theme, preferencias).model_dump(mode="json")
        ]
    return {
        "generated_at": ahora().isoformat(),
        "household_id": str(alcance.household_id),
        "scope": datos.scope.value,
        "tables": volcado,
    }


def _a_csv(volcado: dict[str, Any]) -> str:
    """Un CSV con todas las tablas, precedidas por su nombre."""
    memoria = io.StringIO()
    for tabla, filas in volcado["tables"].items():
        memoria.write(f"# {tabla}\n")
        if filas:
            escritor = csv.DictWriter(memoria, fieldnames=list(filas[0]), delimiter=";")
            escritor.writeheader()
            for fila in filas:
                escritor.writerow({clave: "" if v is None else v for clave, v in fila.items()})
        memoria.write("\n")
    return memoria.getvalue()


def _ruta_export(clave: str) -> Path:
    raiz = settings.upload_dir.resolve()
    destino = (raiz / clave).resolve()
    if raiz not in destino.parents:
        raise NoEncontrado("El fichero de esta exportación no está disponible.")
    return destino


def _respuesta_exportacion(registro: DataExport) -> ExportacionRespuesta:
    ambito = (registro.scope or {}).get("scope", AmbitoExportacion.ALL.value)
    estado = EstadoExportacion(registro.status if registro.status != "error" else "failed")
    return ExportacionRespuesta(
        id=registro.id,
        created_at=registro.created_at,
        updated_at=registro.updated_at,
        status=estado,
        scope=AmbitoExportacion(ambito),
        format=FormatoExportacion(registro.format),
        date_from=(registro.scope or {}).get("date_from"),
        date_to=(registro.scope or {}).get("date_to"),
        include_files=registro.includes_attachments,
        size_bytes=registro.byte_size,
        rows=sum((registro.row_counts or {}).values()) if registro.row_counts else None,
        file_url=(
            f"{settings.api_prefix}/exports/{registro.id}/file"
            if registro.status == "ready"
            else None
        ),
        expires_at=registro.expires_at,
        error=registro.error_message,
    )


@router.post(
    "/exports",
    tags=["exports"],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Exporta todos tus datos",
)
async def exportar(alcance: AlcanceEscritura, datos: ExportacionCrear) -> ExportacionRespuesta:
    """F-43. El fichero se genera en el acto y caduca a los 7 días."""
    if datos.format is FormatoExportacion.ZIP:
        raise ReglaDeNegocio(
            "El formato zip con los PDF originales todavía no está disponible: usa json o csv.",
            codigo="datos_invalidos",
        )
    volcado = await _datos_de_exportacion(alcance, datos)
    contenido = (
        json.dumps(volcado, ensure_ascii=False, indent=2)
        if datos.format is FormatoExportacion.JSON
        else _a_csv(volcado)
    ).encode("utf-8")

    clave = f"{alcance.usuario.id}/exportaciones/{uuidlib.uuid4()}.{datos.format.value}"
    registro = DataExport(
        household_id=alcance.household_id,
        format=datos.format.value,
        scope={
            "scope": datos.scope.value,
            "date_from": datos.date_from.isoformat() if datos.date_from else None,
            "date_to": datos.date_to.isoformat() if datos.date_to else None,
        },
        status="ready",
        storage_key=clave,
        byte_size=len(contenido),
        sha256=hashlib.sha256(contenido).hexdigest(),
        row_counts={tabla: len(filas) for tabla, filas in volcado["tables"].items()},
        includes_attachments=False,
        expires_at=ahora() + timedelta(days=DIAS_DE_CADUCIDAD),
        requested_by_id=alcance.usuario.id,
    )
    alcance.sesion.add(registro)
    await alcance.sesion.flush()
    destino = _ruta_export(clave)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(contenido)
    await alcance.sesion.commit()
    await cargado(alcance.sesion, registro)
    return _respuesta_exportacion(registro)


@router.get(
    "/exports/quick", tags=["exports"], response_model=None, summary="Exportación inmediata"
)
async def exportacion_rapida(
    alcance: Alcance,
    entity: Annotated[AmbitoExportacion, Query()] = AmbitoExportacion.ALL,
    format: Annotated[FormatoExportacion, Query()] = FormatoExportacion.JSON,
) -> Response:
    """Sin trabajo en segundo plano y sin dejar rastro: se sirve al momento."""
    if format is FormatoExportacion.ZIP:
        raise ReglaDeNegocio("La exportación rápida es json o csv.", codigo="datos_invalidos")
    volcado = await _datos_de_exportacion(alcance, ExportacionCrear(scope=entity, format=format))
    if format is FormatoExportacion.JSON:
        return Response(
            content=json.dumps(volcado, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="datos.json"'},
        )
    return Response(
        content=_a_csv(volcado),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="datos.csv"'},
    )


@router.get("/exports", tags=["exports"], summary="Exportaciones generadas")
async def listar_exportaciones(
    alcance: Alcance,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Pagina[ExportacionRespuesta]:
    consulta = (
        select(DataExport)
        .where(DataExport.household_id == alcance.household_id)
        .order_by(DataExport.created_at.desc())
    )
    total = (
        await alcance.sesion.execute(select(func.count()).select_from(consulta.subquery()))
    ).scalar_one()
    registros = list(
        (await alcance.sesion.execute(consulta.offset((page - 1) * size).limit(size))).scalars()
    )
    return Pagina.crear(
        [_respuesta_exportacion(registro) for registro in registros],
        page=page,
        size=size,
        total=total,
    )


@router.get("/exports/{export_id}", tags=["exports"], summary="Estado de la exportación")
async def detalle_exportacion(alcance: Alcance, export_id: uuidlib.UUID) -> ExportacionRespuesta:
    return _respuesta_exportacion(await _exportacion_o_404(alcance, export_id))


@router.get(
    "/exports/{export_id}/file",
    tags=["exports"],
    response_model=None,
    summary="Descarga el fichero",
)
async def descargar_exportacion(alcance: Alcance, export_id: uuidlib.UUID) -> FileResponse:
    registro = await _exportacion_o_404(alcance, export_id)
    if registro.status != "ready":
        raise Conflicto("La exportación todavía no está lista.", codigo="conflicto")
    if registro.expires_at is not None and registro.expires_at < ahora():
        raise Conflicto(
            "La exportación ha caducado. Genérala otra vez.",
            codigo="caducada",
            estado=status.HTTP_410_GONE,
        )
    ruta = _ruta_export(registro.storage_key or "")
    if not ruta.is_file():
        raise NoEncontrado("El fichero de esta exportación ya no está en el disco.")
    tipos = {"json": "application/json", "csv": "text/csv; charset=utf-8"}
    return FileResponse(
        ruta,
        media_type=tipos.get(registro.format, "application/octet-stream"),
        filename=f"datos.{registro.format}",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.delete(
    "/exports/{export_id}",
    tags=["exports"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra la exportación",
)
async def borrar_exportacion(alcance: AlcanceEscritura, export_id: uuidlib.UUID) -> Response:
    registro = await _exportacion_o_404(alcance, export_id)
    clave = registro.storage_key
    await alcance.sesion.delete(registro)
    await alcance.sesion.commit()
    if clave:
        _ruta_export(clave).unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _exportacion_o_404(alcance: AlcanceHogar, export_id: uuidlib.UUID) -> DataExport:
    registro = (
        await alcance.sesion.execute(
            select(DataExport).where(
                DataExport.household_id == alcance.household_id, DataExport.id == export_id
            )
        )
    ).scalar_one_or_none()
    if registro is None:
        raise NoEncontrado("Esa exportación no existe.")
    return registro
