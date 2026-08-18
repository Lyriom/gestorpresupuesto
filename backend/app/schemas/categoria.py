"""Temáticas: árbol, movimiento, reordenación y fusión. §3.4 y §4.4 del contrato."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.comun import (
    Actualizacion,
    ColorHex,
    ImporteStr,
    Nombre,
    ParametrosBusqueda,
    PeriodoPresupuesto,
    Peticion,
    Respuesta,
    RespuestaSellada,
    fallo,
    sin_repetidos,
)

#: RN-11: hasta seis niveles (`depth` de 0 a 5).
PROFUNDIDAD_MAXIMA = 6

#: RN-20: una fusión se puede deshacer durante 30 días.
DIAS_PARA_DESHACER = 30


class TipoTematica(StrEnum):
    """RN-13: se hereda del padre y no cambia si ya hay histórico."""

    EXPENSE = "expense"
    INCOME = "income"


class CategoriaCrear(Peticion):
    name: Nombre
    parent_id: UUID | None = None
    kind: TipoTematica = TipoTematica.EXPENSE
    color: ColorHex | None = None
    icon: str | None = Field(default=None, max_length=40)
    rollover_enabled: bool = False
    is_locked: bool = Field(
        default=False,
        description="No reasignable arrastrando en la barra (hipoteca, seguros).",
    )
    monthly_target: ImporteStr | None = Field(default=None, ge=0)
    position: int | None = Field(default=None, ge=0)


class CategoriaActualizar(Actualizacion):
    """Renombrar NO rompe el histórico (F-05): el identificador no cambia.

    El padre no se cambia aquí: para eso está `POST /categories/{id}/move`, que
    es el único sitio donde se comprueban los ciclos y la profundidad (RN-11).
    """

    name: Nombre | None = None
    color: ColorHex | None = None
    icon: str | None = Field(default=None, max_length=40)
    rollover_enabled: bool | None = None
    is_locked: bool | None = None
    monthly_target: ImporteStr | None = Field(default=None, ge=0)
    is_default: bool | None = Field(
        default=None, description="Temática por defecto para los gastos sin clasificar."
    )


class CategoriaRefRespuesta(Respuesta):
    """Temática embebida en otra respuesta: lo justo para pintar un chip."""

    id: UUID
    name: str
    color: str | None = None


class CategoriaRespuesta(RespuestaSellada):
    name: str
    parent_id: UUID | None
    kind: TipoTematica
    path: str = Field(description="Ruta materializada de UUID: 'a1b2/…/f9e8' (§7.3).")
    depth: int = Field(ge=0, le=PROFUNDIDAD_MAXIMA - 1)
    position: int
    color: str | None
    icon: str | None
    rollover_enabled: bool
    is_locked: bool
    is_archived: bool
    is_default: bool = False
    monthly_target: ImporteStr | None
    children_count: int
    descendants_count: int
    ancestors: list[CategoriaRefRespuesta] = Field(
        default_factory=list, description="Miga de pan, de la raíz al padre."
    )
    # Solo con include=stats o ?period=
    transactions_count: int | None = None
    spent: ImporteStr | None = None
    allocated: ImporteStr | None = None


class CategoriaNodoRespuesta(CategoriaRespuesta):
    """Árbol anidado de `GET /categories/tree`, ya ordenado por `position`."""

    children: list[CategoriaNodoRespuesta] = Field(default_factory=list)


class CategoriaMoverCrear(Peticion):
    """Mueve y reordena: nuevo padre y/o nueva posición entre hermanos."""

    parent_id: UUID | None = Field(default=None, description="null la convierte en raíz.")
    position: int = Field(default=0, ge=0, description="Índice entre los hermanos.")


class CategoriaPosicionCrear(Peticion):
    id: UUID
    parent_id: UUID | None = None
    position: int = Field(ge=0)


class CategoriaReordenarCrear(Peticion):
    """Arrastrar y soltar varios hermanos de una vez."""

    items: list[CategoriaPosicionCrear] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _sin_repetidos(self) -> CategoriaReordenarCrear:
        if not sin_repetidos([item.id for item in self.items]):
            fallo("datos_invalidos", "Hay una temática repetida en la lista.")
        return self


class CategoriaFusionCrear(Peticion):
    """RN-17 a RN-20: ni consigo misma, ni con un descendiente, ni entre `kind` distintos.

    El parentesco y el `kind` se comprueban en el servicio, que es quien tiene el
    árbol; aquí solo lo que se ve en el propio cuerpo.
    """

    source_ids: list[UUID] = Field(min_length=1, max_length=50)
    target_id: UUID
    move_children: bool = Field(
        default=True, description="Los hijos de las origen pasan a la destino."
    )
    keep_source_names_as_alias: bool = Field(
        default=True, description="Guarda los nombres antiguos para poder buscar por ellos."
    )
    force: bool = Field(
        default=False,
        description="Reabre, recalcula y vuelve a cerrar los periodos cerrados (RN-20).",
    )

    @model_validator(mode="after")
    def _no_consigo_misma(self) -> CategoriaFusionCrear:
        if self.target_id in self.source_ids:
            fallo("fusion_invalida", "No se puede fusionar una temática consigo misma.")
        if not sin_repetidos(self.source_ids):
            fallo("fusion_invalida", "Hay temáticas repetidas en la lista de origen.")
        return self


class CategoriaFusionPreviaRespuesta(Respuesta):
    """Lo que se va a mover, antes de moverlo: es el diálogo de confirmación."""

    target: CategoriaRefRespuesta
    sources: list[CategoriaRefRespuesta]
    transactions: int
    splits: int
    invoice_lines: int
    rules: int
    recurring: int
    products: int
    payees: int = 0
    goals: int
    budget_periods: int
    allocations_merged: ImporteStr = Field(
        description="Suma de asignaciones que quedará en la temática destino (RN-20)."
    )
    children_moved: int
    conflicts: list[str] = Field(
        default_factory=list, description="Ej.: 'El periodo 2026-03 está cerrado'."
    )


class CategoriaFusionResultadoRespuesta(CategoriaFusionPreviaRespuesta):
    merge_id: UUID
    performed_at: datetime
    undo_available_until: datetime


class CategoriaFusionRespuesta(Respuesta):
    """Una fusión del registro de reasignación, deshacible 30 días (RN-20)."""

    id: UUID
    target: CategoriaRefRespuesta | None
    sources: list[CategoriaRefRespuesta] = Field(default_factory=list)
    rows_changed: int
    performed_at: datetime
    undo_available_until: datetime
    undone_at: datetime | None = None
    can_undo: bool


class CategoriaUsoRespuesta(Respuesta):
    """Dónde se usa: lo que se muestra antes de borrar o fusionar (RN-14)."""

    category_id: UUID
    transactions: int
    splits: int
    invoice_lines: int
    rules: int
    recurring: int
    goals: int
    allocations: int
    products: int = 0
    payees: int = 0
    first_used_on: date | None
    last_used_on: date | None
    can_hard_delete: bool = Field(description="False obliga a reasignar o archivar (RN-14).")


class CategoriaFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset({"name", "position", "depth", "spent", "allocated", "created_at"})
    ORDEN_POR_DEFECTO = "position"

    parent_id: UUID | None = None
    kind: TipoTematica | None = None
    max_depth: int | None = Field(default=None, ge=1, le=PROFUNDIDAD_MAXIMA)
    is_archived: bool | None = None
    #: Presupuestario, así que admite semana: la pantalla de Temáticas enseña lo
    #: gastado y lo asignado del periodo que se esté mirando, sea cual sea.
    period: PeriodoPresupuesto | None = Field(
        default=None, description="Trae `spent` y `allocated` de ese periodo."
    )
    include: list[Literal["stats"]] = Field(default=[])
