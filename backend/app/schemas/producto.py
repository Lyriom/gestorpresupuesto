"""Catálogo de productos, alias, histórico de precios, comparativa y cesta.

§3.14 y §4.10 del contrato. La tendencia de precio no se redefine: es
`Tendencia` de `app/services/precios.py`, que ya es quien la calcula, igual que
el umbral difuso por defecto viene de `app/services/normalizacion.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comercio import ComercioRefRespuesta
from app.schemas.comun import (
    Actualizacion,
    CantidadStr,
    ImporteStr,
    Moneda,
    Nombre,
    ParametrosBusqueda,
    Peticion,
    PrecioStr,
    Puntuacion,
    Respuesta,
    RespuestaSellada,
    fallo,
    sin_repetidos,
)
from app.services.normalizacion import UMBRAL_COINCIDENCIA
from app.services.precios import Tendencia


class OrigenPrecio(StrEnum):
    """De dónde salió la observación de precio."""

    INVOICE = "invoice"
    MANUAL = "manual"
    IMPORT = "import"


class ProductoCrear(Peticion):
    name: Nombre
    brand: str | None = Field(default=None, max_length=80)
    size_value: CantidadStr | None = Field(default=None, gt=0)
    size_unit: str | None = Field(default=None, max_length=20)
    unit: str | None = Field(default=None, max_length=20, description="Unidad de venta: kg, l, ud.")
    barcode: str | None = Field(default=None, max_length=20)
    default_category_id: UUID | None = None
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _tamanyo_completo(self) -> ProductoCrear:
        """RN-60: un tamaño sin unidad no sirve para comparar precios unitarios."""
        if (self.size_value is None) != (self.size_unit is None):
            fallo("datos_invalidos", "Indica el tamaño y su unidad, o ninguno de los dos.")
        return self


class ProductoActualizar(Actualizacion):
    name: Nombre | None = None
    brand: str | None = Field(default=None, max_length=80)
    size_value: CantidadStr | None = Field(default=None, gt=0)
    size_unit: str | None = Field(default=None, max_length=20)
    unit: str | None = Field(default=None, max_length=20)
    barcode: str | None = Field(default=None, max_length=20)
    default_category_id: UUID | None = None
    is_archived: bool | None = None
    note: str | None = Field(default=None, max_length=1000)


class ProductoRefRespuesta(Respuesta):
    id: UUID
    name: str
    brand: str | None = None
    size_text: str | None = None


class ProductoRespuesta(RespuestaSellada):
    name: str
    brand: str | None
    canonical_name: str = Field(description="Clave de agrupación de `normalizacion.py`.")
    size_value: CantidadStr | None = None
    size_unit: str | None = None
    size_text: str | None = None
    unit: str | None = None
    barcode: str | None = None
    default_category: CategoriaRefRespuesta | None = None
    is_archived: bool
    aliases_count: int = 0
    observations_count: int = 0
    payees_count: int = 0
    first_seen_on: date | None = None
    last_seen_on: date | None = None
    last_unit_price: PrecioStr | None = None
    min_unit_price: PrecioStr | None = None
    max_unit_price: PrecioStr | None = None
    average_unit_price: PrecioStr | None = None
    change_pct: float | None = Field(
        default=None, description="Última observación frente a la anterior (RN-63)."
    )
    change_pct_12m: float | None = None
    trend: Tendencia = Tendencia.SIN_DATOS
    has_increase: bool = False
    note: str | None = None


class ProductoSugerenciaRespuesta(Respuesta):
    """Candidato por parecido difuso. El sistema sugiere; el usuario confirma (RN-60)."""

    product: ProductoRefRespuesta
    score: Puntuacion = Field(description="RapidFuzz; el umbral por defecto es 88.")
    matched_alias: str | None = None
    last_unit_price: PrecioStr | None = None
    last_payee: ComercioRefRespuesta | None = None


class ProductoFusionCrear(Peticion):
    source_ids: list[UUID] = Field(min_length=1, max_length=50)
    target_id: UUID
    keep_aliases: bool = True

    @model_validator(mode="after")
    def _no_consigo_mismo(self) -> ProductoFusionCrear:
        if self.target_id in self.source_ids:
            fallo("fusion_invalida", "No se puede fusionar un producto consigo mismo.")
        if not sin_repetidos(self.source_ids):
            fallo("fusion_invalida", "Hay productos repetidos en la lista de origen.")
        return self


class ProductoFusionResultadoRespuesta(Respuesta):
    merge_id: UUID
    target: ProductoRefRespuesta
    sources: list[ProductoRefRespuesta]
    prices_moved: int
    invoice_lines_moved: int
    aliases_moved: int
    performed_at: datetime
    undo_available_until: datetime


class ProductoFusionRespuesta(Respuesta):
    """Una fusión de producto del registro de reasignación (RN-65)."""

    id: UUID
    target: ProductoRefRespuesta | None
    sources: list[ProductoRefRespuesta] = Field(default_factory=list)
    prices_moved: int
    performed_at: datetime
    undo_available_until: datetime
    undone_at: datetime | None = None
    can_undo: bool


class ProductoSepararCrear(Peticion):
    """Separar un producto mal fusionado: se elige qué se saca, de tres formas."""

    price_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    alias_ids: list[UUID] = Field(
        default_factory=list,
        max_length=200,
        description="Saca todo lo observado bajo estos alias.",
    )
    payee_id: UUID | None = Field(
        default=None, description="Saca todo lo observado en este comercio."
    )
    target_product_id: UUID | None = Field(
        default=None, description="Destino existente; si no, se crea uno nuevo."
    )
    new_product: ProductoCrear | None = None

    @model_validator(mode="after")
    def _algo_que_sacar(self) -> ProductoSepararCrear:
        if not (self.price_ids or self.alias_ids or self.payee_id):
            fallo("datos_invalidos", "Indica qué observaciones hay que separar.")
        if bool(self.target_product_id) == bool(self.new_product):
            fallo(
                "datos_invalidos",
                "Indica un producto destino o los datos de uno nuevo, pero no los dos.",
            )
        return self


class ProductoSepararResultadoRespuesta(Respuesta):
    source: ProductoRefRespuesta
    target: ProductoRefRespuesta
    prices_moved: int
    invoice_lines_moved: int
    aliases_moved: int


class AliasProductoCrear(Peticion):
    raw_description: str = Field(min_length=2, max_length=300)


class AliasProductoRespuesta(Respuesta):
    id: UUID
    product_id: UUID
    raw_description: str
    normalized: str | None = None
    payee: ComercioRefRespuesta | None = None
    times_seen: int = 1
    source: Literal["invoice", "manual", "merge"] = "invoice"
    created_at: datetime


class PrecioCrear(Peticion):
    """Observación de precio registrada a mano: un escaparate, una etiqueta del súper."""

    product_id: UUID
    payee_id: UUID | None = None
    observed_at: date
    unit_price: PrecioStr = Field(gt=0)
    unit: str | None = Field(default=None, max_length=20)
    quantity: CantidadStr | None = Field(default=None, gt=0)
    total: ImporteStr | None = None
    currency: Moneda = "EUR"
    note: str | None = Field(default=None, max_length=280)


class PrecioActualizar(Actualizacion):
    payee_id: UUID | None = None
    observed_at: date | None = None
    unit_price: PrecioStr | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=20)
    quantity: CantidadStr | None = Field(default=None, gt=0)
    total: ImporteStr | None = None
    note: str | None = Field(default=None, max_length=280)


class PrecioRespuesta(Respuesta):
    id: UUID
    product_id: UUID
    product: ProductoRefRespuesta | None = None
    payee: ComercioRefRespuesta | None = None
    observed_at: date
    unit_price: PrecioStr
    unit: str | None
    quantity: CantidadStr | None = None
    total: ImporteStr | None = None
    currency: str = "EUR"
    source: OrigenPrecio
    invoice_id: UUID | None = None
    invoice_line_id: UUID | None = Field(
        default=None, description="Única por línea de factura: reconfirmar no duplica (RN-47)."
    )
    change_pct: float | None = None
    change_basis: Literal["same_payee", "global"] | None = Field(
        default=None, description="RN-63: contra qué observación se ha comparado."
    )
    is_increase: bool = False
    note: str | None = None
    created_at: datetime


class EstadisticasPrecioRespuesta(Respuesta):
    product_id: UUID
    observations: int
    period_from: date | None = None
    period_to: date | None = None
    min_unit_price: PrecioStr | None = None
    max_unit_price: PrecioStr | None = None
    average_unit_price: PrecioStr | None = None
    median_unit_price: PrecioStr | None = None
    last_unit_price: PrecioStr | None = None
    last_observed_at: date | None = None
    change_pct: float | None = None
    change_pct_12m: float | None = None
    trend: Tendencia = Tendencia.SIN_DATOS
    cheapest_payee: ComercioRefRespuesta | None = None


class PrecioComercioRespuesta(Respuesta):
    payee: ComercioRefRespuesta | None
    last_unit_price: PrecioStr
    last_observed_at: date
    observations: int
    average_unit_price: PrecioStr
    diff_vs_cheapest: ImporteStr
    diff_vs_cheapest_pct: float
    is_stale: bool = Field(default=False, description="La observación tiene más de 90 días.")


class ComparativaProductoRespuesta(Respuesta):
    """Comparativa entre comercios del mismo producto (F-38)."""

    product: ProductoRefRespuesta
    unit: str | None = None
    cheapest: PrecioComercioRespuesta | None = None
    most_expensive: PrecioComercioRespuesta | None = None
    spread_pct: float | None = None
    by_payee: list[PrecioComercioRespuesta] = Field(default_factory=list)


class AlertaPrecioRespuesta(Respuesta):
    """Subida detectada al confirmar una factura (F-16, RN-64)."""

    product: ProductoRefRespuesta
    payee: ComercioRefRespuesta | None = None
    previous_unit_price: PrecioStr
    new_unit_price: PrecioStr
    change_pct: float
    observed_at: date
    invoice_line_id: UUID | None = None


class CestaItemCrear(Peticion):
    product_id: UUID
    quantity: CantidadStr = Field(default=Decimal("1"), gt=0)


class CestaItemRespuesta(Respuesta):
    product: ProductoRefRespuesta
    quantity: CantidadStr
    last_unit_price: PrecioStr | None = None


class CestaCrear(Peticion):
    name: Nombre
    items: list[CestaItemCrear] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _sin_repetidos(self) -> CestaCrear:
        if not sin_repetidos([item.product_id for item in self.items]):
            fallo("datos_invalidos", "Hay un producto repetido en la cesta.")
        return self


class CestaActualizar(Actualizacion):
    name: Nombre | None = None
    items: list[CestaItemCrear] | None = Field(default=None, min_length=1, max_length=200)


class CestaRespuesta(RespuestaSellada):
    name: str
    items: list[CestaItemRespuesta] = Field(default_factory=list)
    items_count: int = 0
    estimated_total: ImporteStr | None = None


class ProductoFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset(
        {"name", "last_price", "change_pct", "observations", "last_seen_on", "created_at"}
    )
    ORDEN_POR_DEFECTO = "name"

    category_id: UUID | None = None
    payee_id: UUID | None = None
    is_archived: bool | None = None
    has_increase: bool | None = None


class ProductoSugerenciaFiltro(ParametrosBusqueda):
    """`GET /products/suggestions`: candidatos para la pantalla de revisión."""

    description: str = Field(min_length=2, max_length=300)
    limit: int = Field(default=5, ge=1, le=20)
    min_score: Puntuacion = UMBRAL_COINCIDENCIA


class PrecioFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset({"observed_at", "unit_price", "created_at"})
    ORDEN_POR_DEFECTO = "-observed_at"

    product_id: UUID | None = None
    payee_id: UUID | None = None
    invoice_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    source: OrigenPrecio | None = None
