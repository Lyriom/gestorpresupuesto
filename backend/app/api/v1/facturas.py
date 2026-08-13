"""Facturas en PDF: subida, procesado, revisión y confirmación.

Implementa §3.12, la máquina de estados de §3.13 y las reglas RN-41…RN-50. Es el
flujo diferencial del producto, y todo el contrato está construido sobre una idea:
`extraer_factura()` no es fiable al 100 %, así que **es imposible guardar sin
revisar**.

    POST /invoices ─▶ processing ─▶ pending_review ─▶ (revisión) ─▶ confirmed
                                 └▶ failed ─▶ alta manual ────────┘
                                                    confirmed ─▶ unconfirm ─▶ pending_review

La extracción tarda segundos, así que no ocurre dentro de la petición: se valida
el PDF, se guarda, se responde `202` y el trabajo se hace en un `BackgroundTask`
con `run_in_threadpool` (pdfplumber y Tesseract son CPU, no I/O). El estado vive
en la base de datos —`invoices.status`— y no en memoria, para que sobreviva a un
reinicio del contenedor (§10).
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
import uuid as uuidlib
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, insert, or_, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, verificar_csrf
from app.api.v1.productos import (
    Emparejamiento,
    _u8,
    ahora,
    aprender_alias,
    cargado,
    crear_producto,
    emparejar,
    normalizada_con_tamanyo,
    ref_comercio,
    ref_producto,
    refrescar_producto,
    registrar_observacion,
    sugerencias_para,
    ultima_observacion,
)
from app.core.config import settings
from app.core.errors import AppError, Conflicto, NoEncontrado, ReglaDeNegocio
from app.models.alerta import Alert
from app.models.categoria import Category
from app.models.comercio import Payee
from app.models.cuenta import Account
from app.models.factura import ExtractionTemplate, Invoice, InvoiceLine
from app.models.producto import Product, ProductPrice
from app.models.transaccion import Transaction, TransactionSplit
from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comun import Pagina
from app.schemas.factura import (
    CONFIANZA_BAJA,
    ESTADOS_REVISABLES,
    EstadoFactura,
    FacturaActualizar,
    FacturaConfirmarCrear,
    FacturaConfirmarResultadoRespuesta,
    FacturaDuplicadaRespuesta,
    FacturaEstadoRespuesta,
    FacturaFiltro,
    FacturaReprocesarCrear,
    FacturaRespuesta,
    LineaFacturaActualizar,
    LineaFacturaCrear,
    LineaFacturaRespuesta,
    LineaRevisionCrear,
    LineasFacturaRespuesta,
    LineasFacturaSustituirCrear,
    NormalizadaRespuesta,
    VincularProductoCrear,
)
from app.schemas.producto import AlertaPrecioRespuesta
from app.services import formato
from app.services.extraccion_pdf import (
    TOLERANCIA,
    FacturaExtraida,
    LineaExtraida,
    PdfInvalido,
    extraer_factura,
    validar_pdf,
)
from app.services.normalizacion import clave_agrupacion, normalizar_descripcion, sin_acentos
from app.services.precios import variacion as variacion_de_precio

logger = logging.getLogger("app.facturas")

router = APIRouter(dependencies=[Depends(verificar_csrf)])

#: Ritmo de sondeo de `GET /invoices/{id}/status` (§3.13).
SEGUNDOS_DE_ESPERA = 2

#: Tamaño del trozo con el que se lee el `multipart`: el contador de bytes se
#: comprueba en cada vuelta, así que un fichero enorme se corta al entrar.
TROZO = 64 * 1024

#: Nombres reservados de Windows: un fichero llamado `CON.pdf` da problemas al
#: descargarlo, aunque aquí la ruta la calcule siempre el servidor.
RESERVADOS_WINDOWS = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{n}" for n in range(1, 10)),
        *(f"lpt{n}" for n in range(1, 10)),
    }
)

CENTIMO = Decimal("0.01")
CERO = Decimal("0.00")

#: Formas jurídicas que se quitan al normalizar el emisor para detectar duplicados.
_FORMAS_JURIDICAS = re.compile(
    r"\b(s\.?\s?l\.?\s?u?|s\.?\s?a\.?\s?u?|sociedad limitada|sociedad anonima|"
    r"cooperativa|coop|sccl|cb|scp)\b"
)


# --------------------------------------------------------------------------- #
# Ficheros: nombre saneado y ruta calculada por el servidor (RN-77, §8.3)
# --------------------------------------------------------------------------- #


def sanear_nombre(nombre: str | None) -> str:
    """Deja el nombre del cliente en un metadato inofensivo.

    Nunca se usa para construir la ruta en disco: eso lo hace `ruta_de()`. Aquí
    solo se normaliza a NFKC, se recorta al juego de caracteres seguro y se
    eliminan los saltos de directorio y los nombres reservados.
    """
    base = unicodedata.normalize("NFKC", nombre or "")
    base = base.replace("\x00", "").replace("..", "").replace("/", " ").replace("\\", " ")
    base = re.sub(r"[^A-Za-z0-9 ._-]", "", base)
    base = re.sub(r"\s+", " ", base).strip(" .")[:120]
    raiz = base.split(".")[0].lower()
    if not base or raiz in RESERVADOS_WINDOWS:
        base = "factura.pdf"
    if not base.lower().endswith(".pdf"):
        base = f"{base}.pdf"
    return base


async def _plantilla_del_hogar(alcance: AlcanceHogar, template_id: uuidlib.UUID | None) -> None:
    """RN-01: la plantilla es del hogar o de la instalación, nunca de otro hogar.

    `extraction_templates.household_id` es nulable (las plantillas de serie son de
    la instalación), así que esta tabla no puede tener clave ajena compuesta: si
    aquí no se comprueba la tenencia, no la comprueba nadie.
    """
    if template_id is None:
        return
    existe = await alcance.sesion.scalar(
        select(ExtractionTemplate.id).where(
            ExtractionTemplate.id == template_id,
            or_(
                ExtractionTemplate.household_id.is_(None),
                ExtractionTemplate.household_id == alcance.household_id,
            ),
        )
    )
    if existe is None:
        raise NoEncontrado("Esa plantilla de extracción no existe.")


def ruta_de(clave: str) -> Path:
    """Ruta absoluta de un fichero guardado, comprobada contra la raíz."""
    raiz = settings.upload_dir.resolve()
    destino = (raiz / clave).resolve()
    if raiz not in destino.parents:
        # Solo puede pasar si alguien manipula `storage_key` en la base de datos.
        raise NoEncontrado("El fichero de esta factura no está disponible.")
    return destino


def clave_de_almacenamiento(usuario_id: uuidlib.UUID, momento: date) -> str:
    """`{user_id}/{aaaa}/{mm}/{uuid4}.pdf`: el nombre del cliente no interviene."""
    return f"{usuario_id}/{momento.year:04d}/{momento.month:02d}/{uuidlib.uuid4()}.pdf"


async def _leer_flujo(fichero: UploadFile) -> tuple[bytes, str]:
    """Lee el `multipart` por trozos abortando en cuanto se pasa del límite.

    Leer primero y comprobar después significa que un fichero de 2 GiB ya te ha
    reventado la memoria (§8.3).
    """
    digestor = hashlib.sha256()
    trozos: list[bytes] = []
    leidos = 0
    while trozo := await fichero.read(TROZO):
        leidos += len(trozo)
        if leidos > settings.max_upload_bytes:
            raise AppError(
                f"El fichero pesa más de {settings.max_upload_mb} MB.",
                codigo="fichero_demasiado_grande",
                estado=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        digestor.update(trozo)
        trozos.append(trozo)
    return b"".join(trozos), digestor.hexdigest()


# --------------------------------------------------------------------------- #
# Utilidades de la factura
# --------------------------------------------------------------------------- #


def normalizar_emisor(texto: str | None) -> str:
    """Emisor sin acentos, en minúsculas y sin forma jurídica (RN-45)."""
    if not texto:
        return ""
    plano = sin_acentos(texto).lower()
    plano = _FORMAS_JURIDICAS.sub(" ", plano)
    return re.sub(r"[^a-z0-9 ]", " ", plano).strip()


def normalizar_numero(texto: str | None) -> str:
    """Número de factura sin espacios ni separadores (RN-45)."""
    if not texto:
        return ""
    return re.sub(r"[^a-z0-9]", "", texto.lower())


async def _factura_o_404(alcance: AlcanceHogar, invoice_id: uuidlib.UUID) -> Invoice:
    factura = (
        await alcance.sesion.execute(
            select(Invoice).where(
                Invoice.household_id == alcance.household_id, Invoice.id == invoice_id
            )
        )
    ).scalar_one_or_none()
    if factura is None:
        raise NoEncontrado("Esta factura no existe.")
    return factura


def _exigir_revisable(factura: Invoice) -> None:
    """RN-49: solo se corrige en `pending_review` y en `failed`."""
    if factura.status not in {estado.value for estado in ESTADOS_REVISABLES}:
        if factura.status == EstadoFactura.CONFIRMED.value:
            raise Conflicto(
                "Esta factura ya está confirmada. Deshaz la confirmación para poder editarla.",
                codigo="factura_no_revisable",
            )
        raise Conflicto(
            "La factura todavía se está procesando o ya se ha descartado.",
            codigo="factura_no_revisable",
        )


async def _lineas_de(alcance: AlcanceHogar, factura: Invoice) -> list[InvoiceLine]:
    return list(
        (
            await alcance.sesion.execute(
                select(InvoiceLine)
                .where(
                    InvoiceLine.household_id == alcance.household_id,
                    InvoiceLine.invoice_id == factura.id,
                )
                .order_by(InvoiceLine.line_number)
            )
        ).scalars()
    )


def suma_de(lineas: list[InvoiceLine]) -> Decimal:
    """Suma de las líneas que van a generar gasto (no excluidas)."""
    return sum((linea.line_total or CERO for linea in lineas if not linea.excluded), CERO).quantize(
        CENTIMO
    )


def cuadra(factura: Invoice, lineas: list[InvoiceLine]) -> bool:
    """RN-42: contra el total con tolerancia de 0,02 €, o contra la base imponible."""
    if factura.total_amount is None:
        return False
    suma = suma_de(lineas)
    if abs(suma - factura.total_amount) <= TOLERANCIA:
        return True
    return factura.taxable_base is not None and abs(suma - factura.taxable_base) <= TOLERANCIA


# --------------------------------------------------------------------------- #
# Procesado en segundo plano
# --------------------------------------------------------------------------- #


def _motor(sesion: AsyncSession) -> AsyncEngine:
    """El motor de la sesión de la petición, para abrir otra en segundo plano."""
    enlace = sesion.bind
    if isinstance(enlace, AsyncEngine):
        return enlace
    from app.db.session import engine

    return engine


async def procesar_factura(
    motor: AsyncEngine,
    invoice_id: uuidlib.UUID,
    household_id: uuidlib.UUID,
    *,
    forzar_ocr: bool = False,
    conservar_editadas: bool = False,
) -> None:
    """Extrae el PDF fuera de la petición y deja el resultado en la factura.

    Se abre una sesión propia porque la de la petición ya está cerrada cuando esto
    corre, y el trabajo de CPU va a un hilo para no bloquear el bucle de eventos.
    """
    async with AsyncSession(bind=motor, expire_on_commit=False) as sesion:
        await sesion.execute(
            text("SELECT set_config('app.household_id', :valor, true)"),
            {"valor": str(household_id)},
        )
        factura = (
            await sesion.execute(
                select(Invoice).where(
                    Invoice.household_id == household_id, Invoice.id == invoice_id
                )
            )
        ).scalar_one_or_none()
        if factura is None:
            return

        factura.processing_started_at = ahora()
        await sesion.commit()

        try:
            datos = ruta_de(factura.storage_key).read_bytes()
            extraida = await run_in_threadpool(
                extraer_factura,
                datos,
                max_bytes=settings.max_upload_bytes,
                max_paginas=settings.max_pdf_pages,
                ocr_habilitado=settings.ocr_enabled or forzar_ocr,
                idiomas_ocr=settings.ocr_languages,
            )
        except (PdfInvalido, OSError) as exc:
            factura.status = EstadoFactura.FAILED.value
            factura.error_message = str(exc) or "No se ha podido leer el PDF."
            factura.processed_at = ahora()
            await sesion.commit()
            return
        except Exception:  # noqa: BLE001 - el fallo no puede dejar la factura colgada
            logger.exception("Fallo inesperado extrayendo la factura %s", invoice_id)
            factura.status = EstadoFactura.FAILED.value
            factura.error_message = (
                "No se ha podido interpretar el PDF. Introduce los datos a mano."
            )
            factura.processed_at = ahora()
            await sesion.commit()
            return

        await _aplicar_extraccion(sesion, factura, extraida, conservar_editadas=conservar_editadas)
        await sesion.commit()


async def _aplicar_extraccion(
    sesion: AsyncSession,
    factura: Invoice,
    extraida: FacturaExtraida,
    *,
    conservar_editadas: bool,
) -> None:
    """Vuelca `FacturaExtraida` en la factura y sus líneas."""
    # Nivel 2 de duplicado (RN-45): mismo emisor y mismo número. Se resuelve
    # **antes** de escribir esos dos campos porque marcar la fila como duplicada
    # es justo lo que la exime del índice único; al revés, el UPDATE chocaría.
    factura.duplicate_of_id = await _duplicado_logico(
        sesion,
        factura.household_id,
        factura.id,
        issuer_tax_id=extraida.nif_emisor,
        numero=extraida.numero,
    )
    factura.issuer_name = extraida.emisor
    factura.issuer_tax_id = extraida.nif_emisor
    factura.invoice_number = extraida.numero
    factura.issued_on = extraida.fecha
    factura.taxable_base = extraida.base_imponible
    factura.tax_amount = extraida.impuestos
    factura.total_amount = extraida.total
    factura.currency = extraida.moneda
    factura.extraction_method = extraida.metodo
    factura.page_count = extraida.paginas
    factura.confidence = Decimal(str(round(extraida.confianza, 3)))
    factura.warnings = list(extraida.avisos)
    factura.raw_text = extraida.texto_crudo or None
    factura.processed_at = ahora()
    factura.error_message = None

    if factura.payee_id is None:
        comercio = await _buscar_comercio(sesion, factura)
        factura.payee_id = comercio.id if comercio else None

    conservadas: list[InvoiceLine] = []
    if conservar_editadas:
        conservadas = list(
            (
                await sesion.execute(
                    select(InvoiceLine).where(
                        InvoiceLine.invoice_id == factura.id,
                        InvoiceLine.was_edited.is_(True),
                    )
                )
            ).scalars()
        )
    await sesion.execute(
        delete(InvoiceLine).where(
            InvoiceLine.invoice_id == factura.id,
            InvoiceLine.id.notin_([linea.id for linea in conservadas] or [uuidlib.uuid4()]),
        )
    )
    await sesion.flush()

    numero = len(conservadas)
    for extraida_linea in extraida.lineas:
        numero += 1
        sesion.add(await _linea_desde_extraccion(sesion, factura, extraida_linea, numero))
    await sesion.flush()

    if extraida.total is None and not extraida.lineas:
        factura.status = EstadoFactura.FAILED.value
        factura.error_message = (
            "No se ha podido interpretar el PDF: no se ha encontrado ni el total ni "
            "las líneas. Introduce los datos a mano."
        )
    else:
        factura.status = EstadoFactura.PENDING_REVIEW.value


async def _linea_desde_extraccion(
    sesion: AsyncSession,
    factura: Invoice,
    extraida: LineaExtraida,
    numero: int,
) -> InvoiceLine:
    """Traduce `LineaExtraida` a fila, resolviendo ya el emparejado en cascada."""
    normalizada = extraida.normalizada or normalizar_descripcion(extraida.descripcion)
    emparejado = await emparejar(sesion, factura.household_id, normalizada)
    return InvoiceLine(
        household_id=factura.household_id,
        invoice_id=factura.id,
        line_number=numero,
        raw_description=extraida.descripcion[:300],
        quantity=extraida.cantidad or None,
        unit=_u8(extraida.unidad),
        unit_price=extraida.precio_unitario,
        line_total=extraida.total,
        confidence=Decimal(str(round(extraida.confianza, 3))),
        normalized_description=normalizada.canonica,
        brand_guess=normalizada.marca_probable,
        size_value=normalizada.tamanyo_valor,
        size_unit=_u8(normalizada.tamanyo_unidad),
        product_code=normalizada.codigo,
        grouping_key=clave_agrupacion(normalizada),
        product_id=emparejado.product_id if emparejado else None,
        match_method=emparejado.metodo if emparejado else "none",
        match_score=emparejado.puntuacion if emparejado else None,
    )


async def _buscar_comercio(sesion: AsyncSession, factura: Invoice) -> Payee | None:
    """El emisor como entidad: primero por NIF, que es fiable; luego por nombre."""
    if factura.issuer_tax_id:
        comercio = (
            await sesion.execute(
                select(Payee).where(
                    Payee.household_id == factura.household_id,
                    Payee.tax_id == factura.issuer_tax_id,
                    Payee.merged_into_id.is_(None),
                )
            )
        ).scalar_one_or_none()
        if comercio is not None:
            return comercio
    normalizado = normalizar_emisor(factura.issuer_name)
    if not normalizado:
        return None
    return (
        await sesion.execute(
            select(Payee).where(
                Payee.household_id == factura.household_id,
                Payee.normalized_name == normalizado,
                Payee.merged_into_id.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _crear_comercio(alcance: AlcanceHogar, factura: Invoice) -> Payee | None:
    """Da de alta el emisor de la factura si aún no estaba en el catálogo."""
    nombre = (factura.issuer_name or "").strip()
    if not nombre:
        return None
    comercio = Payee(
        household_id=alcance.household_id,
        name=nombre[:200],
        normalized_name=normalizar_emisor(nombre),
        kind="supplier",
        tax_id=factura.issuer_tax_id,
    )
    alcance.sesion.add(comercio)
    await alcance.sesion.flush()
    return comercio


async def _duplicado_logico(
    sesion: AsyncSession,
    household_id: uuidlib.UUID,
    invoice_id: uuidlib.UUID,
    *,
    issuer_tax_id: str | None,
    numero: str | None,
) -> uuidlib.UUID | None:
    """Otra factura con el mismo emisor y el mismo número (RN-45, nivel 2)."""
    if not (issuer_tax_id and numero):
        return None
    with sesion.no_autoflush:
        return (
            await sesion.execute(
                select(Invoice.id)
                .where(
                    Invoice.household_id == household_id,
                    Invoice.id != invoice_id,
                    Invoice.issuer_tax_id == issuer_tax_id,
                    Invoice.invoice_number == numero,
                    Invoice.status != EstadoFactura.FAILED.value,
                    Invoice.duplicate_of_id.is_(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Respuestas
# --------------------------------------------------------------------------- #


def _normalizada_respuesta(linea: InvoiceLine) -> NormalizadaRespuesta | None:
    if not linea.normalized_description:
        return None
    return NormalizadaRespuesta(
        canonical=linea.normalized_description,
        brand_guess=linea.brand_guess,
        size_value=linea.size_value,
        size_unit=linea.size_unit,
        code=linea.product_code,
    )


@dataclass(slots=True)
class Sugerencia:
    """Lo que el backend puede proponer para una línea concreta."""

    producto: Product | None = None
    puntuacion: float | None = None
    categoria: Category | None = None
    ultimo_precio: Decimal | None = None
    ultima_fecha: date | None = None
    variacion: float | None = None


def respuesta_linea(
    linea: InvoiceLine,
    *,
    producto: Product | None = None,
    categoria: Category | None = None,
    sugerencia: Sugerencia | None = None,
) -> LineaFacturaRespuesta:
    avisos: list[str] = []
    if linea.confidence < Decimal(str(CONFIANZA_BAJA)):
        avisos.append("La lectura de esta línea es dudosa: compruébala.")
    if (
        linea.quantity is not None
        and linea.unit_price is not None
        and linea.line_total is not None
        and abs((linea.quantity * linea.unit_price).quantize(CENTIMO) - linea.line_total)
        > TOLERANCIA
    ):
        avisos.append("Cantidad × precio no da el importe de la línea.")

    return LineaFacturaRespuesta(
        id=linea.id,
        line_number=linea.line_number,
        description=linea.raw_description,
        quantity=linea.quantity,
        unit=linea.unit,
        unit_price=linea.unit_price,
        total=linea.line_total,
        confidence=float(linea.confidence),
        normalized=_normalizada_respuesta(linea),
        is_edited=linea.was_edited,
        is_excluded=linea.excluded,
        is_product=bool(linea.grouping_key),
        warnings=avisos,
        category_id=linea.category_id,
        category=_ref_categoria(categoria),
        product_id=linea.product_id,
        product=ref_producto(producto) if producto else None,
        suggested_product=None,
        suggested_category=_ref_categoria(sugerencia.categoria if sugerencia else None),
        last_unit_price=sugerencia.ultimo_precio if sugerencia else None,
        last_seen_on=sugerencia.ultima_fecha if sugerencia else None,
        change_pct=sugerencia.variacion if sugerencia else None,
    )


def _ref_categoria(categoria: Category | None) -> CategoriaRefRespuesta | None:
    if categoria is None:
        return None
    return CategoriaRefRespuesta(id=categoria.id, name=categoria.name, color=categoria.color_hex)


async def respuesta_factura(
    alcance: AlcanceHogar,
    factura: Invoice,
    *,
    incluir_lineas: bool = False,
) -> FacturaRespuesta:
    await cargado(alcance.sesion, factura)
    lineas = await _lineas_de(alcance, factura)
    suma = suma_de(lineas)
    descuadre = None
    if factura.total_amount is not None and not cuadra(factura, lineas):
        descuadre = (suma - factura.total_amount).quantize(CENTIMO)
    comercio = None
    if factura.payee_id:
        comercio = await alcance.sesion.get(Payee, factura.payee_id)

    detalle: list[LineaFacturaRespuesta] = []
    if incluir_lineas:
        productos, categorias = await _relacionados(alcance, lineas)
        detalle = [
            respuesta_linea(
                linea,
                producto=productos.get(linea.product_id),
                categoria=categorias.get(linea.category_id),
            )
            for linea in lineas
        ]

    return FacturaRespuesta(
        id=factura.id,
        created_at=factura.created_at,
        updated_at=factura.updated_at,
        status=EstadoFactura(factura.status),
        issuer=factura.issuer_name,
        issuer_tax_id=factura.issuer_tax_id,
        number=factura.invoice_number,
        date=factura.issued_on,
        taxable_base=factura.taxable_base,
        tax_amount=factura.tax_amount,
        total=factura.total_amount,
        currency=factura.currency,
        extraction_method=factura.extraction_method,  # type: ignore[arg-type]
        pages=factura.page_count,
        confidence=float(factura.confidence),
        warnings=list(factura.warnings or []),
        lines_count=len(lineas),
        lines_sum=suma,
        total_mismatch=descuadre,
        low_confidence_lines=sum(
            1 for linea in lineas if linea.confidence < Decimal(str(CONFIANZA_BAJA))
        ),
        filename=factura.file_name,
        size_bytes=factura.byte_size,
        checksum=factura.content_sha256,
        file_url=f"{settings.api_prefix}/invoices/{factura.id}/file",
        payee_id=factura.payee_id,
        payee=ref_comercio(comercio),
        account_id=None,
        transaction_id=factura.transaction_id,
        template_id=factura.extraction_template_id,
        duplicate_of_id=factura.duplicate_of_id,
        default_category_id=None,
        note=factura.notes,
        uploaded_at=factura.created_at,
        processed_at=factura.processed_at,
        reviewed_at=factura.reviewed_at,
        confirmed_at=factura.reviewed_at,
        error=factura.error_message,
        lines=detalle,
    )


async def _relacionados(
    alcance: AlcanceHogar, lineas: list[InvoiceLine]
) -> tuple[dict[Any, Product], dict[Any, Category]]:
    """Productos y temáticas de las líneas, en dos consultas y no en 2N."""
    product_ids = [linea.product_id for linea in lineas if linea.product_id]
    category_ids = [linea.category_id for linea in lineas if linea.category_id]
    productos: dict[Any, Product] = {}
    categorias: dict[Any, Category] = {}
    if product_ids:
        productos = {
            producto.id: producto
            for producto in (
                await alcance.sesion.execute(select(Product).where(Product.id.in_(product_ids)))
            ).scalars()
        }
    if category_ids:
        categorias = {
            categoria.id: categoria
            for categoria in (
                await alcance.sesion.execute(select(Category).where(Category.id.in_(category_ids)))
            ).scalars()
        }
    return productos, categorias


# --------------------------------------------------------------------------- #
# Subida
# --------------------------------------------------------------------------- #


@router.post(
    "/invoices",
    tags=["invoices"],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sube una factura en PDF",
)
async def subir(
    alcance: AlcanceEscritura,
    tareas: BackgroundTasks,
    respuesta: Response,
    fichero: Annotated[UploadFile, File(alias="fichero")],
    account_id: Annotated[uuidlib.UUID | None, Form()] = None,
    payee_id: Annotated[uuidlib.UUID | None, Form()] = None,
    template_id: Annotated[uuidlib.UUID | None, Form()] = None,
) -> FacturaRespuesta:
    """Valida el PDF de verdad, lo guarda y encola la extracción (RN-43, RN-44).

    El `content-type` que declara el navegador no decide nada: se mira la firma
    del fichero, su tamaño y su número de páginas.
    """
    datos, huella = await _leer_flujo(fichero)
    if not datos:
        raise ReglaDeNegocio("El fichero está vacío.", codigo="pdf_invalido")
    if not datos.lstrip()[:5].startswith(b"%PDF-"):
        raise AppError(
            "El fichero no es un PDF. Sube el PDF original de la factura.",
            codigo="tipo_no_soportado",
            estado=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    try:
        # Se cuentan las páginas con un tope holgado para poder distinguir «PDF
        # ilegible» de «PDF con demasiadas páginas», que son dos errores distintos.
        paginas = await run_in_threadpool(validar_pdf, datos, settings.max_upload_bytes, 100_000)
    except PdfInvalido as exc:
        raise ReglaDeNegocio(str(exc), codigo="pdf_invalido") from exc
    if paginas > settings.max_pdf_pages:
        raise ReglaDeNegocio(
            f"El PDF tiene {paginas} páginas y el máximo son {settings.max_pdf_pages}.",
            codigo="pdf_demasiadas_paginas",
        )

    # RN-44: el mismo fichero no se sube dos veces. No es un error: es la
    # respuesta correcta, con 200 en lugar de 202.
    existente = (
        await alcance.sesion.execute(
            select(Invoice).where(
                Invoice.household_id == alcance.household_id,
                Invoice.content_sha256 == huella,
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        respuesta.status_code = status.HTTP_200_OK
        return await respuesta_factura(alcance, existente)

    if payee_id is not None:
        comercio = await alcance.sesion.get(Payee, payee_id)
        if comercio is None or comercio.household_id != alcance.household_id:
            raise NoEncontrado("Ese comercio no existe.")
    if account_id is not None:
        cuenta = await alcance.sesion.get(Account, account_id)
        if cuenta is None or cuenta.household_id != alcance.household_id:
            raise NoEncontrado("Esa cuenta no existe.")
    await _plantilla_del_hogar(alcance, template_id)

    clave = clave_de_almacenamiento(alcance.usuario.id, date.today())
    factura = Invoice(
        household_id=alcance.household_id,
        payee_id=payee_id,
        extraction_template_id=template_id,
        status=EstadoFactura.PROCESSING.value,
        source="upload",
        page_count=paginas,
        file_name=sanear_nombre(fichero.filename),
        storage_key=clave,
        byte_size=len(datos),
        content_sha256=huella,
        uploaded_by_id=alcance.usuario.id,
    )
    alcance.sesion.add(factura)
    await alcance.sesion.flush()

    destino = ruta_de(clave)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    await alcance.sesion.commit()

    tareas.add_task(procesar_factura, _motor(alcance.sesion), factura.id, alcance.household_id)
    return await respuesta_factura(alcance, factura)


@router.get("/invoices", tags=["invoices"], summary="Bandeja de facturas")
async def listar(
    alcance: Alcance, filtro: Annotated[FacturaFiltro, Query()]
) -> Pagina[FacturaRespuesta]:
    consulta = select(Invoice).where(Invoice.household_id == alcance.household_id)
    if filtro.status:
        consulta = consulta.where(Invoice.status.in_([estado.value for estado in filtro.status]))
    if filtro.payee_id:
        consulta = consulta.where(Invoice.payee_id == filtro.payee_id)
    if filtro.date_from:
        consulta = consulta.where(Invoice.issued_on >= filtro.date_from)
    if filtro.date_to:
        consulta = consulta.where(Invoice.issued_on <= filtro.date_to)
    if filtro.min_total is not None:
        consulta = consulta.where(Invoice.total_amount >= filtro.min_total)
    if filtro.max_total is not None:
        consulta = consulta.where(Invoice.total_amount <= filtro.max_total)
    if filtro.has_transaction is not None:
        consulta = consulta.where(
            Invoice.transaction_id.is_not(None)
            if filtro.has_transaction
            else Invoice.transaction_id.is_(None)
        )
    if filtro.confidence_below is not None:
        consulta = consulta.where(Invoice.confidence < Decimal(str(filtro.confidence_below)))
    if filtro.q:
        patron = f"%{filtro.q.lower()}%"
        consulta = consulta.where(
            or_(
                func.lower(Invoice.issuer_name).like(patron),
                func.lower(Invoice.invoice_number).like(patron),
                func.lower(Invoice.file_name).like(patron),
            )
        )

    total = (
        await alcance.sesion.execute(select(func.count()).select_from(consulta.subquery()))
    ).scalar_one()
    columnas = {
        "uploaded_at": Invoice.created_at,
        "date": Invoice.issued_on,
        "total": Invoice.total_amount,
        "confidence": Invoice.confidence,
        "issuer": Invoice.issuer_name,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is not None:
            consulta = consulta.order_by(columna.desc() if descendente else columna.asc())

    facturas = list(
        (
            await alcance.sesion.execute(
                consulta.order_by(Invoice.id).offset(filtro.desplazamiento).limit(filtro.size)
            )
        ).scalars()
    )
    incluir = "lines" in filtro.include
    filas = [
        await respuesta_factura(alcance, factura, incluir_lineas=incluir) for factura in facturas
    ]
    return Pagina.crear(filas, page=filtro.page, size=filtro.size, total=total)


@router.get("/invoices/{invoice_id}", tags=["invoices"], summary="Cabecera de la factura")
async def detalle(
    alcance: Alcance,
    invoice_id: uuidlib.UUID,
    include: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI copia el valor
) -> FacturaRespuesta:
    factura = await _factura_o_404(alcance, invoice_id)
    return await respuesta_factura(alcance, factura, incluir_lineas="lines" in include)


@router.get(
    "/invoices/{invoice_id}/status",
    tags=["invoices"],
    response_model=FacturaEstadoRespuesta,
    summary="Sondeo del procesado",
)
async def estado(
    alcance: Alcance,
    invoice_id: uuidlib.UUID,
    respuesta: Response,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Any:
    """Una sola fila, con `ETag` y `Retry-After`: sondear no cuesta nada."""
    factura = await _factura_o_404(alcance, invoice_id)
    sello = f'"{factura.id}-{factura.status}-{int(factura.updated_at.timestamp() * 1_000_000)}"'
    if if_none_match and sello in {valor.strip() for valor in if_none_match.split(",")}:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": sello})

    cuantas, dudosas = (
        await alcance.sesion.execute(
            select(
                func.count(InvoiceLine.id),
                func.count(InvoiceLine.id).filter(
                    InvoiceLine.confidence < Decimal(str(CONFIANZA_BAJA))
                ),
            ).where(InvoiceLine.invoice_id == factura.id)
        )
    ).one()

    procesando = factura.status == EstadoFactura.PROCESSING.value
    respuesta.headers["ETag"] = sello
    respuesta.headers["Cache-Control"] = "no-cache"
    if procesando:
        respuesta.headers["Retry-After"] = str(SEGUNDOS_DE_ESPERA)
    return FacturaEstadoRespuesta(
        id=factura.id,
        status=EstadoFactura(factura.status),
        progress=10 if procesando else 100,
        extraction_method=factura.extraction_method,  # type: ignore[arg-type]
        pages=factura.page_count,
        confidence=float(factura.confidence),
        lines_count=cuantas,
        low_confidence_lines=dudosas,
        warnings=list(factura.warnings or []),
        error=factura.error_message,
        retry_after_seconds=SEGUNDOS_DE_ESPERA if procesando else None,
    )


@router.get("/invoices/{invoice_id}/file", tags=["invoices"], summary="Descarga el PDF original")
async def descargar(
    alcance: Alcance,
    invoice_id: uuidlib.UUID,
    disposition: Annotated[str, Query(pattern="^(inline|attachment)$")] = "attachment",
) -> FileResponse:
    """El `Content-Type` lo fija el servidor, nunca el cliente (§8.3)."""
    factura = await _factura_o_404(alcance, invoice_id)
    ruta = ruta_de(factura.storage_key)
    if not ruta.is_file():
        raise NoEncontrado("El fichero de esta factura ya no está en el disco.")
    return FileResponse(
        ruta,
        media_type="application/pdf",
        filename=factura.file_name,
        content_disposition_type=disposition,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.get(
    "/invoices/{invoice_id}/duplicates", tags=["invoices"], summary="Candidatas a duplicado"
)
async def duplicados(alcance: Alcance, invoice_id: uuidlib.UUID) -> list[FacturaDuplicadaRespuesta]:
    """RN-45: emisor + número + fecha + total, y las coincidencias parciales."""
    factura = await _factura_o_404(alcance, invoice_id)
    return await _candidatas_duplicado(alcance, factura)


async def _candidatas_duplicado(
    alcance: AlcanceHogar, factura: Invoice
) -> list[FacturaDuplicadaRespuesta]:
    otras = list(
        (
            await alcance.sesion.execute(
                select(Invoice).where(
                    Invoice.household_id == alcance.household_id,
                    Invoice.id != factura.id,
                    Invoice.status != EstadoFactura.DISCARDED.value,
                )
            )
        ).scalars()
    )
    emisor = normalizar_emisor(factura.issuer_name)
    numero = normalizar_numero(factura.invoice_number)
    candidatas: list[FacturaDuplicadaRespuesta] = []
    for otra in otras:
        if otra.content_sha256 == factura.content_sha256:
            motivo, confianza = "checksum", 1.0
        elif (
            emisor
            and numero
            and normalizar_emisor(otra.issuer_name) == emisor
            and normalizar_numero(otra.invoice_number) == numero
            and otra.issued_on == factura.issued_on
            and otra.total_amount == factura.total_amount
        ):
            motivo, confianza = "issuer_number_date_total", 0.95
        elif (
            factura.total_amount is not None
            and otra.total_amount == factura.total_amount
            and otra.issued_on == factura.issued_on
        ):
            motivo, confianza = "total_date", 0.6
        elif numero and normalizar_numero(otra.invoice_number) == numero:
            motivo, confianza = "number_only", 0.4
        else:
            continue
        candidatas.append(
            FacturaDuplicadaRespuesta(
                invoice_id=otra.id,
                issuer=otra.issuer_name,
                number=otra.invoice_number,
                date=otra.issued_on,
                total=otra.total_amount,
                status=EstadoFactura(otra.status),
                match_reason=motivo,  # type: ignore[arg-type]
                confidence=confianza,
            )
        )
    return sorted(candidatas, key=lambda una: una.confidence, reverse=True)


# --------------------------------------------------------------------------- #
# Revisión: líneas y sugerencias
# --------------------------------------------------------------------------- #


async def _sugerencias_de(
    alcance: AlcanceHogar,
    factura: Invoice,
    lineas: list[InvoiceLine],
) -> dict[uuidlib.UUID, Sugerencia]:
    """Producto sugerido, temática recordada, último precio y variación (§3.13)."""
    comercio_defecto: Category | None = None
    if factura.payee_id:
        comercio = await alcance.sesion.get(Payee, factura.payee_id)
        if comercio is not None and comercio.default_category_id:
            comercio_defecto = await alcance.sesion.get(Category, comercio.default_category_id)

    resultado: dict[uuidlib.UUID, Sugerencia] = {}
    for linea in lineas:
        sugerencia = Sugerencia(categoria=comercio_defecto)
        producto: Product | None = None

        if linea.product_id:
            producto = await alcance.sesion.get(Product, linea.product_id)
        else:
            normalizada = normalizada_con_tamanyo(
                linea.raw_description,
                size_value=linea.size_value,
                size_unit=linea.size_unit,
            )
            candidatos = await sugerencias_para(
                alcance.sesion,
                alcance.household_id,
                normalizada,
                limite=1,
                minimo=70.0,
            )
            if candidatos:
                producto, puntuacion = candidatos[0]
                sugerencia.producto = producto
                sugerencia.puntuacion = round(puntuacion, 2)

        if producto is not None:
            # F-17: la temática del producto, y si no la última que se le puso.
            if producto.category_id:
                sugerencia.categoria = await alcance.sesion.get(Category, producto.category_id)
            else:
                recordada = await _ultima_tematica(alcance, producto.id, factura.id)
                if recordada is not None:
                    sugerencia.categoria = recordada
            ultima = await ultima_observacion(
                alcance.sesion, alcance.household_id, producto.id, payee_id=factura.payee_id
            )
            if ultima is None:
                ultima = await ultima_observacion(alcance.sesion, alcance.household_id, producto.id)
            if ultima is not None:
                sugerencia.ultimo_precio = ultima.unit_price
                sugerencia.ultima_fecha = ultima.priced_on
                if linea.unit_price is not None:
                    cambio = variacion_de_precio(ultima.unit_price, linea.unit_price)
                    if cambio is not None:
                        sugerencia.variacion = float((cambio * 100).quantize(CENTIMO))
        resultado[linea.id] = sugerencia
    return resultado


async def _ultima_tematica(
    alcance: AlcanceHogar, product_id: uuidlib.UUID, excluir_factura: uuidlib.UUID
) -> Category | None:
    """La temática que se usó la última vez para ese producto (F-17)."""
    categoria_id = (
        await alcance.sesion.execute(
            select(InvoiceLine.category_id)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .where(
                InvoiceLine.household_id == alcance.household_id,
                InvoiceLine.product_id == product_id,
                InvoiceLine.category_id.is_not(None),
                InvoiceLine.invoice_id != excluir_factura,
            )
            .order_by(Invoice.issued_on.desc().nullslast(), InvoiceLine.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if categoria_id is None:
        return None
    return await alcance.sesion.get(Category, categoria_id)


def _motivos_de_bloqueo(
    factura: Invoice, lineas: list[InvoiceLine], *, sin_tematica: int
) -> list[str]:
    """Lo que impide confirmar, en la frase que verá el usuario."""
    motivos: list[str] = []
    if factura.status not in {estado.value for estado in ESTADOS_REVISABLES}:
        motivos.append("La factura no está en revisión.")
    if factura.issued_on is None:
        motivos.append("Falta la fecha de la factura.")
    if factura.total_amount is None:
        motivos.append("Falta el importe total de la factura.")
    vivas = [linea for linea in lineas if not linea.excluded]
    if not vivas:
        motivos.append("No hay ninguna línea que registrar.")
    if sin_tematica:
        motivos.append(
            f"Hay {sin_tematica} líneas sin temática: asígnales una o elige una por defecto."
        )
    if factura.total_amount is not None and not cuadra(factura, lineas):
        motivos.append(
            f"Las líneas suman {formato.euros(suma_de(lineas))} y el total de la factura es "
            f"{formato.euros(factura.total_amount)}."
        )
    return motivos


async def _respuesta_lineas(
    alcance: AlcanceHogar,
    factura: Invoice,
    *,
    con_sugerencias: bool = True,
) -> LineasFacturaRespuesta:
    lineas = await _lineas_de(alcance, factura)
    productos, categorias = await _relacionados(alcance, lineas)
    sugerencias = await _sugerencias_de(alcance, factura, lineas) if con_sugerencias else {}

    detalle: list[LineaFacturaRespuesta] = []
    for linea in lineas:
        sugerencia = sugerencias.get(linea.id)
        fila = respuesta_linea(
            linea,
            producto=productos.get(linea.product_id),
            categoria=categorias.get(linea.category_id),
            sugerencia=sugerencia,
        )
        if sugerencia and sugerencia.producto is not None and sugerencia.puntuacion is not None:
            from app.schemas.producto import ProductoSugerenciaRespuesta

            fila.suggested_product = ProductoSugerenciaRespuesta(
                product=ref_producto(sugerencia.producto),
                score=sugerencia.puntuacion,
                last_unit_price=sugerencia.ultimo_precio,
            )
        detalle.append(fila)

    suma = suma_de(lineas)
    descuadre = None
    if factura.total_amount is not None and not cuadra(factura, lineas):
        descuadre = (suma - factura.total_amount).quantize(CENTIMO)
    # Una línea sin temática solo bloquea si tampoco hay ninguna sugerida: la
    # confirmación puede tomar la sugerida o la que se elija por defecto.
    huerfanas = sum(
        1
        for linea in lineas
        if not linea.excluded
        and linea.category_id is None
        and (sugerencias.get(linea.id) is None or sugerencias[linea.id].categoria is None)
    )
    motivos = _motivos_de_bloqueo(factura, lineas, sin_tematica=huerfanas)
    return LineasFacturaRespuesta(
        invoice_id=factura.id,
        status=EstadoFactura(factura.status),
        total=factura.total_amount,
        taxable_base=factura.taxable_base,
        lines_sum=suma,
        total_mismatch=descuadre,
        can_confirm=not motivos,
        blocking_reasons=motivos,
        warnings=list(factura.warnings or []),
        low_confidence_lines=sum(
            1 for linea in lineas if linea.confidence < Decimal(str(CONFIANZA_BAJA))
        ),
        lines=detalle,
    )


@router.get("/invoices/{invoice_id}/lines", tags=["invoices"], summary="Líneas para revisar")
async def lineas(
    alcance: Alcance,
    invoice_id: uuidlib.UUID,
    include_suggestions: bool = True,
) -> LineasFacturaRespuesta:
    """Cada línea con lo que dio el extractor **más** lo que el backend sugiere."""
    factura = await _factura_o_404(alcance, invoice_id)
    return await _respuesta_lineas(alcance, factura, con_sugerencias=include_suggestions)


@router.patch("/invoices/{invoice_id}", tags=["invoices"], summary="Corrige la cabecera")
async def actualizar(
    alcance: AlcanceEscritura, invoice_id: uuidlib.UUID, datos: FacturaActualizar
) -> FacturaRespuesta:
    factura = await _factura_o_404(alcance, invoice_id)
    _exigir_revisable(factura)
    campos = datos.model_dump(exclude_unset=True)

    correspondencia = {
        "issuer": "issuer_name",
        "issuer_tax_id": "issuer_tax_id",
        "number": "invoice_number",
        "date": "issued_on",
        "taxable_base": "taxable_base",
        "tax_amount": "tax_amount",
        "total": "total_amount",
        "currency": "currency",
        "note": "notes",
    }
    for entrada, columna in correspondencia.items():
        if entrada in campos:
            setattr(factura, columna, campos.pop(entrada))

    if "payee_id" in campos:
        nuevo = campos.pop("payee_id")
        if nuevo is not None:
            comercio = await alcance.sesion.get(Payee, nuevo)
            if comercio is None or comercio.household_id != alcance.household_id:
                raise NoEncontrado("Ese comercio no existe.")
        factura.payee_id = nuevo
    if campos.get("payee_name"):
        factura.issuer_name = campos["payee_name"]
        comercio = await _buscar_comercio(alcance.sesion, factura)
        if comercio is None:
            comercio = await _crear_comercio(alcance, factura)
        factura.payee_id = comercio.id if comercio else factura.payee_id
    campos.pop("payee_name", None)
    campos.pop("account_id", None)
    if "default_category_id" in campos:
        # No hay columna propia: la temática por defecto de la revisión se
        # propaga a las líneas que aún no tienen ninguna.
        defecto = campos.pop("default_category_id")
        if defecto is not None:
            await _validar_categoria(alcance, defecto)
            for linea in await _lineas_de(alcance, factura):
                if linea.category_id is None:
                    linea.category_id = defecto

    if factura.status == EstadoFactura.FAILED.value and factura.total_amount is not None:
        # Alta manual sobre una factura ilegible: vuelve al camino normal (§3.13).
        factura.status = EstadoFactura.PENDING_REVIEW.value
        factura.error_message = None
    factura.duplicate_of_id = await _duplicado_logico(
        alcance.sesion,
        alcance.household_id,
        factura.id,
        issuer_tax_id=factura.issuer_tax_id,
        numero=factura.invoice_number,
    )
    await alcance.sesion.commit()
    return await respuesta_factura(alcance, factura, incluir_lineas=True)


async def _validar_categoria(alcance: AlcanceHogar, category_id: uuidlib.UUID) -> Category:
    categoria = await alcance.sesion.get(Category, category_id)
    if categoria is None or categoria.household_id != alcance.household_id:
        raise NoEncontrado("Esa temática no existe.")
    if categoria.archived_at is not None:
        raise ReglaDeNegocio("Esa temática está archivada.")
    return categoria


def _recalcular(linea: InvoiceLine, tocados: set[str]) -> None:
    """RN-41: deduce el hueco que falte con la lógica de `LineaExtraida`.

    Si se han tocado la cantidad o el precio y no el total, el total se vuelve a
    calcular; si se ha tocado el total y no el precio, se recalcula el precio. En
    lo demás manda `completar()`, que es la única definición de esta aritmética.
    """
    if {"quantity", "unit_price"} & tocados and "total" not in tocados:
        if linea.quantity is not None and linea.unit_price is not None:
            # HALF_UP y no el redondeo bancario del contexto: 10 kWh a 0,2165 €
            # son 2,17 €, no 2,16 €, y es lo que hace la base al guardar.
            linea.line_total = (linea.quantity * linea.unit_price).quantize(
                CENTIMO, rounding=ROUND_HALF_UP
            )
    elif (
        "total" in tocados
        and "unit_price" not in tocados
        and linea.quantity
        and linea.line_total is not None
    ):
        linea.unit_price = (linea.line_total / linea.quantity).quantize(Decimal("0.0001"))

    calculo = LineaExtraida(
        descripcion=linea.raw_description,
        cantidad=linea.quantity,
        unidad=linea.unit,
        precio_unitario=linea.unit_price,
        total=linea.line_total,
    )
    calculo.completar()
    linea.quantity = calculo.cantidad or None
    linea.unit_price = calculo.precio_unitario
    linea.line_total = calculo.total
    linea.was_edited = True
    linea.is_reviewed = True
    linea.confidence = Decimal("1.000")


def _renormalizar(linea: InvoiceLine) -> None:
    normalizada = normalizar_descripcion(linea.raw_description)
    linea.normalized_description = normalizada.canonica
    linea.brand_guess = normalizada.marca_probable
    linea.size_value = normalizada.tamanyo_valor
    linea.size_unit = _u8(normalizada.tamanyo_unidad)
    linea.product_code = normalizada.codigo
    linea.grouping_key = clave_agrupacion(normalizada)


def _marcar_no_producto(linea: InvoiceLine) -> None:
    """RN-48: la línea es un concepto, no un producto.

    El modelo no tiene columna `is_product`: se representa vaciando
    `grouping_key`, que es precisamente la identidad de producto de la línea, y
    desenlazando el catálogo.
    """
    linea.grouping_key = ""
    linea.product_id = None
    linea.match_method = "none"
    linea.match_score = None


async def _linea_o_404(
    alcance: AlcanceHogar, factura: Invoice, line_id: uuidlib.UUID
) -> InvoiceLine:
    linea = (
        await alcance.sesion.execute(
            select(InvoiceLine).where(
                InvoiceLine.household_id == alcance.household_id,
                InvoiceLine.invoice_id == factura.id,
                InvoiceLine.id == line_id,
            )
        )
    ).scalar_one_or_none()
    if linea is None:
        raise NoEncontrado("Esa línea no existe en esta factura.")
    return linea


@router.patch(
    "/invoices/{invoice_id}/lines/{line_id}", tags=["invoices"], summary="Corrige una línea"
)
async def actualizar_linea(
    alcance: AlcanceEscritura,
    invoice_id: uuidlib.UUID,
    line_id: uuidlib.UUID,
    datos: LineaFacturaActualizar,
) -> LineaFacturaRespuesta:
    factura = await _factura_o_404(alcance, invoice_id)
    _exigir_revisable(factura)
    linea = await _linea_o_404(alcance, factura, line_id)
    campos = datos.model_dump(exclude_unset=True)

    if "description" in campos and campos["description"]:
        linea.raw_description = campos["description"][:300]
        _renormalizar(linea)
    if "quantity" in campos:
        linea.quantity = campos["quantity"] or None
    if "unit" in campos:
        linea.unit = _u8(campos["unit"])
    if "unit_price" in campos:
        linea.unit_price = campos["unit_price"]
    if "total" in campos:
        linea.line_total = campos["total"]
    if "is_excluded" in campos:
        linea.excluded = bool(campos["is_excluded"])
    if "is_product" in campos:
        if campos["is_product"]:
            _renormalizar(linea)
        else:
            # RN-48: un concepto (potencia contratada, impuestos, portes) no toca
            # el catálogo. Se marca vaciando su clave de agrupación.
            _marcar_no_producto(linea)
    if "category_id" in campos:
        if campos["category_id"] is not None:
            await _validar_categoria(alcance, campos["category_id"])
        linea.category_id = campos["category_id"]
    if "product_id" in campos:
        if campos["product_id"] is not None:
            producto = await alcance.sesion.get(Product, campos["product_id"])
            if producto is None or producto.household_id != alcance.household_id:
                raise NoEncontrado("Ese producto no existe.")
            linea.product_id = producto.id
            linea.match_method = "manual"
            linea.match_score = Decimal("100.00")
        else:
            linea.product_id = None
            linea.match_method = "none"
            linea.match_score = None

    _recalcular(linea, set(campos))
    await alcance.sesion.commit()
    producto = await alcance.sesion.get(Product, linea.product_id) if linea.product_id else None
    categoria = await alcance.sesion.get(Category, linea.category_id) if linea.category_id else None
    return respuesta_linea(linea, producto=producto, categoria=categoria)


@router.put("/invoices/{invoice_id}/lines", tags=["invoices"], summary="Guarda toda la revisión")
async def sustituir_lineas(
    alcance: AlcanceEscritura,
    invoice_id: uuidlib.UUID,
    datos: LineasFacturaSustituirCrear,
) -> LineasFacturaRespuesta:
    """Idempotente: sustituye el conjunto de líneas de una sola vez."""
    factura = await _factura_o_404(alcance, invoice_id)
    _exigir_revisable(factura)
    existentes = {linea.id: linea for linea in await _lineas_de(alcance, factura)}

    # La unicidad de (invoice_id, line_number) es DEFERRABLE justo para esto:
    # renumerar todas las líneas dentro de la misma transacción.
    await alcance.sesion.execute(text("SET CONSTRAINTS ALL DEFERRED"))

    conservadas: set[uuidlib.UUID] = set()
    for posicion, entrada in enumerate(datos.lines, start=1):
        if entrada.id is not None and entrada.id in existentes:
            linea = existentes[entrada.id]
            conservadas.add(linea.id)
        else:
            linea = InvoiceLine(
                household_id=alcance.household_id,
                invoice_id=factura.id,
                line_number=posicion,
                raw_description=entrada.description[:300],
                confidence=Decimal("1.000"),
                normalized_description="",
                grouping_key="",
            )
            alcance.sesion.add(linea)
        await _aplicar_revision(alcance, linea, entrada, posicion)

    for identificador, linea in existentes.items():
        if identificador not in conservadas:
            await alcance.sesion.delete(linea)
    await alcance.sesion.commit()
    return await _respuesta_lineas(alcance, factura)


async def _aplicar_revision(
    alcance: AlcanceHogar, linea: InvoiceLine, entrada: LineaRevisionCrear, posicion: int
) -> None:
    linea.line_number = posicion
    linea.raw_description = entrada.description[:300]
    linea.quantity = entrada.quantity or None
    linea.unit = _u8(entrada.unit)
    linea.unit_price = entrada.unit_price
    linea.line_total = entrada.total
    linea.excluded = entrada.is_excluded
    if entrada.category_id is not None:
        await _validar_categoria(alcance, entrada.category_id)
    linea.category_id = entrada.category_id
    if entrada.product_id is not None and entrada.is_product:
        producto = await alcance.sesion.get(Product, entrada.product_id)
        if producto is None or producto.household_id != alcance.household_id:
            raise NoEncontrado("Ese producto no existe.")
        linea.product_id = producto.id
        linea.match_method = "manual"
        linea.match_score = Decimal("100.00")
    else:
        linea.product_id = None
        linea.match_method = "none"
        linea.match_score = None
    _renormalizar(linea)
    if not entrada.is_product:
        _marcar_no_producto(linea)
    _recalcular(linea, {"quantity", "unit_price", "total"})


@router.post(
    "/invoices/{invoice_id}/lines",
    tags=["invoices"],
    status_code=status.HTTP_201_CREATED,
    summary="Añade una línea a mano",
)
async def crear_linea(
    alcance: AlcanceEscritura, invoice_id: uuidlib.UUID, datos: LineaFacturaCrear
) -> LineaFacturaRespuesta:
    factura = await _factura_o_404(alcance, invoice_id)
    _exigir_revisable(factura)
    ultimo = (
        await alcance.sesion.execute(
            select(func.coalesce(func.max(InvoiceLine.line_number), 0)).where(
                InvoiceLine.invoice_id == factura.id
            )
        )
    ).scalar_one()
    linea = InvoiceLine(
        household_id=alcance.household_id,
        invoice_id=factura.id,
        line_number=(datos.position or ultimo) + 1,
        raw_description=datos.description[:300],
        quantity=datos.quantity or None,
        unit=_u8(datos.unit),
        unit_price=datos.unit_price,
        line_total=datos.total,
        confidence=Decimal("1.000"),
        normalized_description="",
        grouping_key="",
        excluded=datos.is_excluded,
        category_id=datos.category_id,
    )
    if datos.category_id is not None:
        await _validar_categoria(alcance, datos.category_id)
    if datos.product_id is not None and datos.is_product:
        producto = await alcance.sesion.get(Product, datos.product_id)
        if producto is None or producto.household_id != alcance.household_id:
            raise NoEncontrado("Ese producto no existe.")
        linea.product_id = producto.id
        linea.match_method = "manual"
        linea.match_score = Decimal("100.00")
    alcance.sesion.add(linea)
    _renormalizar(linea)
    if not datos.is_product:
        _marcar_no_producto(linea)
    _recalcular(linea, {"quantity", "unit_price", "total"})
    await alcance.sesion.commit()
    return respuesta_linea(linea)


@router.delete(
    "/invoices/{invoice_id}/lines/{line_id}",
    tags=["invoices"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Descarta una línea mal leída",
)
async def borrar_linea(
    alcance: AlcanceEscritura, invoice_id: uuidlib.UUID, line_id: uuidlib.UUID
) -> Response:
    factura = await _factura_o_404(alcance, invoice_id)
    _exigir_revisable(factura)
    linea = await _linea_o_404(alcance, factura, line_id)
    await alcance.sesion.delete(linea)
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/invoices/{invoice_id}/lines/{line_id}/link-product",
    tags=["invoices"],
    summary="Vincula la línea con el catálogo",
)
async def vincular_producto(
    alcance: AlcanceEscritura,
    invoice_id: uuidlib.UUID,
    line_id: uuidlib.UUID,
    datos: VincularProductoCrear,
) -> LineaFacturaRespuesta:
    """Vincular guarda el alias: la próxima factura se reconoce sola (§3.13)."""
    factura = await _factura_o_404(alcance, invoice_id)
    _exigir_revisable(factura)
    linea = await _linea_o_404(alcance, factura, line_id)

    if datos.product_id is not None:
        producto = await alcance.sesion.get(Product, datos.product_id)
        if producto is None or producto.household_id != alcance.household_id:
            raise NoEncontrado("Ese producto no existe.")
    else:
        assert datos.new_product is not None  # noqa: S101 - lo garantiza el esquema
        producto = await crear_producto(alcance, datos.new_product)

    linea.product_id = producto.id
    linea.match_method = "manual"
    linea.match_score = Decimal("100.00")
    linea.is_reviewed = True

    if datos.remember_alias and linea.normalized_description:
        await aprender_alias(
            alcance,
            producto.id,
            linea.normalized_description,
            bruto=linea.raw_description,
            payee_id=factura.payee_id,
            metodo="manual",
        )
    if datos.set_default_category and linea.category_id:
        producto.category_id = linea.category_id
    await alcance.sesion.commit()
    categoria = await alcance.sesion.get(Category, linea.category_id) if linea.category_id else None
    return respuesta_linea(linea, producto=producto, categoria=categoria)


@router.delete(
    "/invoices/{invoice_id}/lines/{line_id}/link-product",
    tags=["invoices"],
    summary="Desvincula la línea del producto",
)
async def desvincular_producto(
    alcance: AlcanceEscritura, invoice_id: uuidlib.UUID, line_id: uuidlib.UUID
) -> LineaFacturaRespuesta:
    factura = await _factura_o_404(alcance, invoice_id)
    _exigir_revisable(factura)
    linea = await _linea_o_404(alcance, factura, line_id)
    linea.product_id = None
    linea.match_method = "none"
    linea.match_score = None
    await alcance.sesion.commit()
    return respuesta_linea(linea)


# --------------------------------------------------------------------------- #
# Confirmación (RN-42, RN-45, RN-46, RN-47, RN-48)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Reparto:
    """Un split por temática, ya cuadrado con el total de la factura."""

    category_id: uuidlib.UUID
    importe: Decimal
    invoice_line_id: uuidlib.UUID | None


def _repartir(
    factura: Invoice,
    lineas: list[InvoiceLine],
    defecto: uuidlib.UUID | None,
) -> list[Reparto]:
    """Un split por línea categorizada, más el resto (el IVA) en la temática por defecto.

    El invariante de `transactions` exige que los splits sumen **exactamente** el
    importe de la transacción, así que la diferencia entre la suma de las líneas y
    el total de la factura —normalmente los impuestos— se imputa explícitamente.
    """
    total = factura.total_amount or CERO
    repartos: list[Reparto] = []
    for linea in lineas:
        if linea.excluded or not linea.line_total:
            continue
        categoria = linea.category_id or defecto
        if categoria is None:
            raise ReglaDeNegocio(
                "Hay líneas sin temática y no has indicado una por defecto.",
                codigo="datos_invalidos",
            )
        repartos.append(
            Reparto(category_id=categoria, importe=-linea.line_total, invoice_line_id=linea.id)
        )

    resto = (-total - sum((reparto.importe for reparto in repartos), CERO)).quantize(CENTIMO)
    if resto != CERO:
        categoria = defecto or repartos[0].category_id
        repartos.append(Reparto(category_id=categoria, importe=resto, invoice_line_id=None))
    return repartos


@router.post("/invoices/{invoice_id}/confirm", tags=["invoices"], summary="Confirma la revisión")
async def confirmar(
    alcance: AlcanceEscritura,
    invoice_id: uuidlib.UUID,
    datos: FacturaConfirmarCrear,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> FacturaConfirmarResultadoRespuesta:
    """Todo en una sola transacción de base de datos (RN-47).

    Transacción de gasto + splits por temática + observaciones de precio + alias
    aprendidos + productos creados + alerta de subida. Si falla un paso, no queda
    nada a medias.
    """
    factura = await _factura_o_404(alcance, invoice_id)

    if factura.status == EstadoFactura.CONFIRMED.value:
        if idempotency_key and factura.transaction_id:
            # RN-46: un reintento con la misma clave devuelve el resultado, no un error.
            return await _resultado_confirmacion(alcance, factura, [], 0, 0, 0, [])
        raise Conflicto(
            "Esta factura ya se ha confirmado. Deshaz la confirmación si quieres repetirla.",
            codigo="factura_ya_confirmada",
        )
    if factura.status not in {estado.value for estado in ESTADOS_REVISABLES}:
        raise Conflicto(
            "La factura no está en revisión: no se puede confirmar.",
            codigo="factura_ya_confirmada",
        )

    cuenta = await alcance.sesion.get(Account, datos.account_id)
    if cuenta is None or cuenta.household_id != alcance.household_id:
        raise NoEncontrado("Esa cuenta no existe.")
    if datos.default_category_id is not None:
        await _validar_categoria(alcance, datos.default_category_id)

    lineas = await _lineas_de(alcance, factura)
    fecha = datos.date or factura.issued_on
    if fecha is None:
        raise ReglaDeNegocio(
            "La factura no tiene fecha: corrígela antes de confirmar.", codigo="datos_invalidos"
        )
    if factura.total_amount is None or factura.total_amount == CERO:
        raise ReglaDeNegocio(
            "La factura no tiene importe total: corrígelo antes de confirmar.",
            codigo="datos_invalidos",
        )

    descuadre = None
    if not cuadra(factura, lineas):
        descuadre = (suma_de(lineas) - factura.total_amount).quantize(CENTIMO)
        if not datos.allow_total_mismatch:
            raise ReglaDeNegocio(
                f"Las líneas suman {formato.euros(suma_de(lineas))} y el total es "
                f"{formato.euros(factura.total_amount)}. Revisa las líneas o confirma "
                "aceptando el descuadre.",
                codigo="total_no_cuadra",
            )

    # RN-45: duplicado por emisor + número + fecha + total contra una confirmada.
    if not datos.ignore_duplicate:
        candidatas = await _candidatas_duplicado(alcance, factura)
        bloqueantes = [
            candidata
            for candidata in candidatas
            if candidata.match_reason in {"checksum", "issuer_number_date_total"}
            and candidata.status == EstadoFactura.CONFIRMED
        ]
        if bloqueantes:
            raise Conflicto(
                "Esta factura ya está registrada.",
                codigo="factura_duplicada",
                detalles=[
                    {"campo": "invoice_id", "mensaje": str(candidata.invoice_id)}
                    for candidata in bloqueantes
                ],
            )

    if datos.payee_id is not None:
        comercio = await alcance.sesion.get(Payee, datos.payee_id)
        if comercio is None or comercio.household_id != alcance.household_id:
            raise NoEncontrado("Ese comercio no existe.")
        factura.payee_id = comercio.id
    elif factura.payee_id is None:
        comercio = await _buscar_comercio(alcance.sesion, factura) or await _crear_comercio(
            alcance, factura
        )
        factura.payee_id = comercio.id if comercio else None

    defecto = datos.default_category_id
    # F-17: la temática recordada del producto se aplica a las líneas que no
    # tienen ninguna, y queda guardada para la próxima factura.
    sugeridas = await _sugerencias_de(alcance, factura, lineas)
    for linea in lineas:
        if linea.excluded or linea.category_id is not None:
            continue
        sugerida = sugeridas.get(linea.id)
        if sugerida is not None and sugerida.categoria is not None:
            linea.category_id = sugerida.categoria.id
        elif defecto is not None:
            # Se escribe en la línea, no solo en el split: así la próxima factura
            # del mismo producto ya llega con su temática recordada (F-17).
            linea.category_id = defecto

    repartos = _repartir(factura, lineas, defecto) if datos.create_splits else []
    importe = -factura.total_amount

    if datos.transaction_id is not None:
        transaccion = await alcance.sesion.get(Transaction, datos.transaction_id)
        if transaccion is None or transaccion.household_id != alcance.household_id:
            raise NoEncontrado("Esa transacción no existe.")
        repartos = []
    else:
        transaccion = await _crear_transaccion(
            alcance,
            factura,
            cuenta=cuenta,
            fecha=fecha,
            importe=importe,
            repartos=repartos,
            defecto=defecto,
            nota=datos.note,
        )

    registrados: list[ProductPrice] = []
    alertas: list[AlertaPrecioRespuesta] = []
    creados = 0
    enlazados = 0
    if datos.register_prices:
        registrados, alertas, creados, enlazados = await _registrar_precios(
            alcance, factura, lineas, fecha
        )

    factura.transaction_id = transaccion.id
    factura.status = EstadoFactura.CONFIRMED.value
    factura.reviewed_at = ahora()
    factura.reviewed_by_id = alcance.usuario.id

    if alertas:
        await _alerta_de_subidas(alcance, factura, alertas)
    await alcance.sesion.commit()

    return await _resultado_confirmacion(
        alcance,
        factura,
        alertas,
        len(repartos),
        len(registrados),
        creados,
        [],
        enlazados=enlazados,
        descuadre=descuadre,
    )


async def _crear_transaccion(
    alcance: AlcanceHogar,
    factura: Invoice,
    *,
    cuenta: Account,
    fecha: date,
    importe: Decimal,
    repartos: list[Reparto],
    defecto: uuidlib.UUID | None,
    nota: str | None,
) -> Transaction:
    """El gasto de la factura, con sus splits por temática (F-17).

    Los splits se insertan en **una sola sentencia** a propósito: el disparador
    `refresh_transaction_split_totals` recalcula los totales al final de la
    sentencia, así que insertarlos de uno en uno rompería el invariante
    `ck_transactions_split_invariant` en el primero.
    """
    descripcion = factura.issuer_name or factura.file_name
    if factura.invoice_number:
        descripcion = f"{descripcion} · {factura.invoice_number}"

    if not repartos:
        categoria = defecto
        if categoria is None:
            raise ReglaDeNegocio(
                "Indica la temática de la factura o activa el reparto por líneas.",
                codigo="datos_invalidos",
            )
        transaccion = Transaction(
            household_id=alcance.household_id,
            account_id=cuenta.id,
            kind="expense",
            booked_on=fecha,
            amount=importe,
            currency=factura.currency,
            category_id=categoria,
            payee_id=factura.payee_id,
            description=descripcion[:500],
            notes=nota,
            categorized_by="invoice",
            created_by_id=alcance.usuario.id,
        )
        alcance.sesion.add(transaccion)
        await alcance.sesion.flush()
        return transaccion

    transaccion = Transaction(
        household_id=alcance.household_id,
        account_id=cuenta.id,
        kind="expense",
        booked_on=fecha,
        amount=importe,
        currency=factura.currency,
        category_id=None,
        payee_id=factura.payee_id,
        description=descripcion[:500],
        notes=nota,
        split_count=len(repartos),
        split_total=importe,
        categorized_by="invoice",
        created_by_id=alcance.usuario.id,
    )
    alcance.sesion.add(transaccion)
    await alcance.sesion.flush()

    await alcance.sesion.execute(
        insert(TransactionSplit).values(
            [
                {
                    "id": uuidlib.uuid4(),
                    "household_id": alcance.household_id,
                    "transaction_id": transaccion.id,
                    "category_id": reparto.category_id,
                    "amount": reparto.importe,
                    "line_number": posicion,
                    "invoice_line_id": reparto.invoice_line_id,
                }
                for posicion, reparto in enumerate(repartos, start=1)
            ]
        )
    )
    return transaccion


async def _registrar_precios(
    alcance: AlcanceHogar,
    factura: Invoice,
    lineas: list[InvoiceLine],
    fecha: date,
) -> tuple[list[ProductPrice], list[AlertaPrecioRespuesta], int, int]:
    """RN-48: solo las líneas de producto alimentan el catálogo y el histórico."""
    umbral = await _umbral_de_subida(alcance)
    registrados: list[ProductPrice] = []
    alertas: list[AlertaPrecioRespuesta] = []
    creados = 0
    enlazados = 0
    comercio = await alcance.sesion.get(Payee, factura.payee_id) if factura.payee_id else None

    for linea in lineas:
        if linea.excluded or not linea.unit_price or linea.unit_price <= 0:
            continue
        if not linea.grouping_key or not linea.normalized_description:
            # `is_product = false`: un concepto de suministro no contamina el
            # catálogo (RN-48).
            continue

        producto: Product | None = None
        if linea.product_id:
            producto = await alcance.sesion.get(Product, linea.product_id)
            if producto is not None:
                enlazados += 1
        if producto is None:
            producto, nuevo = await _producto_para(alcance, factura, linea)
            creados += int(nuevo)
            enlazados += int(not nuevo)
        if producto is None:
            continue

        ya = (
            await alcance.sesion.execute(
                select(ProductPrice.id).where(ProductPrice.invoice_line_id == linea.id)
            )
        ).scalar_one_or_none()
        if ya is not None:
            # Única por `invoice_line_id`: reconfirmar no puede duplicar la serie.
            continue

        observacion, variacion = await registrar_observacion(
            alcance,
            producto=producto,
            fecha=fecha,
            precio_unitario=linea.unit_price,
            unidad=linea.unit or producto.unit,
            cantidad=linea.quantity,
            total=linea.line_total,
            payee_id=factura.payee_id,
            invoice_line_id=linea.id,
            origen="invoice",
            moneda=factura.currency,
        )
        registrados.append(observacion)

        # RN-64: se avisa por encima del umbral del hogar y de 0,05 € de diferencia.
        if (
            variacion.porcentaje is not None
            and variacion.anterior is not None
            and Decimal(str(variacion.porcentaje)) >= umbral
            and abs(linea.unit_price - variacion.anterior.unit_price) > Decimal("0.05")
        ):
            observacion.alerted_at = ahora()
            alertas.append(
                AlertaPrecioRespuesta(
                    product=ref_producto(producto),
                    payee=ref_comercio(comercio),
                    previous_unit_price=variacion.anterior.unit_price,
                    new_unit_price=linea.unit_price,
                    change_pct=variacion.porcentaje,
                    observed_at=fecha,
                    invoice_line_id=linea.id,
                )
            )
    return registrados, alertas, creados, enlazados


async def _producto_para(
    alcance: AlcanceHogar, factura: Invoice, linea: InvoiceLine
) -> tuple[Product | None, bool]:
    """Resuelve el producto de una línea: cascada y, si nada casa, alta nueva."""
    normalizada = normalizada_con_tamanyo(
        linea.raw_description,
        size_value=linea.size_value,
        size_unit=linea.size_unit,
    )
    emparejado: Emparejamiento | None = await emparejar(
        alcance.sesion, alcance.household_id, normalizada, codigo_barras=linea.product_code
    )
    if emparejado is not None:
        producto = await alcance.sesion.get(Product, emparejado.product_id)
        if producto is not None:
            linea.product_id = producto.id
            linea.match_method = emparejado.metodo
            linea.match_score = emparejado.puntuacion
            await aprender_alias(
                alcance,
                producto.id,
                linea.normalized_description,
                bruto=linea.raw_description,
                payee_id=factura.payee_id,
                metodo=emparejado.metodo,
                puntuacion=emparejado.puntuacion,
                confirmado=False,
            )
            return producto, False

    from app.schemas.producto import ProductoCrear

    producto = await crear_producto(
        alcance,
        ProductoCrear(
            name=linea.raw_description[:120],
            size_value=linea.size_value,
            size_unit=linea.size_unit,
            unit=linea.unit,
            default_category_id=linea.category_id,
        ),
        origen="invoice",
    )
    linea.product_id = producto.id
    linea.match_method = "manual"
    linea.match_score = Decimal("100.00")
    await aprender_alias(
        alcance,
        producto.id,
        linea.normalized_description,
        bruto=linea.raw_description,
        payee_id=factura.payee_id,
        metodo="manual",
        confirmado=False,
    )
    return producto, True


async def _umbral_de_subida(alcance: AlcanceHogar) -> Decimal:
    from app.models.hogar import Household

    valor = (
        await alcance.sesion.execute(
            select(Household.price_alert_pct).where(Household.id == alcance.household_id)
        )
    ).scalar_one_or_none()
    return valor if valor is not None else Decimal("5.00")


async def _alerta_de_subidas(
    alcance: AlcanceHogar, factura: Invoice, alertas: list[AlertaPrecioRespuesta]
) -> None:
    """RN-64: una alerta con N productos, no N alertas."""
    peor = max(alertas, key=lambda una: una.change_pct)
    cuerpo = "; ".join(
        f"{una.product.name}: {formato.precio(una.previous_unit_price)} → "
        f"{formato.precio(una.new_unit_price)} "
        f"({formato.porcentaje(Decimal(str(una.change_pct)) / 100)})"
        for una in alertas[:10]
    )
    clave = f"product_price_increase:{factura.id}"
    existente = (
        await alcance.sesion.execute(
            select(Alert).where(
                Alert.household_id == alcance.household_id, Alert.dedupe_key == clave
            )
        )
    ).scalar_one_or_none()
    titulo = (
        f"{len(alertas)} productos han subido de precio"
        if len(alertas) > 1
        else f"{peor.product.name} ha subido de precio"
    )
    carga = {
        "invoice_id": str(factura.id),
        "products": [
            {
                "product_id": str(una.product.id),
                "name": una.product.name,
                "previous_unit_price": str(una.previous_unit_price),
                "new_unit_price": str(una.new_unit_price),
                "change_pct": una.change_pct,
            }
            for una in alertas
        ],
    }
    if existente is not None:
        existente.title = titulo
        existente.body = cuerpo
        existente.payload = carga
        existente.status = "new"
        existente.read_at = None
        existente.triggered_at = ahora()
        return
    alcance.sesion.add(
        Alert(
            household_id=alcance.household_id,
            type="product_price_increase",
            severity="warning",
            status="new",
            title=titulo,
            body=cuerpo,
            dedupe_key=clave,
            subject_table="invoices",
            subject_id=factura.id,
            period_month=(factura.issued_on or date.today()).replace(day=1),
            payload=carga,
            triggered_at=ahora(),
        )
    )


async def _resultado_confirmacion(
    alcance: AlcanceHogar,
    factura: Invoice,
    alertas: list[AlertaPrecioRespuesta],
    splits: int,
    precios_registrados: int,
    productos_creados: int,
    avisos: list[str],
    *,
    enlazados: int = 0,
    descuadre: Decimal | None = None,
) -> FacturaConfirmarResultadoRespuesta:
    assert factura.transaction_id is not None  # noqa: S101 - se acaba de fijar
    return FacturaConfirmarResultadoRespuesta(
        invoice=await respuesta_factura(alcance, factura, incluir_lineas=True),
        transaction_id=factura.transaction_id,
        splits_created=splits,
        prices_registered=precios_registrados,
        products_created=productos_creados,
        products_linked=enlazados,
        total_mismatch=descuadre,
        price_alerts=alertas,
        warnings=avisos,
    )


@router.post(
    "/invoices/{invoice_id}/unconfirm", tags=["invoices"], summary="Revierte la confirmación"
)
async def deshacer_confirmacion(
    alcance: AlcanceEscritura,
    invoice_id: uuidlib.UUID,
    keep_transaction: bool = False,
) -> FacturaRespuesta:
    """RN-50: la inversa exacta de `confirm`, sin dejar nada a medias."""
    factura = await _factura_o_404(alcance, invoice_id)
    if factura.status != EstadoFactura.CONFIRMED.value:
        raise Conflicto("Esta factura no está confirmada.", codigo="conflicto")

    avisos: list[str] = []
    lineas = await _lineas_de(alcance, factura)
    identificadores = [linea.id for linea in lineas] or [uuidlib.uuid4()]

    afectados = list(
        (
            await alcance.sesion.execute(
                select(ProductPrice).where(
                    ProductPrice.household_id == alcance.household_id,
                    ProductPrice.invoice_line_id.in_(identificadores),
                )
            )
        ).scalars()
    )
    productos = {observacion.product_id for observacion in afectados}
    await alcance.sesion.execute(
        delete(ProductPrice).where(
            ProductPrice.household_id == alcance.household_id,
            ProductPrice.invoice_line_id.in_(identificadores),
        )
    )
    await alcance.sesion.flush()
    for product_id in productos:
        producto = await alcance.sesion.get(Product, product_id)
        if producto is not None:
            await refrescar_producto(alcance.sesion, producto)

    # La alerta de subida que originó esta factura se cierra: su causa ya no existe.
    await alcance.sesion.execute(
        delete(Alert).where(
            Alert.household_id == alcance.household_id,
            Alert.dedupe_key == f"product_price_increase:{factura.id}",
        )
    )

    if factura.transaction_id is not None:
        transaccion = await alcance.sesion.get(Transaction, factura.transaction_id)
        if transaccion is not None:
            modificada = (
                factura.reviewed_at is not None and transaccion.updated_at > factura.reviewed_at
            )
            if keep_transaction or modificada:
                if modificada:
                    avisos.append("transaccion_modificada")
            else:
                await alcance.sesion.delete(transaccion)
        factura.transaction_id = None

    factura.status = EstadoFactura.PENDING_REVIEW.value
    factura.reviewed_at = None
    factura.reviewed_by_id = None
    await alcance.sesion.commit()
    respuesta = await respuesta_factura(alcance, factura, incluir_lineas=True)
    respuesta.warnings = [*respuesta.warnings, *avisos]
    return respuesta


@router.post(
    "/invoices/{invoice_id}/reprocess",
    tags=["invoices"],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Vuelve a extraer el PDF",
)
async def reprocesar(
    alcance: AlcanceEscritura,
    invoice_id: uuidlib.UUID,
    tareas: BackgroundTasks,
    datos: FacturaReprocesarCrear,
) -> FacturaRespuesta:
    """Conserva las líneas corregidas a mano si se pide (RN-41)."""
    factura = await _factura_o_404(alcance, invoice_id)
    _exigir_revisable(factura)
    if datos.template_id is not None:
        await _plantilla_del_hogar(alcance, datos.template_id)
        factura.extraction_template_id = datos.template_id
    factura.status = EstadoFactura.PROCESSING.value
    factura.error_message = None
    await alcance.sesion.commit()
    tareas.add_task(
        procesar_factura,
        _motor(alcance.sesion),
        factura.id,
        alcance.household_id,
        forzar_ocr=datos.force_ocr,
        conservar_editadas=datos.keep_edited,
    )
    return await respuesta_factura(alcance, factura)


@router.delete(
    "/invoices/{invoice_id}",
    tags=["invoices"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Descarta la factura",
)
async def borrar(
    alcance: AlcanceEscritura,
    invoice_id: uuidlib.UUID,
    force: bool = False,
    delete_transaction: bool = False,
) -> Response:
    """Borra la factura y su PDF. Una confirmada exige `force=true`."""
    factura = await _factura_o_404(alcance, invoice_id)
    if factura.status == EstadoFactura.CONFIRMED.value and not force:
        raise Conflicto(
            "Esta factura está confirmada. Deshaz la confirmación o bórrala con force.",
            codigo="conflicto",
        )
    if delete_transaction and factura.transaction_id:
        transaccion = await alcance.sesion.get(Transaction, factura.transaction_id)
        if transaccion is not None:
            await alcance.sesion.delete(transaccion)

    ruta = ruta_de(factura.storage_key)
    await alcance.sesion.delete(factura)
    await alcance.sesion.commit()
    # El fichero se borra **después** del COMMIT: si la transacción falla, el PDF
    # sigue estando (RN-78).
    ruta.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
