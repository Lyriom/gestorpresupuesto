"""Facturas PDF: subida, estado del procesado, revisión, corrección y confirmación.

§3.12, §3.13 y §4.9 del contrato. Los nombres de campo son la traducción directa
de `FacturaExtraida` y `LineaExtraida` (`app/services/extraccion_pdf.py`), para
que la capa de servicio no tenga que inventar nada:

    emisor→issuer, nif_emisor→issuer_tax_id, numero→number, fecha→date,
    base_imponible→taxable_base, impuestos→tax_amount, total→total,
    moneda→currency, metodo→extraction_method, paginas→pages,
    confianza→confidence, avisos→warnings; y en cada línea
    descripcion→description, cantidad→quantity, unidad→unit,
    precio_unitario→unit_price, total→total, confianza→confidence,
    normalizada→normalized.

El método de extracción y la tolerancia de descuadre son los del extractor
(`MetodoExtraccion` y `TOLERANCIA`), no una copia.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comercio import ComercioRefRespuesta
from app.schemas.comun import (
    Actualizacion,
    CantidadStr,
    Confianza,
    ImporteStr,
    Moneda,
    Nombre,
    ParametrosBusqueda,
    Peticion,
    PrecioStr,
    Respuesta,
    RespuestaSellada,
    fallo,
)
from app.schemas.producto import (
    AlertaPrecioRespuesta,
    ProductoCrear,
    ProductoRefRespuesta,
    ProductoSugerenciaRespuesta,
)
from app.services.extraccion_pdf import TOLERANCIA, MetodoExtraccion

#: `date` es además el nombre de un campo, y un campo con valor por defecto
#: oculta el tipo dentro de la clase: en esas anotaciones se usa este alias.
Fecha = date

#: Confianza por debajo de la cual la interfaz destaca la línea (§3.13).
CONFIANZA_BAJA = 0.6

#: Tope de líneas de una factura, para que una revisión quepa en una pantalla.
LINEAS_MAXIMAS = 500

#: Alias público de `MetodoExtraccion`: "tabla" | "texto" | "ocr" | "ninguno".
MetodoExtraccionFactura = MetodoExtraccion


class EstadoFactura(StrEnum):
    """Los cinco estados que exigen RN-46 y RN-49."""

    PROCESSING = "processing"  # extracción en curso
    PENDING_REVIEW = "pending_review"  # extraída, ESPERANDO REVISIÓN HUMANA
    FAILED = "failed"  # PDF ilegible: alta manual sobre la misma factura
    CONFIRMED = "confirmed"  # revisada y volcada a transacción + precios
    DISCARDED = "discarded"


#: RN-49: solo se corrige en estos dos estados.
ESTADOS_REVISABLES = frozenset({EstadoFactura.PENDING_REVIEW, EstadoFactura.FAILED})


class NormalizadaRespuesta(Respuesta):
    """Espejo de `DescripcionNormalizada` del servicio de normalización."""

    canonical: str
    brand_guess: str | None = None
    size_value: CantidadStr | None = None
    size_unit: str | None = None
    code: str | None = None


class LineaFacturaRespuesta(Respuesta):
    id: UUID
    line_number: int
    description: str
    quantity: CantidadStr | None = None
    unit: str | None = None
    unit_price: PrecioStr | None = None
    total: ImporteStr | None = None
    confidence: Confianza
    normalized: NormalizadaRespuesta | None = None
    # Revisión
    is_edited: bool = Field(
        default=False, description="Corregida a mano: un reprocesado no la toca."
    )
    is_excluded: bool = Field(default=False, description="Descartada: no genera split ni precio.")
    is_product: bool = Field(
        default=True, description="False para conceptos: potencia, impuestos, portes (RN-48)."
    )
    warnings: list[str] = Field(default_factory=list)
    # Vínculos y sugerencias
    category_id: UUID | None = None
    category: CategoriaRefRespuesta | None = None
    product_id: UUID | None = None
    product: ProductoRefRespuesta | None = None
    suggested_product: ProductoSugerenciaRespuesta | None = None
    suggested_category: CategoriaRefRespuesta | None = None
    last_unit_price: PrecioStr | None = None
    last_seen_on: date | None = None
    change_pct: float | None = Field(
        default=None, description="Variación frente al último precio visto (RN-63)."
    )


class FacturaRespuesta(RespuestaSellada):
    status: EstadoFactura
    # Cabecera extraída y corregible
    issuer: str | None = None
    issuer_tax_id: str | None = None
    number: str | None = None
    date: Fecha | None = None
    taxable_base: ImporteStr | None = None
    tax_amount: ImporteStr | None = None
    total: ImporteStr | None = None
    currency: str
    # Extracción
    extraction_method: MetodoExtraccion = "ninguno"
    pages: int = 0
    confidence: Confianza = 0.0
    warnings: list[str] = Field(default_factory=list)
    lines_count: int = 0
    lines_sum: ImporteStr = Field(description="Suma de los totales de las líneas no excluidas.")
    total_mismatch: ImporteStr | None = Field(
        default=None, description="lines_sum − total, si descuadra."
    )
    low_confidence_lines: int = 0
    # Fichero. Los cuatro son nulos en una factura metida a mano: no tiene
    # documento, y fingir uno dejaría a la interfaz ofreciendo «ver original»
    # para algo que no existe.
    filename: str | None = None
    size_bytes: int | None = None
    checksum: str | None = Field(
        default=None, description="SHA-256: la misma factura no se sube dos veces (RN-44)."
    )
    file_url: str | None = None
    # Vínculos
    payee_id: UUID | None = None
    payee: ComercioRefRespuesta | None = None
    account_id: UUID | None = None
    transaction_id: UUID | None = None
    template_id: UUID | None = None
    duplicate_of_id: UUID | None = None
    default_category_id: UUID | None = None
    note: str | None = None
    uploaded_at: datetime
    processed_at: datetime | None = None
    reviewed_at: datetime | None = None
    confirmed_at: datetime | None = None
    error: str | None = None
    lines: list[LineaFacturaRespuesta] = Field(default_factory=list)


class FacturaEstadoRespuesta(Respuesta):
    """Sondeo del procesado: una sola fila, cacheable con `ETag`."""

    id: UUID
    status: EstadoFactura
    progress: int = Field(ge=0, le=100)
    extraction_method: MetodoExtraccion = "ninguno"
    pages: int = 0
    confidence: Confianza = 0.0
    lines_count: int = 0
    low_confidence_lines: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    retry_after_seconds: int | None = Field(
        default=None, description="Ritmo de sondeo mientras procesa: 1,5 s (§3.13)."
    )


class FacturaSubirCrear(Peticion):
    """Campos que acompañan al `fichero` en el `multipart` de `POST /invoices`.

    El PDF se valida por contenido, nunca por el `content-type` que declara el
    navegador (RN-43), así que aquí no hay ningún campo de tipo de fichero.
    """

    account_id: UUID | None = None
    payee_id: UUID | None = None
    template_id: UUID | None = None


class FacturaActualizar(Actualizacion):
    """Corrección de la cabecera durante la revisión (RN-49)."""

    issuer: str | None = Field(default=None, max_length=200)
    issuer_tax_id: str | None = Field(default=None, max_length=20)
    number: str | None = Field(default=None, max_length=60)
    date: Fecha | None = None
    taxable_base: ImporteStr | None = None
    tax_amount: ImporteStr | None = None
    total: ImporteStr | None = None
    currency: Moneda | None = None
    payee_id: UUID | None = None
    payee_name: str | None = Field(default=None, max_length=120)
    account_id: UUID | None = None
    default_category_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class LineaFacturaActualizar(Actualizacion):
    """Corrección de una línea. El backend recalcula el hueco que falte (RN-41)."""

    description: str | None = Field(default=None, max_length=300)
    quantity: CantidadStr | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    unit_price: PrecioStr | None = Field(default=None, ge=0)
    total: ImporteStr | None = None
    category_id: UUID | None = None
    product_id: UUID | None = None
    is_excluded: bool | None = None
    is_product: bool | None = None


class LineaFacturaCrear(Peticion):
    """Línea añadida a mano: la que el parser no vio."""

    description: str = Field(min_length=1, max_length=300)
    quantity: CantidadStr | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    unit_price: PrecioStr | None = Field(default=None, ge=0)
    total: ImporteStr | None = None
    category_id: UUID | None = None
    product_id: UUID | None = None
    is_excluded: bool = False
    is_product: bool = True
    position: int | None = Field(default=None, ge=0)


class FacturaManualCrear(Peticion):
    """Factura metida a mano: el ticket de papel, la compra sin PDF.

    Pide lo mínimo que hace falta para que la factura sirva de algo: quién la
    emitió, cuándo y cuánto. Las líneas son opcionales, pero **sin ellas la
    factura no aporta nada al seguimiento de precios**, que es para lo que está
    el catálogo de productos; la interfaz lo advierte.

    El «concepto» es la temática, y se puede dar de dos maneras: con
    `category_id` si ya existe o con `category_name` si es nueva, y entonces se
    crea. Las dos a la vez no, porque no habría forma de saber cuál manda.
    """

    issuer: Nombre
    issuer_tax_id: str | None = Field(default=None, max_length=20)
    number: str | None = Field(default=None, max_length=60)
    date: Fecha
    taxable_base: ImporteStr | None = None
    tax_amount: ImporteStr | None = None
    total: ImporteStr = Field(gt=0, description="En positivo, como en el papel.")
    currency: Moneda | None = Field(default=None, description="Por defecto, la del hogar.")
    payee_id: UUID | None = None
    category_id: UUID | None = Field(default=None, description="El concepto, si ya existe.")
    category_name: Nombre | None = Field(
        default=None, description="El concepto cuando es nuevo: se crea la temática."
    )
    account_id: UUID | None = Field(
        default=None,
        description="Si viene, la factura se confirma y genera el movimiento en el acto.",
    )
    note: str | None = Field(default=None, max_length=2000)
    lines: list[LineaFacturaCrear] = Field(default_factory=list, max_length=200)
    allow_total_mismatch: bool = Field(
        default=False,
        description=(
            "Confirmar aunque las líneas no sumen el total. En una factura con "
            "impuestos es lo normal: las líneas suman la base y el total lleva el IVA."
        ),
    )

    @model_validator(mode="after")
    def _un_solo_concepto(self) -> FacturaManualCrear:
        if self.category_id is not None and self.category_name is not None:
            fallo(
                "concepto_ambiguo",
                "Elige una temática existente o escribe una nueva, no las dos.",
            )
        # Confirmar en el acto crea un movimiento, y un movimiento sin temática
        # queda fuera de la barra del presupuesto: es justo lo que se quiere evitar.
        if self.account_id is not None and self.category_id is None and self.category_name is None:
            fallo(
                "falta_el_concepto",
                "Para guardar la factura y el gasto de una vez hace falta la temática.",
            )
        return self


class LineaRevisionCrear(Peticion):
    """Una línea dentro del guardado completo de la revisión."""

    id: UUID | None = Field(default=None, description="Nulo para una línea añadida a mano.")
    description: str = Field(min_length=1, max_length=300)
    quantity: CantidadStr | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    unit_price: PrecioStr | None = Field(default=None, ge=0)
    total: ImporteStr
    category_id: UUID | None = None
    product_id: UUID | None = None
    is_excluded: bool = False
    is_product: bool = True


class LineasFacturaSustituirCrear(Peticion):
    """Guardado de la revisión completa en una sola llamada. Idempotente."""

    lines: list[LineaRevisionCrear] = Field(max_length=LINEAS_MAXIMAS)

    @model_validator(mode="after")
    def _sin_ids_repetidos(self) -> LineasFacturaSustituirCrear:
        vistos = [linea.id for linea in self.lines if linea.id is not None]
        if len(set(vistos)) != len(vistos):
            fallo("datos_invalidos", "Hay una línea repetida en la revisión.")
        return self


class LineaDividirCrear(Peticion):
    """Reparte una línea en varias: un pack que son dos productos distintos."""

    parts: list[LineaRevisionCrear] = Field(min_length=2, max_length=20)


class LineasFacturaRespuesta(Respuesta):
    """Lo que pinta la pantalla de revisión, con el semáforo de confirmación."""

    invoice_id: UUID
    status: EstadoFactura
    total: ImporteStr | None = None
    taxable_base: ImporteStr | None = None
    lines_sum: ImporteStr
    total_mismatch: ImporteStr | None = None
    tolerance: ImporteStr = Field(
        default=TOLERANCIA, description="0,02 €, la misma constante que usa el extractor (RN-42)."
    )
    can_confirm: bool
    blocking_reasons: list[str] = Field(
        default_factory=list,
        description="Ej.: 'Hay 3 líneas sin temática', 'Las líneas no suman el total'.",
    )
    warnings: list[str] = Field(default_factory=list)
    low_confidence_lines: int = 0
    lines: list[LineaFacturaRespuesta] = Field(default_factory=list)


class VincularProductoCrear(Peticion):
    """Vincular una línea con el catálogo: a uno existente o creando uno nuevo."""

    product_id: UUID | None = None
    new_product: ProductoCrear | None = None
    remember_alias: bool = Field(
        default=True, description="Aprende la descripción cruda para la próxima factura."
    )
    set_default_category: bool = Field(
        default=False, description="Guarda la temática de la línea como la del producto (F-17)."
    )

    @model_validator(mode="after")
    def _uno_de_los_dos(self) -> VincularProductoCrear:
        if bool(self.product_id) == bool(self.new_product):
            fallo(
                "datos_invalidos",
                "Indica un producto existente o los datos de uno nuevo, pero no los dos.",
            )
        return self


class FacturaConfirmarCrear(Peticion):
    """Confirmación de la revisión. Solo se puede una vez (RN-46)."""

    account_id: UUID
    date: Fecha | None = Field(default=None, description="Por defecto, la fecha de la factura.")
    payee_id: UUID | None = None
    default_category_id: UUID | None = Field(
        default=None, description="Para las líneas sin temática propia."
    )
    transaction_id: UUID | None = Field(
        default=None, description="Vincular a un gasto ya registrado en vez de crear uno nuevo."
    )
    create_splits: bool = Field(default=True, description="Un split por temática (F-17).")
    register_prices: bool = Field(default=True, description="Alimenta el histórico (F-15).")
    allow_total_mismatch: bool = Field(
        default=False, description="Confirmar aun sin cuadrar el total (RN-42)."
    )
    ignore_duplicate: bool = Field(
        default=False, description="Confirmar aun siendo duplicada (RN-45)."
    )
    tag_ids: list[UUID] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=2000)


class FacturaConfirmarResultadoRespuesta(Respuesta):
    invoice: FacturaRespuesta
    transaction_id: UUID
    splits_created: int
    prices_registered: int
    products_created: int
    products_linked: int
    total_mismatch: ImporteStr | None = None
    price_alerts: list[AlertaPrecioRespuesta] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FacturaDuplicadaRespuesta(Respuesta):
    """Candidata a duplicado por emisor + número + fecha + total (RN-45)."""

    invoice_id: UUID
    issuer: str | None = None
    number: str | None = None
    date: Fecha | None = None
    total: ImporteStr | None = None
    status: EstadoFactura
    match_reason: Literal["checksum", "issuer_number_date_total", "total_date", "number_only"]
    confidence: Confianza


class FacturaReprocesarCrear(Peticion):
    """Vuelve a extraer conservando lo corregido a mano (RN-41)."""

    template_id: UUID | None = None
    force_ocr: bool = False
    keep_edited: bool = True


class PlantillaFacturaCrear(Peticion):
    """Plantilla de extracción por proveedor (F-40)."""

    name: Nombre
    payee_id: UUID | None = None
    issuer_pattern: str = Field(min_length=2, max_length=200)
    from_invoice_id: UUID | None = Field(
        default=None, description="Aprende los patrones de una factura ya corregida."
    )
    field_patterns: dict[str, str] = Field(default_factory=dict)
    table_columns: dict[str, int] = Field(default_factory=dict)
    default_category_id: UUID | None = None
    force_ocr: bool = False
    is_active: bool = True


class PlantillaFacturaActualizar(Actualizacion):
    name: Nombre | None = None
    payee_id: UUID | None = None
    issuer_pattern: str | None = Field(default=None, min_length=2, max_length=200)
    field_patterns: dict[str, str] | None = None
    table_columns: dict[str, int] | None = None
    default_category_id: UUID | None = None
    force_ocr: bool | None = None
    is_active: bool | None = None


class PlantillaFacturaRespuesta(RespuestaSellada):
    name: str
    payee: ComercioRefRespuesta | None = None
    issuer_pattern: str
    field_patterns: dict[str, str] = Field(default_factory=dict)
    table_columns: dict[str, int] = Field(default_factory=dict)
    default_category_id: UUID | None = None
    force_ocr: bool
    is_active: bool
    invoices_count: int = 0
    last_used_at: datetime | None = None


class PlantillaProbarCrear(Peticion):
    """Prueba la plantilla contra una factura ya subida, sin guardar nada."""

    invoice_id: UUID


class FacturaFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset({"uploaded_at", "date", "total", "confidence", "issuer"})
    ORDEN_POR_DEFECTO = "-uploaded_at"

    status: list[EstadoFactura] = Field(default=[])
    payee_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    min_total: ImporteStr | None = None
    max_total: ImporteStr | None = None
    has_transaction: bool | None = None
    confidence_below: Confianza | None = None
    include: list[Literal["lines", "duplicates"]] = Field(default=[])
