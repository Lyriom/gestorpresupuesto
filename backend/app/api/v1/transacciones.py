"""Transacciones, repartos, operaciones en lote, duplicados y adjuntos (§3.5).

Este módulo guarda además las piezas compartidas por el resto de routers del
grupo —búsqueda sin acentos, ordenación con lista blanca, resolución de
entidades del hogar y la conversión de importe firmado—, que los demás importan
de aquí para no tener cinco copias.

Dos invariantes gobiernan el fichero:

* **`ck_transactions_split_invariant`**: una transacción es simple (con temática
  y sin reparto) o repartida (sin temática y con splits que suman su importe),
  nunca las dos. El disparador `refresh_transaction_split_totals` recalcula la
  cabecera después de **cada sentencia** sobre `transaction_splits`, así que el
  reparto se escribe siempre con una sola sentencia multifila y se retira con un
  CTE que actualiza la cabecera en la misma sentencia. Cualquier otro orden deja
  un estado intermedio que la restricción rechaza (y hace bien).
* **RN-21**: una transferencia no es gasto ni ingreso. Las dos patas llevan
  `kind = 'transfer'`, no tienen temática y quedan fuera de todo agregado de
  gasto; se crean y se borran por `/transfers`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

import aiofiles
from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import (
    ColumnElement,
    Select,
    delete,
    func,
    insert,
    or_,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.orm import selectinload

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, PaginacionActual, verificar_csrf
from app.core.config import settings
from app.core.errors import AppError, Conflicto, NoEncontrado, ReglaDeNegocio
from app.models.categoria import Category
from app.models.comercio import Payee
from app.models.cuenta import Account
from app.models.factura import Invoice
from app.models.regla import CategorizationRule
from app.models.transaccion import (
    Attachment,
    Tag,
    Transaction,
    TransactionSplit,
    TransactionTag,
)
from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comercio import ComercioRefRespuesta
from app.schemas.comun import Pagina, ResultadoLoteRespuesta
from app.schemas.cuenta import CuentaRefRespuesta
from app.schemas.etiqueta import EtiquetaRefRespuesta
from app.schemas.regla import condiciones_de
from app.schemas.transaccion import (
    AdjuntoRespuesta,
    DuplicadoFiltro,
    EstadoMovimiento,
    GrupoDuplicadoRespuesta,
    LoteBorrarCrear,
    LoteCategorizarCrear,
    LoteEtiquetarCrear,
    OrigenMovimiento,
    SplitRespuesta,
    SplitsSustituirCrear,
    TipoMovimiento,
    TransaccionActualizar,
    TransaccionCrear,
    TransaccionFiltro,
    TransaccionFusionCrear,
    TransaccionRespuesta,
)
from app.services.normalizacion import sin_acentos
from app.services.reglas import MovimientoEvaluable, Regla, aplicar_reglas

# Las rutas llevan su prefijo completo (`/transactions`, `/attachments`), así que el agregador
# incluye este router sin `prefix`. `verificar_csrf` va en el router porque no
# hace nada en GET, HEAD ni OPTIONS: así no se puede olvidar en un endpoint.
router = APIRouter(tags=["transactions"], dependencies=[Depends(verificar_csrf)])

CERO = Decimal("0.00")

#: Tipos de adjunto admitidos, reconocidos por firma y no por `content-type` (RN-76).
FIRMAS_ADJUNTO: tuple[tuple[bytes, str, str], ...] = (
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
)

#: La base no tiene la extensión `unaccent`, así que el pliegue de acentos se
#: hace con `translate`. Cubre el castellano, que es el único idioma de la
#: interfaz, y permite que `q=alimentacion` encuentre «Alimentación».
_ACENTOS = "áàäâãéèëêíìïîóòöôõúùüûñç"
_LLANOS = "aaaaaeeeeiiiiooooouuuunc"

#: Se leen los ficheros subidos a trozos para no cargar 20 MiB en memoria.
_TROZO = 64 * 1024


# --------------------------------------------------------------------------- #
# Piezas compartidas por todos los routers del grupo
# --------------------------------------------------------------------------- #


def texto_plano(columna: ColumnElement[Any]) -> ColumnElement[str]:
    """La columna en minúsculas y sin tildes, para comparar con `ILIKE`."""
    return func.translate(func.lower(columna), _ACENTOS, _LLANOS)


def patron(texto: str) -> str:
    """Patrón `%…%` ya normalizado igual que `texto_plano()`."""
    return f"%{sin_acentos(texto).lower()}%"


def aplicar_orden(
    consulta: Select[Any],
    criterios: Iterable[tuple[str, bool]],
    columnas: dict[str, Any],
    desempate: Any,
) -> Select[Any]:
    """Aplica `sort` con lista blanca y añade siempre el desempate por `id` (§1.6)."""
    for campo, descendente in criterios:
        columna = columnas.get(campo)
        if columna is None:
            continue
        consulta = consulta.order_by(
            columna.desc().nulls_last() if descendente else columna.asc().nulls_last()
        )
    return consulta.order_by(desempate.desc())


async def contar(alcance: AlcanceHogar, consulta: Select[Any]) -> int:
    """Total de filas de un listado, sin su orden ni su paginación."""
    total = await alcance.sesion.scalar(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    )
    return int(total or 0)


async def del_hogar[T](
    alcance: AlcanceHogar,
    modelo: type[T],
    identificador: uuid.UUID,
    *,
    mensaje: str,
    cargas: Sequence[Any] = (),
) -> T:
    """Una fila del hogar de la sesión, o 404.

    RN-02: si la fila existe pero es de otro hogar la respuesta es la misma que
    si no existiera, para no permitir enumerar identificadores.
    """
    consulta = select(modelo).where(
        modelo.household_id == alcance.household_id,  # type: ignore[attr-defined]
        modelo.id == identificador,  # type: ignore[attr-defined]
    )
    for carga in cargas:
        consulta = consulta.options(carga)
    fila = (await alcance.sesion.execute(consulta)).unique().scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(mensaje)
    return fila


def importe_firmado(kind: str, importe: Decimal) -> Decimal:
    """Importe tecleado → importe firmado que guarda la base (§0.5 del modelo).

    Un gasto se teclea en positivo y se guarda en negativo; una devolución se
    teclea en negativo y se guarda en positivo, de modo que **reduzca** el
    gastado de su temática en lugar de inflar los ingresos del mes.
    """
    return -importe if kind == TipoMovimiento.EXPENSE else importe


def importe_visible(kind: str, guardado: Decimal) -> Decimal:
    """La inversa de `importe_firmado()`: lo que se devuelve como `amount`."""
    if kind == TipoMovimiento.TRANSFER:
        return abs(guardado)
    return -guardado if kind == TipoMovimiento.EXPENSE else guardado


def ref_tematica(categoria: Category | None) -> CategoriaRefRespuesta | None:
    if categoria is None:
        return None
    return CategoriaRefRespuesta(id=categoria.id, name=categoria.name, color=categoria.color_hex)


def ref_comercio(comercio: Payee | None) -> ComercioRefRespuesta | None:
    if comercio is None:
        return None
    return ComercioRefRespuesta(id=comercio.id, name=comercio.name)


def ref_cuenta(cuenta: Account | None) -> CuentaRefRespuesta | None:
    if cuenta is None:
        return None
    return CuentaRefRespuesta(
        id=cuenta.id,
        name=cuenta.name,
        type=cuenta.type,
        currency=cuenta.currency,
        color=None,
    )


async def cuenta_del_hogar(alcance: AlcanceHogar, cuenta_id: uuid.UUID) -> Account:
    cuenta = await del_hogar(alcance, Account, cuenta_id, mensaje="La cuenta no existe.")
    if cuenta.archived_at is not None:
        raise ReglaDeNegocio("La cuenta está archivada: desarchívala para poder usarla.")
    return cuenta


async def tematica_del_hogar(
    alcance: AlcanceHogar,
    categoria_id: uuid.UUID,
    *,
    permitir_ingreso: bool = True,
) -> Category:
    """Temática viva del hogar. Una archivada no admite movimientos nuevos (RN-34)."""
    categoria = await del_hogar(alcance, Category, categoria_id, mensaje="La temática no existe.")
    if categoria.archived_at is not None:
        raise ReglaDeNegocio("La temática está archivada: elige otra o desarchívala.")
    if not permitir_ingreso and categoria.kind != "expense":
        raise ReglaDeNegocio("Esa temática es de ingresos y aquí hace falta una de gastos.")
    return categoria


async def etiquetas_del_hogar(alcance: AlcanceHogar, ids: Sequence[uuid.UUID]) -> list[Tag]:
    if not ids:
        return []
    filas = (
        (
            await alcance.sesion.execute(
                select(Tag).where(
                    Tag.household_id == alcance.household_id,
                    Tag.id.in_(set(ids)),
                    Tag.archived_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if len(filas) != len(set(ids)):
        raise NoEncontrado("Alguna de las etiquetas no existe.")
    return list(filas)


async def subarbol_de(alcance: AlcanceHogar, ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
    """Los identificadores pedidos más todos sus descendientes (§7.3).

    Se resuelve con el índice GIN sobre `path_ids`, en una sola consulta y sin
    CTE recursiva: una temática desciende de otra si su ruta la contiene.
    """
    if not ids:
        return []
    filas = await alcance.sesion.scalars(
        select(Category.id).where(
            Category.household_id == alcance.household_id,
            Category.path_ids.overlap(list(ids)),
        )
    )
    return list(filas)


async def ajustar_uso_etiquetas(
    alcance: AlcanceHogar, ids: Iterable[uuid.UUID], delta: int
) -> None:
    """Mantiene el contador de uso que ordena el selector de etiquetas."""
    unicos = list(set(ids))
    if not unicos or delta == 0:
        return
    await alcance.sesion.execute(
        update(Tag)
        .where(Tag.household_id == alcance.household_id, Tag.id.in_(unicos))
        .values(usage_count=func.greatest(Tag.usage_count + delta, 0))
    )


async def ajustar_uso_comercio(
    alcance: AlcanceHogar, comercio_id: uuid.UUID | None, delta: int, cuando: date | None = None
) -> None:
    """Contador y última fecha vista del comercio (F-37)."""
    if comercio_id is None or delta == 0:
        return
    valores: dict[str, Any] = {
        "transaction_count": func.greatest(Payee.transaction_count + delta, 0)
    }
    if cuando is not None and delta > 0:
        valores["last_seen_on"] = func.greatest(func.coalesce(Payee.last_seen_on, cuando), cuando)
    await alcance.sesion.execute(
        update(Payee)
        .where(Payee.household_id == alcance.household_id, Payee.id == comercio_id)
        .values(**valores)
    )


async def resolver_comercio(
    alcance: AlcanceHogar, comercio_id: uuid.UUID | None, nombre: str | None
) -> Payee | None:
    """Comercio por identificador o por nombre, creándolo si hace falta."""
    if comercio_id is not None:
        return await del_hogar(alcance, Payee, comercio_id, mensaje="El comercio no existe.")
    if not nombre or not nombre.strip():
        return None

    normalizado = sin_acentos(nombre).lower().strip()
    existente = (
        await alcance.sesion.execute(
            select(Payee).where(
                Payee.household_id == alcance.household_id,
                Payee.normalized_name == normalizado,
                Payee.merged_into_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        return existente

    comercio = Payee(
        household_id=alcance.household_id,
        name=nombre.strip(),
        normalized_name=normalizado,
    )
    alcance.sesion.add(comercio)
    await alcance.sesion.flush()
    return comercio


async def reglas_activas(alcance: AlcanceHogar) -> list[Regla]:
    """Reglas de auto-categorización del hogar, listas para el motor (F-27)."""
    filas = (
        (
            await alcance.sesion.execute(
                select(CategorizationRule).where(
                    CategorizationRule.household_id == alcance.household_id,
                    CategorizationRule.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    reglas: list[Regla] = []
    for fila in filas:
        try:
            condiciones = condiciones_de(fila.conditions)
        except Exception:  # noqa: BLE001 - una regla corrupta no debe romper el alta
            continue
        if not condiciones:
            continue
        try:
            reglas.append(
                Regla(
                    regla_id=str(fila.id),
                    nombre=fila.name or fila.text_form,
                    condiciones=condiciones,
                    categoria_id=str(fila.set_category_id) if fila.set_category_id else None,
                    comercio_id=str(fila.set_payee_id) if fila.set_payee_id else None,
                    etiquetas=[str(t) for t in (fila.add_tag_ids or [])] or None,
                    prioridad=fila.priority,
                    activa=fila.is_active,
                    exigir_todas=fila.match_mode == "all",
                )
            )
        except Exception:  # noqa: BLE001
            continue
    return reglas


def evaluable_de(
    descripcion: str | None,
    comercio: Payee | None,
    cuenta: Account | None,
    importe: Decimal | None,
) -> MovimientoEvaluable:
    return MovimientoEvaluable(
        descripcion=descripcion,
        comercio=comercio.name if comercio else None,
        importe=importe,
        cuenta=cuenta.name if cuenta else None,
    )


def sin_transferencias() -> ColumnElement[bool]:
    """RN-21: filtro común de todo agregado de gasto o de ingreso."""
    return (Transaction.kind != TipoMovimiento.TRANSFER.value) & (
        Transaction.excluded_from_reports.is_(False)
    )


# --------------------------------------------------------------------------- #
# Contexto de una página: todas las relaciones resueltas en bloque (§7.1)
# --------------------------------------------------------------------------- #

TODO_INCLUIDO = frozenset({"splits", "tags", "payee", "attachments", "account", "category"})


@dataclass(slots=True)
class Contexto:
    """Relaciones de una página de transacciones, resueltas sin N+1."""

    tematicas: dict[uuid.UUID, Category] = field(default_factory=dict)
    cuentas: dict[uuid.UUID, Account] = field(default_factory=dict)
    comercios: dict[uuid.UUID, Payee] = field(default_factory=dict)
    etiquetas: dict[uuid.UUID, list[Tag]] = field(default_factory=dict)
    contrapartes: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    facturas: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    adjuntos: dict[uuid.UUID, list[Attachment]] = field(default_factory=dict)


async def contexto_de(
    alcance: AlcanceHogar, transacciones: Sequence[Transaction], incluir: frozenset[str]
) -> Contexto:
    """Una consulta por relación para toda la página, nunca una por fila."""
    contexto = Contexto()
    if not transacciones:
        return contexto

    sesion = alcance.sesion
    ids = [t.id for t in transacciones]

    ids_tematica = {t.category_id for t in transacciones if t.category_id}
    if "splits" in incluir:
        for transaccion in transacciones:
            ids_tematica.update(split.category_id for split in transaccion.splits)
    if ids_tematica:
        filas = await sesion.scalars(select(Category).where(Category.id.in_(ids_tematica)))
        contexto.tematicas = {categoria.id: categoria for categoria in filas}

    ids_cuenta = {t.account_id for t in transacciones}
    filas_cuenta = await sesion.scalars(select(Account).where(Account.id.in_(ids_cuenta)))
    contexto.cuentas = {cuenta.id: cuenta for cuenta in filas_cuenta}

    ids_comercio = {t.payee_id for t in transacciones if t.payee_id}
    if ids_comercio:
        filas_comercio = await sesion.scalars(select(Payee).where(Payee.id.in_(ids_comercio)))
        contexto.comercios = {comercio.id: comercio for comercio in filas_comercio}

    if "tags" in incluir:
        filas_etiqueta = await sesion.execute(
            select(TransactionTag.transaction_id, Tag)
            .join(Tag, Tag.id == TransactionTag.tag_id)
            .where(TransactionTag.transaction_id.in_(ids))
            .order_by(Tag.name)
        )
        for transaccion_id, etiqueta in filas_etiqueta:
            contexto.etiquetas.setdefault(transaccion_id, []).append(etiqueta)

    if "attachments" in incluir:
        filas_adjunto = await sesion.scalars(
            select(Attachment).where(Attachment.transaction_id.in_(ids))
        )
        for adjunto in filas_adjunto:
            contexto.adjuntos.setdefault(adjunto.transaction_id, []).append(adjunto)  # type: ignore[arg-type]

    grupos = {t.transfer_group_id for t in transacciones if t.transfer_group_id}
    if grupos:
        patas = await sesion.execute(
            select(Transaction.id, Transaction.transfer_group_id).where(
                Transaction.household_id == alcance.household_id,
                Transaction.transfer_group_id.in_(grupos),
            )
        )
        por_grupo: dict[uuid.UUID, list[uuid.UUID]] = {}
        for pata_id, grupo in patas:
            por_grupo.setdefault(grupo, []).append(pata_id)
        for transaccion in transacciones:
            if not transaccion.transfer_group_id:
                continue
            otras = [
                otra
                for otra in por_grupo.get(transaccion.transfer_group_id, [])
                if otra != transaccion.id
            ]
            if otras:
                contexto.contrapartes[transaccion.id] = otras[0]

    filas_factura = await sesion.execute(
        select(Invoice.transaction_id, Invoice.id).where(Invoice.transaction_id.in_(ids))
    )
    contexto.facturas = {
        transaccion_id: factura_id for transaccion_id, factura_id in filas_factura if transaccion_id
    }
    return contexto


def _origen_de(transaccion: Transaction, contexto: Contexto) -> OrigenMovimiento:
    if transaccion.import_batch_id is not None:
        return OrigenMovimiento.IMPORT
    if transaccion.id in contexto.facturas:
        return OrigenMovimiento.INVOICE
    if transaccion.recurring_rule_id is not None:
        return OrigenMovimiento.RECURRING
    if transaccion.reconciliation_id is not None:
        return OrigenMovimiento.RECONCILIATION
    return OrigenMovimiento.MANUAL


#: `categorized_by` de la base admite `payee`, que el contrato no expone: una
#: sugerencia del comercio es, de cara al usuario, una categorización automática.
_ORIGEN_CATEGORIA = {
    "user": "user",
    "rule": "rule",
    "payee": "rule",
    "import": "import",
    "invoice": "invoice",
}


def respuesta_transaccion(
    transaccion: Transaction, contexto: Contexto, incluir: frozenset[str]
) -> TransaccionRespuesta:
    """Traduce el modelo al contrato, con los importes ya en su signo visible."""
    tematica = contexto.tematicas.get(transaccion.category_id) if transaccion.category_id else None
    splits: list[SplitRespuesta] = []
    if "splits" in incluir:
        splits = [
            SplitRespuesta(
                id=split.id,
                category_id=split.category_id,
                category=ref_tematica(contexto.tematicas.get(split.category_id)),
                amount=importe_visible(transaccion.kind, split.amount),
                note=split.notes,
                invoice_line_id=split.invoice_line_id,
            )
            for split in transaccion.splits
        ]

    return TransaccionRespuesta(
        id=transaccion.id,
        created_at=transaccion.created_at,
        updated_at=transaccion.updated_at,
        kind=TipoMovimiento(transaccion.kind),
        account_id=transaccion.account_id,
        account=ref_cuenta(contexto.cuentas.get(transaccion.account_id)),
        date=transaccion.booked_on,
        amount=importe_visible(transaccion.kind, transaccion.amount),
        signed_amount=transaccion.amount,
        currency=transaccion.currency,
        category_id=transaccion.category_id,
        category=ref_tematica(tematica),
        payee_id=transaccion.payee_id,
        payee=ref_comercio(
            contexto.comercios.get(transaccion.payee_id) if transaccion.payee_id else None
        ),
        description=transaccion.description or None,
        note=transaccion.notes,
        is_split=transaccion.split_count > 0,
        splits=splits,
        tags=[
            EtiquetaRefRespuesta(id=etiqueta.id, name=etiqueta.name, color=None)
            for etiqueta in contexto.etiquetas.get(transaccion.id, [])
        ],
        attachments_count=transaccion.attachment_count,
        attachments=[
            respuesta_adjunto(adjunto) for adjunto in contexto.adjuntos.get(transaccion.id, [])
        ],
        invoice_id=contexto.facturas.get(transaccion.id),
        recurring_id=transaccion.recurring_rule_id,
        transfer_group_id=transaccion.transfer_group_id,
        transfer_counterpart_id=contexto.contrapartes.get(transaccion.id),
        status=EstadoMovimiento(transaccion.status),
        is_reconciled=transaccion.status == EstadoMovimiento.RECONCILED,
        is_anomaly=False,
        source=_origen_de(transaccion, contexto),
        categorized_by=_ORIGEN_CATEGORIA.get(transaccion.categorized_by),  # type: ignore[arg-type]
    )


async def una_respuesta(
    alcance: AlcanceHogar, transaccion_id: uuid.UUID, incluir: frozenset[str] = TODO_INCLUIDO
) -> TransaccionRespuesta:
    """Respuesta de una transacción releída de la base.

    Se relee con `populate_existing` porque el reparto se escribe con SQL crudo y
    un disparador toca la cabecera: la copia que tiene la sesión en memoria está
    desfasada y el mapa de identidad, por sí solo, no la refrescaría.
    """
    transaccion = (
        (
            await alcance.sesion.execute(
                select(Transaction)
                .where(
                    Transaction.household_id == alcance.household_id,
                    Transaction.id == transaccion_id,
                )
                .options(selectinload(Transaction.splits))
                .execution_options(populate_existing=True)
            )
        )
        .unique()
        .scalar_one()
    )
    contexto = await contexto_de(alcance, [transaccion], incluir)
    return respuesta_transaccion(transaccion, contexto, incluir)


def respuesta_adjunto(adjunto: Attachment) -> AdjuntoRespuesta:
    return AdjuntoRespuesta(
        id=adjunto.id,
        created_at=adjunto.created_at,
        updated_at=adjunto.updated_at,
        transaction_id=adjunto.transaction_id,
        invoice_id=adjunto.invoice_id,
        filename=adjunto.file_name,
        content_type=adjunto.mime_type,
        size_bytes=adjunto.byte_size,
        pages=adjunto.page_count,
        checksum=adjunto.sha256,
        download_url=f"{settings.api_prefix}/attachments/{adjunto.id}/content",
    )


# --------------------------------------------------------------------------- #
# Reparto en splits
# --------------------------------------------------------------------------- #


async def _validar_tematicas_de_splits(
    alcance: AlcanceHogar, categorias: Sequence[uuid.UUID], kind: str
) -> None:
    """RN-15: ninguna archivada y ninguna de `kind` distinto al del movimiento."""
    for categoria_id in dict.fromkeys(categorias):
        categoria = await tematica_del_hogar(alcance, categoria_id)
        if categoria.kind != kind:
            clase = "gastos" if kind == "expense" else "ingresos"
            raise ReglaDeNegocio(
                f"«{categoria.name}» no es una temática de {clase}.",
                codigo="splits_no_cuadran",
            )


def _comprobar_suma(splits: Sequence[Decimal], importe: Decimal) -> None:
    """RN-15: la suma es exactamente el importe, en `Decimal` y al céntimo."""
    total = sum(splits, CERO)
    if total != importe:
        raise ReglaDeNegocio(
            "Los splits deben sumar exactamente el importe de la transacción.",
            codigo="splits_no_cuadran",
            detalles=[
                {
                    "campo": "splits",
                    "mensaje": f"Suman {total:.2f} € y la transacción es de {importe:.2f} €.",
                }
            ],
        )


async def _escribir_splits(
    alcance: AlcanceHogar,
    transaccion: Transaction,
    lineas: Sequence[tuple[uuid.UUID, Decimal, str | None]],
    *,
    tematica_final: uuid.UUID | None = None,
    importe: Decimal | None = None,
) -> None:
    """Sustituye el reparto completo respetando el invariante en cada paso.

    El disparador de `transaction_splits` recalcula la cabecera después de cada
    sentencia, y `ck_transactions_split_invariant` se evalúa ahí mismo: por eso
    el borrado va en un CTE que deja la cabecera ya coherente y la inserción es
    **una sola** sentencia multifila. Con `lineas` vacío se deshace el reparto y
    `tematica_final` es la temática única que queda.

    `importe` cambia el importe de la cabecera **en la misma sentencia** que
    retira el reparto anterior (RN-16): escribirlo antes dejaría un instante en
    el que los splits viejos no suman el importe nuevo, y eso es exactamente lo
    que el invariante prohíbe.
    """
    sesion = alcance.sesion
    provisional = tematica_final or (lineas[0][0] if lineas else transaccion.category_id)
    await sesion.execute(
        text(
            """
            WITH borrado AS (
                DELETE FROM transaction_splits WHERE transaction_id = :transaccion RETURNING 1
            )
            UPDATE transactions
               SET category_id = :tematica,
                   split_count = 0,
                   split_total = 0,
                   amount = COALESCE(:importe, amount)
             WHERE id = :transaccion AND household_id = :hogar
            """
        ),
        {
            "transaccion": transaccion.id,
            "tematica": provisional,
            "importe": importe,
            "hogar": alcance.household_id,
        },
    )
    if lineas:
        await sesion.execute(
            insert(TransactionSplit).values(
                [
                    {
                        "id": uuid.uuid4(),
                        "household_id": alcance.household_id,
                        "transaction_id": transaccion.id,
                        "category_id": categoria_id,
                        "amount": importe,
                        "line_number": numero,
                        "notes": nota,
                    }
                    for numero, (categoria_id, importe, nota) in enumerate(lineas, start=1)
                ]
            )
        )


# --------------------------------------------------------------------------- #
# Listado
# --------------------------------------------------------------------------- #


def _columnas_de_orden() -> dict[str, Any]:
    return {
        "date": Transaction.booked_on,
        "amount": Transaction.amount,
        "created_at": Transaction.created_at,
        "description": Transaction.description,
        "payee": select(Payee.name).where(Payee.id == Transaction.payee_id).scalar_subquery(),
        "category": select(Category.name)
        .where(Category.id == Transaction.category_id)
        .scalar_subquery(),
        "account": select(Account.name)
        .where(Account.id == Transaction.account_id)
        .scalar_subquery(),
    }


async def _consulta_filtrada(alcance: AlcanceHogar, filtro: TransaccionFiltro) -> Select[Any]:
    """Todos los filtros de F-42, combinables entre sí."""
    if filtro.date_from and filtro.date_to and filtro.date_from > filtro.date_to:
        raise AppError("El rango de fechas está invertido: «desde» es posterior a «hasta».")

    consulta = select(Transaction).where(Transaction.household_id == alcance.household_id)

    if filtro.date_from:
        consulta = consulta.where(Transaction.booked_on >= filtro.date_from)
    if filtro.date_to:
        consulta = consulta.where(Transaction.booked_on <= filtro.date_to)
    if filtro.account_id:
        consulta = consulta.where(Transaction.account_id.in_(filtro.account_id))
    if filtro.kind:
        consulta = consulta.where(Transaction.kind.in_([k.value for k in filtro.kind]))
    if filtro.status:
        consulta = consulta.where(Transaction.status.in_([e.value for e in filtro.status]))
    if filtro.payee_id:
        consulta = consulta.where(Transaction.payee_id.in_(filtro.payee_id))

    if filtro.category_id:
        ids = (
            await subarbol_de(alcance, filtro.category_id)
            if filtro.include_children
            else list(filtro.category_id)
        )
        # Una transacción entra si su temática es una de ellas o si alguno de sus
        # splits lo es: si no, un gasto repartido desaparecería del filtro.
        consulta = consulta.where(
            or_(
                Transaction.category_id.in_(ids),
                select(TransactionSplit.id)
                .where(
                    TransactionSplit.transaction_id == Transaction.id,
                    TransactionSplit.category_id.in_(ids),
                )
                .exists(),
            )
        )

    # El rango de importes se compara sobre el valor absoluto: el usuario piensa
    # en «entre 10 y 50 euros», no en el signo con el que se guarda.
    if filtro.min_amount is not None:
        consulta = consulta.where(func.abs(Transaction.amount) >= abs(filtro.min_amount))
    if filtro.max_amount is not None:
        consulta = consulta.where(func.abs(Transaction.amount) <= abs(filtro.max_amount))

    if filtro.tag_id:
        consulta = consulta.where(
            select(TransactionTag.id)
            .where(
                TransactionTag.transaction_id == Transaction.id,
                TransactionTag.tag_id.in_(filtro.tag_id),
            )
            .exists()
        )

    factura_existe = select(Invoice.id).where(Invoice.transaction_id == Transaction.id).exists()
    if filtro.has_invoice is not None:
        consulta = consulta.where(factura_existe if filtro.has_invoice else ~factura_existe)
    if filtro.invoice_id is not None:
        consulta = consulta.where(
            select(Invoice.id)
            .where(Invoice.transaction_id == Transaction.id, Invoice.id == filtro.invoice_id)
            .exists()
        )
    if filtro.has_attachments is not None:
        consulta = consulta.where(
            Transaction.attachment_count > 0
            if filtro.has_attachments
            else Transaction.attachment_count == 0
        )
    if filtro.only_recurring:
        consulta = consulta.where(Transaction.recurring_rule_id.is_not(None))
    if filtro.recurring_id is not None:
        consulta = consulta.where(Transaction.recurring_rule_id == filtro.recurring_id)
    if filtro.only_uncategorized:
        # El invariante de la base exige temática en toda transacción simple, así
        # que esto solo puede casar con repartos a medio hacer; se deja literal
        # para no inventar una semántica distinta de la del contrato.
        consulta = consulta.where(Transaction.category_id.is_(None), Transaction.split_count == 0)
    if filtro.only_anomalies:
        # F-48 (detección de gasto inusual) no está implementada todavía: el
        # filtro existe en el contrato y devuelve una lista vacía, nunca datos
        # inventados.
        consulta = consulta.where(text("false"))

    if filtro.q:
        aguja = patron(filtro.q)
        consulta = consulta.where(
            or_(
                texto_plano(Transaction.description).like(aguja),
                texto_plano(func.coalesce(Transaction.notes, "")).like(aguja),
                select(Payee.id)
                .where(Payee.id == Transaction.payee_id, texto_plano(Payee.name).like(aguja))
                .exists(),
            )
        )
    return consulta


def _cursor_a_clave(cursor: str) -> tuple[date, uuid.UUID]:
    try:
        crudo = base64.urlsafe_b64decode(cursor.encode()).decode()
        fecha, identificador = crudo.split("|", 1)
        return date.fromisoformat(fecha), uuid.UUID(identificador)
    except (ValueError, binascii.Error) as exc:
        raise AppError("El cursor de paginación no es válido.") from exc


def _clave_a_cursor(transaccion: Transaction) -> str:
    crudo = f"{transaccion.booked_on.isoformat()}|{transaccion.id}"
    return base64.urlsafe_b64encode(crudo.encode()).decode()


@router.get("/transactions", summary="Listado con todos los filtros combinables (F-42)")
async def listar_transacciones(
    alcance: Alcance,
    filtro: Annotated[TransaccionFiltro, Query()],
) -> Pagina[TransaccionRespuesta]:
    """Listado paginado y ordenable. El orden por defecto es `-date,-created_at`."""
    incluir = frozenset(filtro.include) | {"account", "category", "payee"}
    consulta = await _consulta_filtrada(alcance, filtro)
    consulta = consulta.options(selectinload(Transaction.splits))

    if filtro.cursor:
        # Modo alternativo del botón «cargar 50 más»: keyset sobre (fecha, id), sin
        # `total` y sin `OFFSET`.
        fecha, identificador = _cursor_a_clave(filtro.cursor)
        consulta = consulta.where(
            tuple_(Transaction.booked_on, Transaction.id) < tuple_(fecha, identificador)
        )
        consulta = consulta.order_by(Transaction.booked_on.desc(), Transaction.id.desc())
        filas = list((await alcance.sesion.execute(consulta.limit(filtro.size))).scalars())
        contexto = await contexto_de(alcance, filas, incluir)
        siguiente = _clave_a_cursor(filas[-1]) if len(filas) == filtro.size else None
        return Pagina.crear(
            [respuesta_transaccion(fila, contexto, incluir) for fila in filas],
            page=1,
            size=filtro.size,
            total=len(filas),
            next_cursor=siguiente,
        )

    total = await contar(alcance, consulta)
    consulta = aplicar_orden(consulta, filtro.orden, _columnas_de_orden(), Transaction.id)
    filas = list(
        (await alcance.sesion.execute(consulta.offset(filtro.desplazamiento).limit(filtro.size)))
        .unique()
        .scalars()
    )
    contexto = await contexto_de(alcance, filas, incluir)
    return Pagina.crear(
        [respuesta_transaccion(fila, contexto, incluir) for fila in filas],
        page=filtro.page,
        size=filtro.size,
        total=total,
    )


# --------------------------------------------------------------------------- #
# Alta, edición y borrado
# --------------------------------------------------------------------------- #


@router.post(
    "/transactions", status_code=status.HTTP_201_CREATED, summary="Alta de gasto o ingreso"
)
async def crear_transaccion(
    alcance: AlcanceEscritura,
    datos: TransaccionCrear,
    respuesta: Response,
) -> TransaccionRespuesta:
    """Alta rápida (F-07) con splits, etiquetas y comercio de una sola vez."""
    cuenta = await cuenta_del_hogar(alcance, datos.account_id)
    comercio = await resolver_comercio(alcance, datos.payee_id, datos.payee_name)
    etiquetas = await etiquetas_del_hogar(alcance, datos.tag_ids)
    firmado = importe_firmado(datos.kind.value, datos.amount)

    categoria_id: uuid.UUID | None = None
    origen_categoria = "user"
    regla_aplicada: uuid.UUID | None = None

    if datos.splits:
        await _validar_tematicas_de_splits(
            alcance, [s.category_id for s in datos.splits], datos.kind.value
        )
    elif datos.category_id is not None:
        categoria = await tematica_del_hogar(alcance, datos.category_id)
        if categoria.kind != datos.kind.value:
            raise ReglaDeNegocio(f"«{categoria.name}» no corresponde a un movimiento de este tipo.")
        categoria_id = categoria.id
    else:
        if datos.apply_rules:
            asignacion = aplicar_reglas(
                evaluable_de(datos.description, comercio, cuenta, datos.amount),
                await reglas_activas(alcance),
            )
            if asignacion and asignacion.categoria_id:
                categoria_id = uuid.UUID(asignacion.categoria_id)
                origen_categoria = "rule"
                regla_aplicada = uuid.UUID(asignacion.regla_id)
        if categoria_id is None and comercio is not None and comercio.default_category_id:
            categoria_id = comercio.default_category_id
            origen_categoria = "payee"
        if categoria_id is None:
            raise ReglaDeNegocio(
                "Indica la temática: ninguna regla ha podido deducirla.",
                codigo="datos_invalidos",
                detalles=[{"campo": "category_id", "mensaje": "Este campo es obligatorio."}],
            )

    if datos.splits:
        _comprobar_suma([s.amount for s in datos.splits], datos.amount)

    # La cabecera nace ya cuadrada (`split_count` y `split_total` propios): así el
    # INSERT no pasa nunca por un estado que el invariante rechace.
    transaccion = Transaction(
        household_id=alcance.household_id,
        account_id=cuenta.id,
        kind=datos.kind.value,
        booked_on=datos.date,
        amount=firmado,
        currency=datos.currency,
        category_id=categoria_id,
        payee_id=comercio.id if comercio else None,
        description=(datos.description or "").strip(),
        notes=datos.note,
        status=datos.status.value,
        categorized_by=origen_categoria,
        applied_rule_id=regla_aplicada,
        created_by_id=alcance.usuario.id,
        recurring_rule_id=datos.recurring_id,
        split_count=len(datos.splits),
        split_total=sum((importe_firmado(datos.kind.value, s.amount) for s in datos.splits), CERO),
    )
    alcance.sesion.add(transaccion)
    await alcance.sesion.flush()

    if datos.splits:
        await _escribir_splits(
            alcance,
            transaccion,
            [
                (s.category_id, importe_firmado(datos.kind.value, s.amount), s.note)
                for s in datos.splits
            ],
        )

    for etiqueta in etiquetas:
        alcance.sesion.add(
            TransactionTag(
                household_id=alcance.household_id,
                transaction_id=transaccion.id,
                tag_id=etiqueta.id,
            )
        )
    await ajustar_uso_etiquetas(alcance, [e.id for e in etiquetas], 1)
    await ajustar_uso_comercio(alcance, transaccion.payee_id, 1, cuando=transaccion.booked_on)

    identificador = transaccion.id
    await alcance.sesion.commit()
    respuesta.headers["Location"] = f"{settings.api_prefix}/transactions/{identificador}"
    return await una_respuesta(alcance, identificador)


@router.get("/transactions/duplicates", summary="Candidatos a duplicado (F-34)")
async def listar_duplicados(
    alcance: Alcance,
    filtro: Annotated[DuplicadoFiltro, Query()],
) -> Pagina[GrupoDuplicadoRespuesta]:
    """Agrupa por importe y fecha ±N días. Se marcan, nunca se borran solos (RN-68)."""
    consulta = select(Transaction).where(
        Transaction.household_id == alcance.household_id,
        Transaction.kind != TipoMovimiento.TRANSFER.value,
    )
    if filtro.account_id:
        consulta = consulta.where(Transaction.account_id == filtro.account_id)
    if filtro.date_from:
        consulta = consulta.where(Transaction.booked_on >= filtro.date_from)
    if filtro.date_to:
        consulta = consulta.where(Transaction.booked_on <= filtro.date_to)
    consulta = consulta.options(selectinload(Transaction.splits)).order_by(
        func.abs(Transaction.amount), Transaction.booked_on, Transaction.id
    )
    filas = list((await alcance.sesion.execute(consulta)).unique().scalars())

    grupos: list[list[Transaction]] = []
    for fila in filas:
        for grupo in grupos:
            cabeza = grupo[0]
            if abs(cabeza.amount) != abs(fila.amount):
                continue
            if abs((cabeza.booked_on - fila.booked_on).days) > filtro.days:
                continue
            if cabeza.account_id != fila.account_id:
                continue
            grupo.append(fila)
            break
        else:
            grupos.append([fila])

    candidatos = [grupo for grupo in grupos if len(grupo) > 1]
    incluir = frozenset({"account", "category", "payee"})
    contexto = await contexto_de(alcance, [t for grupo in candidatos for t in grupo], incluir)

    resultado: list[GrupoDuplicadoRespuesta] = []
    for grupo in candidatos:
        mismo_comercio = len({t.payee_id for t in grupo}) == 1 and grupo[0].payee_id is not None
        misma_fecha = len({t.booked_on for t in grupo}) == 1
        de_importacion = any(t.import_fingerprint for t in grupo)
        if de_importacion:
            razon, puntuacion = "importacion", 0.9
        elif misma_fecha:
            razon, puntuacion = "mismo_importe_y_fecha", 1.0 if mismo_comercio else 0.85
        else:
            razon, puntuacion = "mismo_comercio", 0.7
        resultado.append(
            GrupoDuplicadoRespuesta(
                key=f"{abs(grupo[0].amount):.2f}:{grupo[0].booked_on.isoformat()}",
                score=puntuacion,
                reason=razon,  # type: ignore[arg-type]
                transactions=[respuesta_transaccion(t, contexto, incluir) for t in grupo],
            )
        )
    resultado.sort(key=lambda grupo: -grupo.score)
    pagina = resultado[filtro.desplazamiento : filtro.desplazamiento + filtro.size]
    return Pagina.crear(pagina, page=filtro.page, size=filtro.size, total=len(resultado))


@router.post("/transactions/bulk-categorize", summary="Asigna una temática en bloque")
async def categorizar_en_lote(
    alcance: AlcanceEscritura, datos: LoteCategorizarCrear
) -> ResultadoLoteRespuesta:
    """Solo toca transacciones simples: una repartida se edita por sus splits."""
    categoria = await tematica_del_hogar(alcance, datos.category_id)
    filas = list(
        (
            await alcance.sesion.execute(
                select(Transaction).where(
                    Transaction.household_id == alcance.household_id,
                    Transaction.id.in_(datos.ids),
                )
            )
        )
        .scalars()
        .all()
    )
    afectadas = 0
    omitidas = 0
    errores: list[dict[str, str]] = []
    for fila in filas:
        if fila.kind == TipoMovimiento.TRANSFER.value or fila.split_count > 0:
            omitidas += 1
            errores.append(
                {
                    "campo": str(fila.id),
                    "mensaje": "Una transferencia o un gasto repartido no se recategoriza así.",
                }
            )
            continue
        if fila.kind != categoria.kind:
            omitidas += 1
            errores.append(
                {"campo": str(fila.id), "mensaje": "La temática no corresponde a este tipo."}
            )
            continue
        fila.category_id = categoria.id
        fila.categorized_by = "user"
        afectadas += 1
    omitidas += len(datos.ids) - len(filas)
    await alcance.sesion.commit()
    return ResultadoLoteRespuesta(affected=afectadas, skipped=omitidas, errors=errores)


@router.post("/transactions/bulk-tag", summary="Añade o quita etiquetas en bloque")
async def etiquetar_en_lote(
    alcance: AlcanceEscritura, datos: LoteEtiquetarCrear
) -> ResultadoLoteRespuesta:
    await etiquetas_del_hogar(alcance, datos.add)
    ids = list(
        await alcance.sesion.scalars(
            select(Transaction.id).where(
                Transaction.household_id == alcance.household_id,
                Transaction.id.in_(datos.ids),
            )
        )
    )
    if datos.remove and ids:
        for etiqueta_id in datos.remove:
            borradas = await alcance.sesion.execute(
                delete(TransactionTag).where(
                    TransactionTag.household_id == alcance.household_id,
                    TransactionTag.transaction_id.in_(ids),
                    TransactionTag.tag_id == etiqueta_id,
                )
            )
            await ajustar_uso_etiquetas(alcance, [etiqueta_id], -(borradas.rowcount or 0))

    for etiqueta_id in datos.add:
        ya = set(
            await alcance.sesion.scalars(
                select(TransactionTag.transaction_id).where(
                    TransactionTag.transaction_id.in_(ids),
                    TransactionTag.tag_id == etiqueta_id,
                )
            )
        )
        nuevos = [identificador for identificador in ids if identificador not in ya]
        if nuevos:
            await alcance.sesion.execute(
                insert(TransactionTag).values(
                    [
                        {
                            "id": uuid.uuid4(),
                            "household_id": alcance.household_id,
                            "transaction_id": identificador,
                            "tag_id": etiqueta_id,
                        }
                        for identificador in nuevos
                    ]
                )
            )
            await ajustar_uso_etiquetas(alcance, [etiqueta_id], len(nuevos))

    await alcance.sesion.commit()
    return ResultadoLoteRespuesta(affected=len(ids), skipped=len(datos.ids) - len(ids))


@router.post("/transactions/bulk-delete", summary="Borra en bloque (máximo 500)")
async def borrar_en_lote(
    alcance: AlcanceEscritura, datos: LoteBorrarCrear
) -> ResultadoLoteRespuesta:
    filas = list(
        (
            await alcance.sesion.execute(
                select(Transaction).where(
                    Transaction.household_id == alcance.household_id,
                    Transaction.id.in_(datos.ids),
                )
            )
        )
        .scalars()
        .all()
    )
    de_factura = set(
        await alcance.sesion.scalars(
            select(Invoice.transaction_id).where(
                Invoice.transaction_id.in_([f.id for f in filas]),
                Invoice.status == "confirmed",
            )
        )
    )
    afectadas = 0
    omitidas = len(datos.ids) - len(filas)
    errores: list[dict[str, str]] = []
    for fila in filas:
        if fila.id in de_factura and not datos.force:
            omitidas += 1
            errores.append({"campo": str(fila.id), "mensaje": "Procede de una factura confirmada."})
            continue
        await _borrar_transaccion(alcance, fila)
        afectadas += 1
    await alcance.sesion.commit()
    return ResultadoLoteRespuesta(affected=afectadas, skipped=omitidas, errors=errores)


@router.get("/transactions/{transaccion_id}", summary="Detalle completo")
async def obtener_transaccion(alcance: Alcance, transaccion_id: uuid.UUID) -> TransaccionRespuesta:
    transaccion = await del_hogar(
        alcance,
        Transaction,
        transaccion_id,
        mensaje="La transacción no existe.",
        cargas=[selectinload(Transaction.splits)],
    )
    contexto = await contexto_de(alcance, [transaccion], TODO_INCLUIDO)
    return respuesta_transaccion(transaccion, contexto, TODO_INCLUIDO)


@router.patch("/transactions/{transaccion_id}", summary="Edición parcial")
async def editar_transaccion(
    alcance: AlcanceEscritura, transaccion_id: uuid.UUID, datos: TransaccionActualizar
) -> TransaccionRespuesta:
    """RN-16: cambiar el importe de una transacción repartida obliga a reenviar los splits."""
    transaccion = await del_hogar(
        alcance,
        Transaction,
        transaccion_id,
        mensaje="La transacción no existe.",
        cargas=[selectinload(Transaction.splits)],
    )
    if transaccion.kind == TipoMovimiento.TRANSFER.value:
        raise ReglaDeNegocio(
            "Una transferencia se edita con PATCH /transfers/{group_id}, no aquí.",
            codigo="transferencia_invalida",
        )

    campos = datos.model_dump(exclude_unset=True)
    kind = (datos.kind or TipoMovimiento(transaccion.kind)).value
    importe_actual = importe_visible(transaccion.kind, transaccion.amount)
    importe = datos.amount if "amount" in campos else importe_actual

    if "amount" in campos and transaccion.split_count > 0 and datos.splits is None:
        raise ReglaDeNegocio(
            "Al cambiar el importe de un gasto repartido hay que reenviar los splits.",
            codigo="splits_no_cuadran",
        )

    if "account_id" in campos and datos.account_id:
        transaccion.account_id = (await cuenta_del_hogar(alcance, datos.account_id)).id
    if "payee_id" in campos or "payee_name" in campos:
        anterior = transaccion.payee_id
        comercio = await resolver_comercio(alcance, datos.payee_id, datos.payee_name)
        transaccion.payee_id = comercio.id if comercio else None
        if anterior != transaccion.payee_id:
            await ajustar_uso_comercio(alcance, anterior, -1)
            await ajustar_uso_comercio(
                alcance, transaccion.payee_id, 1, cuando=datos.date or transaccion.booked_on
            )
    if "date" in campos and datos.date:
        transaccion.booked_on = datos.date
    if "description" in campos:
        transaccion.description = (datos.description or "").strip()
    if "note" in campos:
        transaccion.notes = datos.note
    if "status" in campos and datos.status:
        transaccion.status = datos.status.value
    kind_anterior = transaccion.kind
    if datos.kind is not None:
        transaccion.kind = kind

    # Cambiar el `kind` sin tocar el importe también cambia el signo guardado: un
    # gasto de 25 € que pasa a ingreso vale +25, no −25.
    nuevo_guardado = (
        importe_firmado(kind, importe) if ("amount" in campos or kind != kind_anterior) else None
    )

    if datos.splits is not None:
        if not datos.splits:
            raise ReglaDeNegocio(
                "Para deshacer el reparto usa DELETE /transactions/{id}/splits.",
                codigo="splits_no_cuadran",
            )
        _comprobar_suma([s.amount for s in datos.splits], importe)
        await _validar_tematicas_de_splits(alcance, [s.category_id for s in datos.splits], kind)
        # El importe viaja dentro de `_escribir_splits`: escribirlo aquí dejaría los
        # splits antiguos sin cuadrar y el invariante rechazaría el UPDATE.
        await alcance.sesion.flush()
        await _escribir_splits(
            alcance,
            transaccion,
            [(s.category_id, importe_firmado(kind, s.amount), s.note) for s in datos.splits],
            importe=nuevo_guardado,
        )
    elif "category_id" in campos and datos.category_id is not None:
        if transaccion.split_count > 0:
            raise ReglaDeNegocio(
                "Este gasto está repartido: la temática vive en cada split.",
                codigo="splits_no_cuadran",
            )
        categoria = await tematica_del_hogar(alcance, datos.category_id)
        if categoria.kind != kind:
            raise ReglaDeNegocio(f"«{categoria.name}» no corresponde a este tipo de movimiento.")
        transaccion.category_id = categoria.id
        transaccion.categorized_by = "user"
        if nuevo_guardado is not None:
            transaccion.amount = nuevo_guardado
    elif nuevo_guardado is not None:
        transaccion.amount = nuevo_guardado

    if datos.tag_ids is not None:
        etiquetas = await etiquetas_del_hogar(alcance, datos.tag_ids)
        previas = set(
            await alcance.sesion.scalars(
                select(TransactionTag.tag_id).where(TransactionTag.transaction_id == transaccion.id)
            )
        )
        deseadas = {e.id for e in etiquetas}
        sobran = previas - deseadas
        if sobran:
            await alcance.sesion.execute(
                delete(TransactionTag).where(
                    TransactionTag.transaction_id == transaccion.id,
                    TransactionTag.tag_id.in_(sobran),
                )
            )
            await ajustar_uso_etiquetas(alcance, sobran, -1)
        for etiqueta_id in deseadas - previas:
            alcance.sesion.add(
                TransactionTag(
                    household_id=alcance.household_id,
                    transaction_id=transaccion.id,
                    tag_id=etiqueta_id,
                )
            )
        await ajustar_uso_etiquetas(alcance, deseadas - previas, 1)

    identificador = transaccion.id
    await alcance.sesion.commit()
    return await una_respuesta(alcance, identificador)


async def _borrar_transaccion(alcance: AlcanceHogar, transaccion: Transaction) -> None:
    """Borra la transacción y, si es una pata de transferencia, también la otra (RN-24)."""
    await ajustar_uso_comercio(alcance, transaccion.payee_id, -1)
    etiquetas = list(
        await alcance.sesion.scalars(
            select(TransactionTag.tag_id).where(TransactionTag.transaction_id == transaccion.id)
        )
    )
    await ajustar_uso_etiquetas(alcance, etiquetas, -1)

    if transaccion.transfer_group_id:
        await alcance.sesion.execute(
            delete(Transaction).where(
                Transaction.household_id == alcance.household_id,
                Transaction.transfer_group_id == transaccion.transfer_group_id,
            )
        )
        return
    await alcance.sesion.delete(transaccion)


@router.delete(
    "/transactions/{transaccion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra la transacción y sus splits",
)
async def borrar_transaccion(
    alcance: AlcanceEscritura,
    transaccion_id: uuid.UUID,
    force: Annotated[
        bool, Query(description="Necesario si procede de una factura confirmada.")
    ] = False,
) -> Response:
    transaccion = (
        await alcance.sesion.execute(
            select(Transaction).where(
                Transaction.household_id == alcance.household_id,
                Transaction.id == transaccion_id,
            )
        )
    ).scalar_one_or_none()
    if transaccion is None:
        # `DELETE` es idempotente (§1.9): borrar algo ya borrado no es un error.
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    factura = (
        await alcance.sesion.execute(
            select(Invoice.id).where(
                Invoice.transaction_id == transaccion.id, Invoice.status == "confirmed"
            )
        )
    ).scalar_one_or_none()
    if factura is not None and not force:
        raise Conflicto(
            "Esta transacción viene de una factura confirmada. "
            "Anula la confirmación o repite la petición con ?force=true."
        )

    await _borrar_transaccion(alcance, transaccion)
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Reparto en splits (F-08)
# --------------------------------------------------------------------------- #


@router.get("/transactions/{transaccion_id}/splits", summary="Splits de una transacción")
async def listar_splits(alcance: Alcance, transaccion_id: uuid.UUID) -> list[SplitRespuesta]:
    transaccion = await del_hogar(
        alcance,
        Transaction,
        transaccion_id,
        mensaje="La transacción no existe.",
        cargas=[selectinload(Transaction.splits)],
    )
    contexto = await contexto_de(alcance, [transaccion], frozenset({"splits"}))
    return respuesta_transaccion(transaccion, contexto, frozenset({"splits"})).splits


@router.put("/transactions/{transaccion_id}/splits", summary="Sustituye el reparto completo")
async def sustituir_splits(
    alcance: AlcanceEscritura, transaccion_id: uuid.UUID, datos: SplitsSustituirCrear
) -> TransaccionRespuesta:
    """Idempotente. La suma tiene que cuadrar al céntimo (RN-15)."""
    transaccion = await del_hogar(
        alcance,
        Transaction,
        transaccion_id,
        mensaje="La transacción no existe.",
        cargas=[selectinload(Transaction.splits)],
    )
    if transaccion.kind == TipoMovimiento.TRANSFER.value:
        raise ReglaDeNegocio(
            "Una transferencia no se reparte entre temáticas.",
            codigo="transferencia_invalida",
        )
    visible = importe_visible(transaccion.kind, transaccion.amount)
    _comprobar_suma([s.amount for s in datos.splits], visible)
    await _validar_tematicas_de_splits(
        alcance, [s.category_id for s in datos.splits], transaccion.kind
    )
    await _escribir_splits(
        alcance,
        transaccion,
        [
            (s.category_id, importe_firmado(transaccion.kind, s.amount), s.note)
            for s in datos.splits
        ],
    )
    identificador = transaccion.id
    await alcance.sesion.commit()
    return await una_respuesta(alcance, identificador)


@router.delete("/transactions/{transaccion_id}/splits", summary="Deshace el reparto")
async def deshacer_splits(
    alcance: AlcanceEscritura,
    transaccion_id: uuid.UUID,
    category_id: Annotated[uuid.UUID, Query(description="Temática única que queda.")],
) -> TransaccionRespuesta:
    transaccion = await del_hogar(
        alcance,
        Transaction,
        transaccion_id,
        mensaje="La transacción no existe.",
        cargas=[selectinload(Transaction.splits)],
    )
    if transaccion.split_count == 0:
        raise ReglaDeNegocio("Esta transacción no está repartida.")
    categoria = await tematica_del_hogar(alcance, category_id)
    if categoria.kind != transaccion.kind:
        raise ReglaDeNegocio(f"«{categoria.name}» no corresponde a este tipo de movimiento.")
    await _escribir_splits(alcance, transaccion, [], tematica_final=categoria.id)
    await alcance.sesion.execute(
        update(Transaction).where(Transaction.id == transaccion.id).values(categorized_by="user")
    )
    identificador = transaccion.id
    await alcance.sesion.commit()
    return await una_respuesta(alcance, identificador)


@router.post("/transactions/{transaccion_id}/merge", summary="Fusiona un duplicado en esta")
async def fusionar_duplicado(
    alcance: AlcanceEscritura, transaccion_id: uuid.UUID, datos: TransaccionFusionCrear
) -> TransaccionRespuesta:
    """Se queda lo mejor de cada una y borra la duplicada."""
    if datos.duplicate_id == transaccion_id:
        raise ReglaDeNegocio("Una transacción no se puede fusionar consigo misma.")
    principal = await del_hogar(
        alcance,
        Transaction,
        transaccion_id,
        mensaje="La transacción no existe.",
        cargas=[selectinload(Transaction.splits)],
    )
    duplicada = await del_hogar(
        alcance, Transaction, datos.duplicate_id, mensaje="La transacción duplicada no existe."
    )
    if TipoMovimiento.TRANSFER.value in (principal.kind, duplicada.kind):
        raise ReglaDeNegocio(
            "Las patas de una transferencia no se fusionan.", codigo="transferencia_invalida"
        )

    campos = {
        "date": ("booked_on", "booked_on"),
        "amount": ("amount", "amount"),
        "category_id": ("category_id", "category_id"),
        "payee_id": ("payee_id", "payee_id"),
        "description": ("description", "description"),
        "note": ("notes", "notes"),
    }
    for campo, quien in datos.keep.items():
        destino = campos.get(campo)
        if destino is None or quien != "duplicate":
            continue
        if campo in ("category_id", "amount") and principal.split_count > 0:
            raise ReglaDeNegocio(
                "El gasto principal está repartido: reenvía sus splits antes de fusionar.",
                codigo="splits_no_cuadran",
            )
        setattr(principal, destino[0], getattr(duplicada, destino[1]))

    # Las etiquetas y los adjuntos de la duplicada se conservan siempre: perder
    # información en una fusión sería el peor de los resultados.
    etiquetas_duplicada = list(
        await alcance.sesion.scalars(
            select(TransactionTag.tag_id).where(TransactionTag.transaction_id == duplicada.id)
        )
    )
    ya = set(
        await alcance.sesion.scalars(
            select(TransactionTag.tag_id).where(TransactionTag.transaction_id == principal.id)
        )
    )
    for etiqueta_id in set(etiquetas_duplicada) - ya:
        alcance.sesion.add(
            TransactionTag(
                household_id=alcance.household_id,
                transaction_id=principal.id,
                tag_id=etiqueta_id,
            )
        )
    await alcance.sesion.execute(
        update(Attachment)
        .where(Attachment.transaction_id == duplicada.id)
        .values(transaction_id=principal.id)
    )
    principal.attachment_count += duplicada.attachment_count

    await _borrar_transaccion(alcance, duplicada)
    identificador = principal.id
    await alcance.sesion.commit()
    return await una_respuesta(alcance, identificador)


# --------------------------------------------------------------------------- #
# Adjuntos (F-21)
# --------------------------------------------------------------------------- #


def _tipo_por_firma(cabecera: bytes) -> tuple[str, str]:
    """RN-76: el tipo se decide por el contenido, nunca por el nombre ni la cabecera."""
    for firma, mime, extension in FIRMAS_ADJUNTO:
        if cabecera.startswith(firma):
            return mime, extension
    if cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise AppError(
        "Solo se admiten PDF y imágenes JPEG, PNG o WebP.",
        codigo="tipo_no_soportado",
        estado=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    )


def _nombre_saneado(nombre: str | None) -> str:
    """RN-77: el nombre original es solo metadato; nunca construye una ruta."""
    limpio = (nombre or "adjunto").replace("\\", "/").split("/")[-1].strip()
    limpio = "".join(caracter for caracter in limpio if caracter.isprintable())
    return limpio[:200] or "adjunto"


@router.get("/transactions/{transaccion_id}/attachments", summary="Adjuntos de la transacción")
async def listar_adjuntos(alcance: Alcance, transaccion_id: uuid.UUID) -> list[AdjuntoRespuesta]:
    await del_hogar(alcance, Transaction, transaccion_id, mensaje="La transacción no existe.")
    filas = await alcance.sesion.scalars(
        select(Attachment)
        .where(
            Attachment.household_id == alcance.household_id,
            Attachment.transaction_id == transaccion_id,
        )
        .order_by(Attachment.created_at)
    )
    return [respuesta_adjunto(adjunto) for adjunto in filas]


@router.post(
    "/transactions/{transaccion_id}/attachments",
    status_code=status.HTTP_201_CREATED,
    summary="Sube un adjunto (PDF o imagen)",
)
async def subir_adjunto(
    alcance: AlcanceEscritura,
    transaccion_id: uuid.UUID,
    fichero: Annotated[UploadFile, File(description="PDF, JPEG, PNG o WebP.")],
) -> AdjuntoRespuesta:
    """El límite de tamaño se aplica **mientras** se recibe el flujo (RN-75)."""
    transaccion = await del_hogar(
        alcance, Transaction, transaccion_id, mensaje="La transacción no existe."
    )

    resumen = hashlib.sha256()
    trozos: list[bytes] = []
    tamanyo = 0
    while True:
        trozo = await fichero.read(_TROZO)
        if not trozo:
            break
        tamanyo += len(trozo)
        if tamanyo > settings.max_upload_bytes:
            raise AppError(
                f"El fichero supera el máximo de {settings.max_upload_mb} MiB.",
                codigo="fichero_demasiado_grande",
                estado=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        resumen.update(trozo)
        trozos.append(trozo)
    if tamanyo == 0:
        raise AppError("El fichero está vacío.")

    contenido = b"".join(trozos)
    mime, extension = _tipo_por_firma(contenido[:16])

    directorio = settings.upload_dir / str(alcance.household_id)
    directorio.mkdir(parents=True, exist_ok=True)
    clave = f"{alcance.household_id}/{uuid.uuid4().hex}{extension}"
    async with aiofiles.open(settings.upload_dir / clave, "wb") as destino:
        await destino.write(contenido)

    adjunto = Attachment(
        household_id=alcance.household_id,
        transaction_id=transaccion.id,
        file_name=_nombre_saneado(fichero.filename),
        mime_type=mime,
        byte_size=tamanyo,
        sha256=resumen.hexdigest(),
        storage_key=clave,
        uploaded_by_id=alcance.usuario.id,
    )
    alcance.sesion.add(adjunto)
    transaccion.attachment_count += 1
    await alcance.sesion.commit()
    await alcance.sesion.refresh(adjunto)
    return respuesta_adjunto(adjunto)


@router.get("/attachments/{adjunto_id}", summary="Metadatos del adjunto")
async def obtener_adjunto(alcance: Alcance, adjunto_id: uuid.UUID) -> AdjuntoRespuesta:
    adjunto = await del_hogar(alcance, Attachment, adjunto_id, mensaje="El adjunto no existe.")
    return respuesta_adjunto(adjunto)


@router.get("/attachments/{adjunto_id}/content", summary="Descarga el fichero original")
async def descargar_adjunto(
    alcance: Alcance,
    adjunto_id: uuid.UUID,
    disposition: Annotated[str, Query(pattern="^(inline|attachment)$")] = "inline",
) -> FileResponse:
    adjunto = await del_hogar(alcance, Attachment, adjunto_id, mensaje="El adjunto no existe.")
    ruta = settings.upload_dir / adjunto.storage_key
    if not ruta.is_file():
        raise NoEncontrado("El fichero ya no está en el almacén.")
    # El nombre viaja entre comillas y saneado: nunca se usa para abrir nada.
    return FileResponse(
        ruta,
        media_type=adjunto.mime_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{_nombre_saneado(adjunto.file_name)}"'
        },
    )


@router.delete(
    "/attachments/{adjunto_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra el adjunto y su fichero",
)
async def borrar_adjunto(alcance: AlcanceEscritura, adjunto_id: uuid.UUID) -> Response:
    adjunto = (
        await alcance.sesion.execute(
            select(Attachment).where(
                Attachment.household_id == alcance.household_id, Attachment.id == adjunto_id
            )
        )
    ).scalar_one_or_none()
    if adjunto is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    ruta = settings.upload_dir / adjunto.storage_key
    if adjunto.transaction_id:
        await alcance.sesion.execute(
            update(Transaction)
            .where(Transaction.id == adjunto.transaction_id)
            .values(attachment_count=func.greatest(Transaction.attachment_count - 1, 0))
        )
    await alcance.sesion.delete(adjunto)
    await alcance.sesion.commit()
    # El fichero se borra **después** del COMMIT: si la transacción fallara, el
    # metadato seguiría vivo y el fichero ya no estaría.
    ruta.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# `PaginacionActual` se usa en los listados que no tienen esquema de filtros
# propio (los de presupuestos y objetivos); se reexporta para que esos módulos no
# tengan que importar `deps` por separado.
__all__ = [
    "PaginacionActual",
    "aplicar_orden",
    "contar",
    "contexto_de",
    "cuenta_del_hogar",
    "del_hogar",
    "etiquetas_del_hogar",
    "importe_firmado",
    "importe_visible",
    "patron",
    "ref_comercio",
    "ref_cuenta",
    "ref_tematica",
    "resolver_comercio",
    "respuesta_transaccion",
    "router",
    "sin_transferencias",
    "subarbol_de",
    "tematica_del_hogar",
    "texto_plano",
    "una_respuesta",
]
