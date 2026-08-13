"""Importación de extractos CSV, OFX y QIF: §3.17 y §4.11 del contrato.

El estado de cada fila y el mapeo de columnas son los del servicio
(`EstadoFila`, `MapeoColumnas` de `app/services/importacion.py`). El contrato
habla de columnas **por nombre**, porque es lo que el usuario ve en la cabecera
del CSV, mientras que el servicio trabaja con **índices**; la traducción está en
`MapeoImportacionCrear.a_mapeo_columnas()`, en un solo sitio.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.core.errors import ReglaDeNegocio
from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comercio import ComercioRefRespuesta
from app.schemas.comun import (
    Actualizacion,
    ImporteStr,
    Nombre,
    ParametrosListado,
    Peticion,
    Respuesta,
    RespuestaSellada,
    fallo,
)
from app.services.importacion import EstadoFila, MapeoColumnas

#: `date` es además el nombre de un campo, y un campo con valor por defecto
#: oculta el tipo dentro de la clase: en esas anotaciones se usa este alias.
Fecha = date


class FormatoImportacion(StrEnum):
    """RN-66: se detecta por contenido, nunca por la extensión del nombre."""

    CSV = "csv"
    OFX = "ofx"
    QIF = "qif"


class EstadoImportacion(StrEnum):
    ANALYZING = "analyzing"
    NEEDS_MAPPING = "needs_mapping"
    READY = "ready"
    COMMITTED = "committed"
    FAILED = "failed"
    DISCARDED = "discarded"


class ImportacionSubirCrear(Peticion):
    """Campos que acompañan al `fichero` en el `multipart` de `POST /imports`."""

    account_id: UUID
    format: FormatoImportacion | None = Field(
        default=None, description="Solo como pista: manda lo que diga el contenido (RN-66)."
    )
    mapping_id: UUID | None = None


class MapeoImportacionCrear(Peticion):
    """Mapeo de columnas del CSV, formato de fecha, separadores y signo."""

    date_column: str = Field(min_length=1, max_length=120)
    amount_column: str | None = Field(default=None, max_length=120)
    debit_column: str | None = Field(default=None, max_length=120)
    credit_column: str | None = Field(default=None, max_length=120)
    description_column: str | None = Field(default=None, max_length=120)
    payee_column: str | None = Field(default=None, max_length=120)
    balance_column: str | None = Field(default=None, max_length=120)
    currency_column: str | None = Field(default=None, max_length=120)
    category_column: str | None = Field(default=None, max_length=120)
    date_format: str = Field(default="%d/%m/%Y", max_length=32)
    decimal_separator: Literal[",", "."] = ","
    thousands_separator: Literal[".", ",", " ", ""] = "."
    invert_sign: bool = False
    skip_rows: int = Field(default=0, ge=0, le=50)
    encoding: str = Field(default="utf-8", max_length=20)
    delimiter: str = Field(default=";", min_length=1, max_length=1)

    @model_validator(mode="after")
    def _importe_definido(self) -> MapeoImportacionCrear:
        """RN-67: sin fecha e importe no hay `commit` posible."""
        if not self.amount_column and not (self.debit_column or self.credit_column):
            fallo(
                "mapeo_incompleto",
                "Indica la columna de importe, o las de cargo y abono.",
            )
        if self.decimal_separator == self.thousands_separator:
            fallo(
                "datos_invalidos",
                "El separador decimal y el de miles no pueden ser el mismo carácter.",
            )
        return self

    def a_mapeo_columnas(self, columnas: list[str]) -> MapeoColumnas:
        """Traduce nombres de columna a los índices que usa el servicio.

        El CSV del banco puede traer la cabecera con espacios o en mayúsculas, así
        que se compara sin distinguir caja ni espacios de los extremos. Una
        columna mapeada que no aparece en la cabecera es un error del usuario, no
        un dato a ignorar: si no se avisara, la importación saldría vacía.

        Se llama desde la capa de servicio, ya fuera de la validación del cuerpo,
        así que el error viaja como `AppError` y no como error de esquema.
        """
        indices = {texto.strip().lower(): posicion for posicion, texto in enumerate(columnas)}

        def indice(nombre: str | None) -> int | None:
            if not nombre:
                return None
            posicion = indices.get(nombre.strip().lower())
            if posicion is None:
                raise ReglaDeNegocio(
                    f"El fichero no tiene ninguna columna «{nombre}».",
                    codigo="mapeo_incompleto",
                )
            return posicion

        return MapeoColumnas(
            fecha=indice(self.date_column),
            concepto=indice(self.description_column or self.payee_column),
            importe=indice(self.amount_column),
            cargo=indice(self.debit_column),
            abono=indice(self.credit_column),
            saldo=indice(self.balance_column),
            divisa=indice(self.currency_column),
            categoria=indice(self.category_column),
        )


class MapeoGuardarCrear(Peticion):
    """Mapeo guardado por banco, para no repetir la configuración."""

    name: Nombre
    bank: str | None = Field(default=None, max_length=120)
    mapping: MapeoImportacionCrear


class MapeoRespuesta(RespuestaSellada):
    name: str
    bank: str | None = None
    format: FormatoImportacion = FormatoImportacion.CSV
    mapping: MapeoImportacionCrear
    times_used: int = 0
    last_used_at: datetime | None = None


class FilaImportacionRespuesta(Respuesta):
    """Una fila interpretada, revisable antes del `commit` (RN-67)."""

    id: UUID
    row_number: int
    raw: dict[str, str] = Field(default_factory=dict)
    date: Fecha | None = None
    amount: ImporteStr | None = None
    description: str | None = None
    payee_name: str | None = None
    balance: ImporteStr | None = None
    status: EstadoFila = Field(
        default=EstadoFila.VALIDA, description="Estado tal y como lo clasifica el servicio."
    )
    suggested_payee: ComercioRefRespuesta | None = None
    suggested_category: CategoriaRefRespuesta | None = None
    matched_rule_id: UUID | None = None
    is_duplicate: bool = False
    duplicate_of_id: UUID | None = None
    is_skipped: bool = False
    error: str | None = None
    fingerprint: str | None = Field(
        default=None, description="Huella de fecha + importe + concepto (RN-68)."
    )


class FilaImportacionActualizar(Actualizacion):
    """Corrección de una fila antes de confirmar."""

    date: Fecha | None = None
    amount: ImporteStr | None = None
    description: str | None = Field(default=None, max_length=200)
    payee_id: UUID | None = None
    payee_name: str | None = Field(default=None, max_length=120)
    category_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2000)
    is_skipped: bool | None = None
    is_duplicate: bool | None = None


class ImportacionRespuesta(RespuestaSellada):
    status: EstadoImportacion
    format: FormatoImportacion
    account_id: UUID
    filename: str
    size_bytes: int
    checksum: str
    detected_columns: list[str] = Field(default_factory=list)
    detected_delimiter: str | None = None
    detected_encoding: str | None = None
    mapping: MapeoImportacionCrear | None = None
    rows_total: int = 0
    rows_valid: int = 0
    rows_duplicated: int = 0
    rows_skipped: int = 0
    rows_error: int = 0
    date_from: date | None = None
    date_to: date | None = None
    committed_at: datetime | None = None
    rolled_back_at: datetime | None = None
    transactions_created: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class ImportacionEstadoRespuesta(Respuesta):
    """Sondeo del análisis, con `Retry-After`."""

    id: UUID
    status: EstadoImportacion
    progress: int = Field(ge=0, le=100)
    rows_total: int = 0
    rows_valid: int = 0
    rows_error: int = 0
    missing_fields: list[str] = Field(
        default_factory=list, description="Lo que falta por mapear (RN-67)."
    )
    error: str | None = None
    retry_after_seconds: int | None = None


class ImportacionConfirmarCrear(Peticion):
    skip_duplicates: bool = Field(default=True, description="RN-68: el usuario decide.")
    apply_rules: bool = True
    create_missing_payees: bool = True
    default_category_id: UUID | None = None


class ImportacionResultadoRespuesta(Respuesta):
    import_id: UUID
    transactions_created: int
    transactions_deleted: int = 0
    duplicates_skipped: int = 0
    rows_failed: int = 0
    rules_applied: int = 0
    payees_created: int = 0
    warnings: list[str] = Field(default_factory=list)


class ImportacionFiltro(ParametrosListado):
    CAMPOS_ORDENABLES = frozenset({"created_at", "committed_at", "rows_total"})
    ORDEN_POR_DEFECTO = "-created_at"

    status: list[EstadoImportacion] = Field(default=[])
    account_id: UUID | None = None


class FilaImportacionFiltro(ParametrosListado):
    CAMPOS_ORDENABLES = frozenset({"row_number", "date", "amount"})
    ORDEN_POR_DEFECTO = "row_number"

    only_duplicates: bool = False
    only_errors: bool = False
