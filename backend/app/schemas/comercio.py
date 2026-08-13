"""Comercios y proveedores: §3.9 y §4.8 del contrato."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comun import (
    Actualizacion,
    ImporteStr,
    Nombre,
    ParametrosBusqueda,
    Periodo,
    Peticion,
    Puntuacion,
    Respuesta,
    RespuestaSellada,
    fallo,
    sin_repetidos,
)
from app.services.normalizacion import UMBRAL_COINCIDENCIA


class ComercioCrear(Peticion):
    name: Nombre
    default_category_id: UUID | None = None
    aliases: list[str] = Field(default_factory=list, max_length=50)
    website: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=20, description="NIF/CIF del emisor.")
    note: str | None = Field(default=None, max_length=1000)


class ComercioActualizar(Actualizacion):
    name: Nombre | None = None
    default_category_id: UUID | None = None
    aliases: list[str] | None = Field(default=None, max_length=50)
    website: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=1000)
    is_archived: bool | None = None


class ComercioRefRespuesta(Respuesta):
    id: UUID
    name: str


class ComercioRespuesta(RespuestaSellada):
    name: str
    normalized_name: str
    default_category: CategoriaRefRespuesta | None = None
    aliases: list[str] = Field(default_factory=list)
    tax_id: str | None
    website: str | None
    note: str | None = None
    is_archived: bool
    # include=stats
    transactions_count: int | None = None
    total_spent: ImporteStr | None = None
    average_ticket: ImporteStr | None = None
    first_seen_on: date | None = None
    last_seen_on: date | None = None
    invoices_count: int | None = None


class ComercioSugerenciaRespuesta(Respuesta):
    """Parecido difuso para el autocompletado y la normalización en importaciones."""

    payee: ComercioRefRespuesta
    score: Puntuacion = Field(description="Parecido de RapidFuzz; el umbral por defecto es 88.")
    matched_alias: str | None = None


class ComercioFusionCrear(Peticion):
    """«Netflix» y «NETFLIX.COM» son el mismo comercio (RN-17 a RN-19)."""

    source_ids: list[UUID] = Field(min_length=1, max_length=50)
    target_id: UUID
    keep_aliases: bool = True

    @model_validator(mode="after")
    def _no_consigo_mismo(self) -> ComercioFusionCrear:
        if self.target_id in self.source_ids:
            fallo("fusion_invalida", "No se puede fusionar un comercio consigo mismo.")
        if not sin_repetidos(self.source_ids):
            fallo("fusion_invalida", "Hay comercios repetidos en la lista de origen.")
        return self


class ComercioFusionResultadoRespuesta(Respuesta):
    merge_id: UUID
    target: ComercioRefRespuesta
    sources: list[ComercioRefRespuesta]
    transactions_moved: int
    invoices_moved: int
    aliases_moved: int
    rules_updated: int
    recurring_updated: int


class ComercioPeriodoRespuesta(Respuesta):
    period: Periodo
    amount: ImporteStr
    transactions: int


class ComercioTematicaRespuesta(Respuesta):
    category: CategoriaRefRespuesta | None
    amount: ImporteStr
    transactions: int
    share_pct: float


class ComercioEstadisticasRespuesta(Respuesta):
    """Gasto por mes y por temática en un comercio."""

    payee: ComercioRefRespuesta
    period_from: Periodo | None
    period_to: Periodo | None
    total_spent: ImporteStr
    transactions: int
    average_ticket: ImporteStr
    by_period: list[ComercioPeriodoRespuesta] = Field(default_factory=list)
    by_category: list[ComercioTematicaRespuesta] = Field(default_factory=list)


class ComercioFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset(
        {"name", "total_spent", "transactions_count", "last_seen_on", "created_at"}
    )
    ORDEN_POR_DEFECTO = "name"

    category_id: UUID | None = None
    is_archived: bool | None = None
    include: list[Literal["stats"]] = Field(default=[])


class ComercioSugerenciaFiltro(ParametrosBusqueda):
    """`GET /payees/suggestions`: parecido difuso sobre un nombre crudo."""

    name: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=5, ge=1, le=20)
    min_score: Puntuacion = UMBRAL_COINCIDENCIA
