"""Reglas de auto-categorización (F-27): §3.11 y §4.8 del contrato.

El motor de evaluación es `app/services/reglas.py`, con su propio vocabulario en
castellano (`Campo`, `Operador`). El contrato expone el vocabulario en inglés,
que es el que ya consume el frontend, así que aquí se declara la correspondencia
una sola vez y `a_condicion()` construye la `Condicion` del servicio. No se
reimplementa ni la evaluación ni la normalización de texto.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.core.errors import ReglaDeNegocio
from app.schemas.comun import (
    Actualizacion,
    Nombre,
    ParametrosBusqueda,
    Peticion,
    Respuesta,
    RespuestaSellada,
    fallo,
    sin_repetidos,
)
from app.schemas.transaccion import TransaccionRespuesta
from app.services.reglas import Campo, Condicion, Operador

#: RN-58: patrón acotado, para no abrir la puerta a un ReDoS.
LONGITUD_MAXIMA_REGEX = 200
CONDICIONES_MAXIMAS = 10


class CampoRegla(StrEnum):
    PAYEE = "payee"
    DESCRIPTION = "description"
    NOTE = "note"
    AMOUNT = "amount"
    ACCOUNT = "account"
    DATE = "date"


class OperadorRegla(StrEnum):
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EQUALS = "equals"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    REGEX = "regex"
    GT = "gt"
    LT = "lt"
    BETWEEN = "between"


#: Campos que el motor del servicio sabe evaluar. `note` y `date` son del
#: contrato y todavía no tienen equivalente en `MovimientoEvaluable`: se aceptan
#: y las resuelve la capa de servicio, no este mapa.
A_CAMPO_SERVICIO: dict[CampoRegla, Campo] = {
    CampoRegla.PAYEE: Campo.COMERCIO,
    CampoRegla.DESCRIPTION: Campo.DESCRIPCION,
    CampoRegla.AMOUNT: Campo.IMPORTE,
    CampoRegla.ACCOUNT: Campo.CUENTA,
}

A_OPERADOR_SERVICIO: dict[OperadorRegla, Operador] = {
    OperadorRegla.CONTAINS: Operador.CONTIENE,
    OperadorRegla.NOT_CONTAINS: Operador.NO_CONTIENE,
    OperadorRegla.EQUALS: Operador.ES_IGUAL,
    OperadorRegla.STARTS_WITH: Operador.EMPIEZA_POR,
    OperadorRegla.ENDS_WITH: Operador.TERMINA_EN,
    OperadorRegla.REGEX: Operador.COINCIDE_REGEX,
    OperadorRegla.GT: Operador.MAYOR_QUE,
    OperadorRegla.LT: Operador.MENOR_QUE,
    OperadorRegla.BETWEEN: Operador.ENTRE,
}

#: Operadores que no tienen sentido sobre un campo de texto.
_OPERADORES_NUMERICOS = {OperadorRegla.GT, OperadorRegla.LT, OperadorRegla.BETWEEN}
_CAMPOS_NUMERICOS = {CampoRegla.AMOUNT, CampoRegla.DATE}


class CondicionRegla(Peticion):
    field: CampoRegla
    operator: OperadorRegla
    value: str = Field(min_length=1, max_length=LONGITUD_MAXIMA_REGEX)
    value_to: str | None = Field(default=None, max_length=LONGITUD_MAXIMA_REGEX)

    @model_validator(mode="after")
    def _coherente(self) -> CondicionRegla:
        if self.operator is OperadorRegla.REGEX:
            # RN-58: patrón compilable. Un patrón catastrófico no se detecta
            # compilando, así que el motor lo evalúa además con límite de tiempo.
            try:
                re.compile(self.value)
            except re.error as exc:
                fallo("datos_invalidos", f"La expresión regular no es válida: {exc}")
        if self.operator is OperadorRegla.BETWEEN and self.value_to is None:
            fallo("datos_invalidos", "Indica el segundo valor del rango.")
        # Las mismas dos incompatibilidades que impone `Condicion.__post_init__`
        # del servicio: se comprueban aquí para que el error llegue como 422 del
        # formulario y no como excepción del motor.
        if self.operator in _OPERADORES_NUMERICOS and self.field not in _CAMPOS_NUMERICOS:
            fallo(
                "datos_invalidos",
                "Los operadores de comparación solo se aplican al importe o a la fecha.",
            )
        if self.operator not in _OPERADORES_NUMERICOS and self.field is CampoRegla.AMOUNT:
            fallo(
                "datos_invalidos", "Sobre el importe solo se puede comparar: mayor, menor o entre."
            )
        return self

    def a_condicion(self) -> Condicion:
        """Traduce la condición al vocabulario del motor de `services/reglas.py`.

        Se llama desde la capa de servicio, ya fuera de la validación del cuerpo,
        así que el error se lanza como `AppError` —que el manejador convierte en
        el 422 del contrato— y no como error de esquema.
        """
        campo = A_CAMPO_SERVICIO.get(self.field)
        if campo is None:
            raise ReglaDeNegocio(
                f"Todavía no se pueden evaluar reglas sobre «{self.field.value}».",
                codigo="datos_invalidos",
            )
        return Condicion(
            campo=campo,
            operador=A_OPERADOR_SERVICIO[self.operator],
            valor=self.value,
            valor_hasta=self.value_to,
        )


class AccionesRegla(Peticion):
    set_category_id: UUID | None = None
    set_payee_id: UUID | None = None
    add_tag_ids: list[UUID] = Field(default_factory=list, max_length=10)
    set_note: str | None = Field(default=None, max_length=500)
    mark_as_transfer: bool = False
    stop_processing: bool = Field(default=True, description="No evaluar más reglas si casa.")

    @model_validator(mode="after")
    def _algo_que_hacer(self) -> AccionesRegla:
        if not any(
            (
                self.set_category_id,
                self.set_payee_id,
                self.add_tag_ids,
                self.set_note,
                self.mark_as_transfer,
            )
        ):
            fallo("datos_invalidos", "La regla no hace nada: indica al menos una acción.")
        return self


class ReglaCrear(Peticion):
    name: Nombre
    match: Literal["all", "any"] = "all"
    conditions: list[CondicionRegla] = Field(min_length=1, max_length=CONDICIONES_MAXIMAS)
    actions: AccionesRegla
    priority: int = Field(
        default=100, ge=0, le=10_000, description="RN-55: se evalúan de menor a mayor."
    )
    is_active: bool = True
    apply_to_imports: bool = True
    apply_to_invoices: bool = True


class ReglaActualizar(Actualizacion):
    name: Nombre | None = None
    match: Literal["all", "any"] | None = None
    conditions: list[CondicionRegla] | None = Field(
        default=None, min_length=1, max_length=CONDICIONES_MAXIMAS
    )
    actions: AccionesRegla | None = None
    priority: int | None = Field(default=None, ge=0, le=10_000)
    is_active: bool | None = None
    apply_to_imports: bool | None = None
    apply_to_invoices: bool | None = None


class ReglaRespuesta(RespuestaSellada):
    name: str
    match: Literal["all", "any"]
    conditions: list[CondicionRegla]
    actions: AccionesRegla
    priority: int
    is_active: bool
    apply_to_imports: bool = True
    apply_to_invoices: bool = True
    applied_count: int = 0
    last_applied_at: datetime | None = None
    disabled_reason: str | None = Field(
        default=None, description="RN-59: la temática se archivó, o el patrón era catastrófico."
    )


class ReglaReordenarCrear(Peticion):
    """El orden de la lista es el orden de evaluación (RN-55)."""

    ids: list[UUID] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _sin_repetidos(self) -> ReglaReordenarCrear:
        if not sin_repetidos(self.ids):
            fallo("datos_invalidos", "Hay una regla repetida en la lista.")
        return self


class ReglaProbarCrear(Peticion):
    """Prueba una regla sin guardarla, contra un texto o contra el histórico."""

    rule: ReglaCrear
    sample_text: str | None = Field(default=None, max_length=500)
    against_history: bool = True
    limit: int = Field(default=20, ge=1, le=200)


class ReglaProbarRespuesta(Respuesta):
    matches: int
    sample_matched: bool | None = None
    transactions: list[TransaccionRespuesta] = Field(default_factory=list)


class ReglaAplicarCrear(Peticion):
    rule_ids: list[UUID] = Field(default_factory=list, description="Vacío = todas las activas.")
    scope: Literal["uncategorized", "all"] = "uncategorized"
    date_from: date | None = None
    date_to: date | None = None
    account_id: UUID | None = None
    dry_run: bool = True


class ReglaAplicadaRespuesta(Respuesta):
    rule_id: UUID
    name: str
    matched: int
    updated: int


class ReglaAplicarResultadoRespuesta(Respuesta):
    dry_run: bool
    evaluated: int
    matched: int
    updated: int
    manual_preserved: int = Field(
        default=0, description="RN-56: categorizaciones manuales que no se han pisado."
    )
    by_rule: list[ReglaAplicadaRespuesta] = Field(default_factory=list)


class ReglaTextoCrear(Peticion):
    """P2 (F-59): «si comercio contiene "mercadona" -> Alimentación»."""

    text: str = Field(min_length=3, max_length=2000)


class ReglaFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset({"priority", "name", "applied_count", "created_at"})
    ORDEN_POR_DEFECTO = "priority"

    is_active: bool | None = None
    category_id: UUID | None = None


def condiciones_de(datos: list[dict[str, Any]]) -> list[Condicion]:
    """Atajo para la capa de servicio: valida y traduce en un paso."""
    return [CondicionRegla.model_validate(fila).a_condicion() for fila in datos]
