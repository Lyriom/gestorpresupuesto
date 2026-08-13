"""Etiquetas libres (F-35): §3.10 y §4.8 del contrato."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.comun import (
    Actualizacion,
    ColorHex,
    ImporteStr,
    NombreCorto,
    ParametrosBusqueda,
    Peticion,
    Respuesta,
    fallo,
    sin_repetidos,
)


class EtiquetaCrear(Peticion):
    name: NombreCorto
    color: ColorHex | None = None


class EtiquetaActualizar(Actualizacion):
    name: NombreCorto | None = None
    color: ColorHex | None = None


class EtiquetaRefRespuesta(Respuesta):
    id: UUID
    name: str
    color: str | None = None


class EtiquetaRespuesta(EtiquetaRefRespuesta):
    created_at: datetime
    # include=stats
    transactions_count: int | None = None
    total_amount: ImporteStr | None = None


class EtiquetaFusionCrear(Peticion):
    """Mismas reglas que la fusión de temáticas (RN-17), con otras tablas."""

    source_ids: list[UUID] = Field(min_length=1, max_length=50)
    target_id: UUID

    @model_validator(mode="after")
    def _no_consigo_misma(self) -> EtiquetaFusionCrear:
        if self.target_id in self.source_ids:
            fallo("fusion_invalida", "No se puede fusionar una etiqueta consigo misma.")
        if not sin_repetidos(self.source_ids):
            fallo("fusion_invalida", "Hay etiquetas repetidas en la lista de origen.")
        return self


class EtiquetaFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset({"name", "transactions_count", "total_amount", "created_at"})
    ORDEN_POR_DEFECTO = "name"

    include: list[Literal["stats"]] = Field(default=[])
