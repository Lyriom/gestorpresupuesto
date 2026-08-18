"""Presupuesto mensual, asignaciones, reasignación, arrastre y cierre.

§3.7 y §4.6 del contrato. `PresupuestoRespuesta` es exactamente lo que consume
el componente `BudgetBar` del design system.

El estado de cada tramo de la barra no se redefine aquí: es `EstadoSegmento` de
`app/services/presupuesto.py`, que ya es quien lo calcula.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comun import (
    Actualizacion,
    ImporteStr,
    ParametrosListado,
    PeriodoPresupuesto,
    Peticion,
    Respuesta,
    fallo,
    sin_repetidos,
)
from app.services.presupuesto import EstadoSegmento

#: Tope de asignaciones por periodo: un árbol de seis niveles no da para más.
ASIGNACIONES_MAXIMAS = 500


class AsignacionCrear(Peticion):
    category_id: UUID
    amount: ImporteStr = Field(ge=0, description="RN-28: nunca negativo.")
    rollover_enabled: bool | None = None
    note: str | None = Field(default=None, max_length=280)


class AsignacionActualizar(Actualizacion):
    """`PATCH` de una sola temática: la edición del campo en la tabla."""

    amount: ImporteStr | None = Field(default=None, ge=0)
    rollover_enabled: bool | None = None
    note: str | None = Field(default=None, max_length=280)


class AsignacionesSustituirCrear(Peticion):
    """`PUT`: sustituye el reparto completo del periodo. Idempotente."""

    allocations: list[AsignacionCrear] = Field(max_length=ASIGNACIONES_MAXIMAS)
    remove_missing: bool = Field(default=True, description="Las temáticas ausentes se dejan a 0.")

    @model_validator(mode="after")
    def _sin_repetidos(self) -> AsignacionesSustituirCrear:
        if not sin_repetidos([asignacion.category_id for asignacion in self.allocations]):
            fallo("datos_invalidos", "Hay dos asignaciones para la misma temática.")
        return self


class AsignacionRespuesta(Respuesta):
    category_id: UUID
    category: CategoriaRefRespuesta
    allocated: ImporteStr
    rollover_in: ImporteStr = Field(
        description="Sobrante que entra del periodo anterior (F-26, RN-32)."
    )
    available: ImporteStr = Field(description="allocated + rollover_in − spent.")
    spent: ImporteStr
    spent_pct: float = Field(ge=0, description="1.0 = presupuesto justo consumido.")
    overspent: ImporteStr = Field(ge=0, description="max(0, spent − allocated − rollover_in).")
    state: EstadoSegmento = Field(
        default=EstadoSegmento.SIN_ASIGNAR,
        description="Tramo de la barra tal y como lo clasifica el servicio.",
    )
    rollover_enabled: bool
    is_locked: bool
    note: str | None = None
    children: list[AsignacionRespuesta] = Field(default_factory=list)


class PresupuestoAjustesCrear(Peticion):
    """`PUT /budgets/{period}`: ingreso previsto (F-01), arrastre y notas."""

    planned_income: ImporteStr | None = Field(default=None, ge=0)
    rollover_default: bool | None = None
    note: str | None = Field(default=None, max_length=1000)


class PresupuestoRespuesta(Respuesta):
    """El payload del `BudgetBar`."""

    period: PeriodoPresupuesto
    currency: str
    is_closed: bool
    closed_at: datetime | None = None
    income_actual: ImporteStr = Field(description="Suma de ingresos reales del periodo (F-01).")
    planned_income: ImporteStr | None = None
    income: ImporteStr = Field(
        description="El 100 % del carril: planned_income si existe, si no income_actual (RN-35)."
    )
    allocated_total: ImporteStr
    spent_total: ImporteStr
    unassigned: ImporteStr = Field(description="income − allocated_total. Puede ser negativo.")
    overallocated: ImporteStr = Field(ge=0, description="max(0, allocated_total − income).")
    rollover_in_total: ImporteStr
    #: Del periodo, no del mes: en la semana que empieza el 10 de agosto, el día 13
    #: es el 4 de 7. `days_in_period` baja a 7, que es por lo que no puede seguir
    #: exigiendo un mínimo de 28.
    day_of_period: int = Field(ge=1, le=31)
    days_in_period: int = Field(ge=1, le=31)
    allocations: list[AsignacionRespuesta] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    note: str | None = None


class PresupuestoResumenRespuesta(Respuesta):
    """Una fila del selector de periodo."""

    period: PeriodoPresupuesto
    income: ImporteStr
    allocated_total: ImporteStr
    spent_total: ImporteStr
    is_closed: bool


class PresupuestoReasignarCrear(Peticion):
    """El arrastre en la barra: mover presupuesto de una temática a otra (RN-29)."""

    from_category_id: UUID
    to_category_id: UUID
    amount: ImporteStr = Field(gt=0)

    @model_validator(mode="after")
    def _distintas(self) -> PresupuestoReasignarCrear:
        if self.from_category_id == self.to_category_id:
            fallo("datos_invalidos", "Elige dos temáticas distintas.")
        return self


class PresupuestoCopiarCrear(Peticion):
    source_period: PeriodoPresupuesto
    strategy: Literal["absolute", "proportional"] = "absolute"
    overwrite: bool = False
    only_missing: bool = True


class PresupuestoDistribuirCrear(Peticion):
    strategy: Literal["equal", "last_period_share", "average_3m"] = "last_period_share"
    category_ids: list[UUID] = Field(default_factory=list, max_length=ASIGNACIONES_MAXIMAS)
    amount: ImporteStr | None = Field(
        default=None, gt=0, description="Por defecto, todo lo que quede sin asignar."
    )


class ArrastreRespuesta(Respuesta):
    """De dónde viene el rollover entrante de cada temática (F-26, RN-32)."""

    category_id: UUID
    category: CategoriaRefRespuesta
    previous_period: PeriodoPresupuesto
    previous_allocated: ImporteStr
    previous_spent: ImporteStr
    carried_in: ImporteStr
    carried_negative: bool


class PresupuestoFiltro(ParametrosListado):
    CAMPOS_ORDENABLES = frozenset({"period"})
    ORDEN_POR_DEFECTO = "-period"

    period_from: PeriodoPresupuesto | None = None
    period_to: PeriodoPresupuesto | None = None


class PresupuestoDetalleFiltro(ParametrosListado):
    """Parámetros de `GET /budgets/{period}`."""

    include_archived: bool = False
    depth: int | None = Field(
        default=None, ge=1, le=6, description="Nivel máximo del árbol que se devuelve."
    )


AsignacionRespuesta.model_rebuild()
