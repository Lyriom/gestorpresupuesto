"""Tipos base, sobre de paginación y forma del error.

Implementa §1.2 (formato de error), §1.4 (paginación `page`/`size` con total),
§1.5 (filtrado), §1.6 (ordenación), §1.7 (importes como cadena decimal) y §4.1
del contrato `docs/arquitectura/api.md`.

Nomenclatura de toda la capa de esquemas
----------------------------------------
El contrato nombra los esquemas en inglés con los sufijos `…In`, `…UpdateIn` y
`…Out`. Aquí se usan los sufijos en castellano que pide el proyecto, con una
correspondencia mecánica y sin excepciones:

    XxxIn        → XxxCrear
    XxxUpdateIn  → XxxActualizar
    XxxOut       → XxxRespuesta

Los **nombres de campo** son los del contrato, en inglés, porque son los que
viajan por el cable y los que ya consume el frontend.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, ClassVar, NoReturn
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
)
from pydantic_core import PydanticCustomError

from app.services.presupuesto import ErrorPresupuesto, validar_periodo

# --------------------------------------------------------------------------- #
# Errores de validación con mensaje propio
# --------------------------------------------------------------------------- #


def fallo(codigo: str, mensaje: str) -> NoReturn:
    """Aborta la validación con un mensaje que llega intacto al cliente.

    `app/core/errors.py` traduce los tipos de error estándar de Pydantic a
    frases genéricas: un `ValueError` a secas se convierte en «El valor no es
    válido» y se pierde la explicación. Con un tipo propio —el `codigo` del
    catálogo de §1.2— el manejador no encuentra traducción y usa este texto tal
    cual, que es el que ve el usuario.
    """
    raise PydanticCustomError(codigo, mensaje)


# --------------------------------------------------------------------------- #
# Importes: cadena decimal, nunca número JSON (§1.7)
# --------------------------------------------------------------------------- #

# Ni moneda, ni separador de miles, ni espacios: eso es cosa de la capa de
# presentación (`formato.ts`), no del contrato.
_CARACTERES_PROHIBIDOS = ("€", "$", "£", "%", " ", "\t", "'", "_")


def _texto_decimal(valor: Any) -> Any:
    """Rechaza toda forma de importe que perdería precisión o sea ambigua."""
    if isinstance(valor, bool):
        fallo("importe_invalido", "El importe no es un número.")
    if isinstance(valor, float):
        fallo(
            "importe_no_es_cadena",
            'Envía el importe como cadena de texto con punto decimal: "12.34".',
        )
    if isinstance(valor, str):
        texto = valor.strip()
        if "," in texto:
            fallo(
                "importe_con_coma",
                'Usa el punto como separador decimal y sin separador de miles: "1234.56".',
            )
        if any(caracter in texto for caracter in _CARACTERES_PROHIBIDOS):
            fallo(
                "importe_con_simbolos",
                'Envía solo el número, sin símbolo de moneda ni espacios: "1234.56".',
            )
        if "e" in texto.lower():
            fallo(
                "importe_notacion_cientifica",
                'No se admite la notación científica: escribe "0.0001".',
            )
        return texto
    return valor


def _serializar_importe(valor: Decimal) -> str:
    """Dinero: siempre dos decimales exactos, «45.00» y no «45»."""
    return f"{valor:.2f}"


def _serializar_precio(valor: Decimal) -> str:
    """Precio unitario y cantidad: decimales significativos hasta cuatro."""
    return format(valor.normalize(), "f")


#: Dinero: 2 decimales, 14 dígitos, igual que `Numeric(14, 2)` de la base.
ImporteStr = Annotated[
    Decimal,
    BeforeValidator(_texto_decimal),
    Field(max_digits=14, decimal_places=2, examples=["45.00"]),
    PlainSerializer(_serializar_importe, return_type=str, when_used="json"),
]

#: Precio unitario: 4 decimales, porque el kWh de la factura de la luz llega con
#: cuatro o seis y redondearlo a céntimos falsearía el histórico (RN-61).
PrecioStr = Annotated[
    Decimal,
    BeforeValidator(_texto_decimal),
    Field(max_digits=16, decimal_places=4, examples=["0.1487"]),
    PlainSerializer(_serializar_precio, return_type=str, when_used="json"),
]

#: Cantidad: la misma precisión que el precio (3,472 kWh; 0,850 kg).
CantidadStr = PrecioStr


# --------------------------------------------------------------------------- #
# Periodo, moneda, color y otros tipos escalares
# --------------------------------------------------------------------------- #

PATRON_PERIODO = r"^\d{4}-(0[1-9]|1[0-2])$"
ANYO_MINIMO = 1970
ANYO_MAXIMO = 2200


def _validar_periodo(valor: Any) -> Any:
    """RN-30: `AAAA-MM` con año entre 1970 y 2200.

    El formato lo comprueba el servicio de presupuesto, que ya es la única
    definición del patrón; aquí solo se traduce su error al formato de la API y
    se añade el rango de años, que es una regla de la capa de contrato.
    """
    if not isinstance(valor, str):
        fallo("periodo_invalido", "El periodo debe ser una cadena con el formato AAAA-MM.")
    try:
        validar_periodo(valor)
    except ErrorPresupuesto as exc:
        fallo("periodo_invalido", str(exc))
    if not ANYO_MINIMO <= int(valor[:4]) <= ANYO_MAXIMO:
        fallo(
            "periodo_invalido",
            f"El año del periodo debe estar entre {ANYO_MINIMO} y {ANYO_MAXIMO}.",
        )
    return valor


def _validar_moneda(valor: Any) -> Any:
    if not isinstance(valor, str):
        fallo("moneda_invalida", "La moneda debe ser un código de tres letras, por ejemplo EUR.")
    texto = valor.strip().upper()
    if len(texto) != 3 or not texto.isalpha() or not texto.isascii():
        fallo(
            "moneda_invalida",
            "La moneda debe ser un código ISO 4217 de tres letras, por ejemplo EUR.",
        )
    return texto


def _validar_color(valor: Any) -> Any:
    if not isinstance(valor, str) or len(valor) != 7 or valor[0] != "#":
        fallo(
            "color_invalido", "El color debe ser hexadecimal de seis dígitos, por ejemplo #1e88e5."
        )
    if any(caracter not in "0123456789abcdefABCDEF" for caracter in valor[1:]):
        fallo(
            "color_invalido", "El color debe ser hexadecimal de seis dígitos, por ejemplo #1e88e5."
        )
    return valor.lower()


#: Periodo de presupuesto (RN-30). El patrón se declara además para OpenAPI.
Periodo = Annotated[
    str,
    StringConstraints(pattern=PATRON_PERIODO),
    BeforeValidator(_validar_periodo),
    Field(examples=["2026-08"]),
]
Moneda = Annotated[str, BeforeValidator(_validar_moneda), Field(examples=["EUR"])]
ColorHex = Annotated[str, BeforeValidator(_validar_color), Field(examples=["#1e88e5"])]
Nombre = Annotated[str, StringConstraints(min_length=1, max_length=120)]
NombreCorto = Annotated[str, StringConstraints(min_length=1, max_length=40)]
Confianza = Annotated[float, Field(ge=0.0, le=1.0)]
Puntuacion = Annotated[float, Field(ge=0.0, le=100.0)]

#: Ventana de fechas admisible para un movimiento (RN-27).
FECHA_MINIMA = date(1970, 1, 1)
DIAS_FUTURO_MAXIMO = 365


def validar_fecha_movimiento(valor: date) -> date:
    """RN-27: ni antes de 1970 ni más de un año en el futuro.

    Un error de teclado en el año («2062» por «2026») descolocaría todos los
    informes sin que nada más lo delate, así que se corta en el borde.
    """
    if valor < FECHA_MINIMA:
        fallo("fecha_invalida", "La fecha es demasiado antigua: debe ser posterior a 1970.")
    if valor > date.today() + timedelta(days=DIAS_FUTURO_MAXIMO):
        fallo("fecha_invalida", "La fecha no puede estar más de un año en el futuro.")
    return valor


#: Fecha de un movimiento, ya acotada por RN-27.
FechaMovimiento = Annotated[date, AfterValidator(validar_fecha_movimiento)]


# --------------------------------------------------------------------------- #
# Bases de petición y de respuesta
# --------------------------------------------------------------------------- #


class Peticion(BaseModel):
    """Base de los cuerpos de petición: rechaza campos desconocidos.

    `extra="forbid"` es deliberado: un campo mal escrito es un error del
    cliente, no algo a ignorar, y además cierra la asignación masiva (§8.5) —un
    `user_id` en el cuerpo se rechaza en vez de colarse (RN-01).
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
        populate_by_name=True,
    )


class Respuesta(BaseModel):
    """Base de las respuestas: se construyen desde modelos de SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class RespuestaSellada(Respuesta):
    """Respuesta de una entidad con identificador y sellos de tiempo."""

    id: UUID
    created_at: datetime
    updated_at: datetime


class Actualizacion(Peticion):
    """Base de los `PATCH`: todos los campos son opcionales.

    Quien consume estos esquemas distingue «no enviado» de «puesto a nulo» con
    `model_dump(exclude_unset=True)`, nunca comparando con `None`.
    """

    @field_validator("*", mode="before")
    @classmethod
    def _cadena_vacia_es_nula(cls, valor: Any) -> Any:
        """Un control de formulario vaciado llega como `""` y significa «bórralo».

        Convertirlo a `None` deja el campo presente en `exclude_unset`, así que
        el servicio lo escribe como `NULL` en vez de guardar una cadena vacía.
        """
        return None if valor == "" else valor


# --------------------------------------------------------------------------- #
# Sobre de paginación (§1.4)
# --------------------------------------------------------------------------- #


class Pagina[T](BaseModel):
    """Sobre único de todos los listados."""

    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    page: int = Field(ge=1, examples=[1])
    size: int = Field(ge=1, le=200, examples=[50])
    total: int = Field(ge=0, examples=[1284])
    pages: int = Field(ge=0, examples=[26])
    next_cursor: str | None = Field(
        default=None, description="Solo en modo cursor; en modo página va a null."
    )

    @classmethod
    def crear(
        cls,
        items: list[T],
        *,
        page: int = 1,
        size: int = 50,
        total: int | None = None,
        next_cursor: str | None = None,
    ) -> Pagina[T]:
        """Monta el sobre calculando `pages`, que siempre es derivado."""
        cuantos = len(items) if total is None else total
        paginas = -(-cuantos // size) if size else 0
        return cls(
            items=items, page=page, size=size, total=cuantos, pages=paginas, next_cursor=next_cursor
        )


class ResultadoLoteRespuesta(Respuesta):
    """Resultado de una operación en bloque (`bulk-*`, `read-all`, `recompute`)."""

    affected: int
    skipped: int = 0
    errors: list[dict[str, str]] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Parámetros de consulta (§1.4, §1.5, §1.6)
# --------------------------------------------------------------------------- #

TAMANYOS_UI = (25, 50, 100, 200)


class ParametrosListado(BaseModel):
    """Base de los esquemas de consulta de los listados.

    `extra="ignore"`, al contrario que en los cuerpos: §1.5 exige que un filtro
    desconocido se ignore en silencio para no romper enlaces guardados cuando se
    retira un filtro.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    #: Campos por los que este listado admite ordenar (§1.6). Sin whitelist no
    #: se ordena por nada: nunca se interpola texto del cliente en el ORDER BY.
    CAMPOS_ORDENABLES: ClassVar[frozenset[str]] = frozenset()
    ORDEN_POR_DEFECTO: ClassVar[str] = ""

    page: int = Field(default=1, ge=1)
    size: int = Field(default=50, ge=1, le=200, examples=list(TAMANYOS_UI))
    sort: str | None = Field(default=None, max_length=120)
    cursor: str | None = Field(
        default=None,
        max_length=200,
        description="Modo alternativo: si se envía, se ignora `page` y no se calcula `total`.",
    )

    @field_validator("sort")
    @classmethod
    def _orden_en_la_whitelist(cls, valor: str | None) -> str | None:
        if not valor:
            return None
        for parte in valor.split(","):
            campo = parte.strip().lstrip("-")
            if campo and campo not in cls.CAMPOS_ORDENABLES:
                fallo("datos_invalidos", f"No se puede ordenar por «{campo}».")
        return valor

    @property
    def orden(self) -> list[tuple[str, bool]]:
        """Traduce `-date,amount` a [("date", True), ("amount", False)].

        El booleano es «descendente». El desempate por `id` lo añade siempre el
        repositorio, no el cliente, para que la paginación sea determinista.
        """
        texto = self.sort or self.ORDEN_POR_DEFECTO
        criterios: list[tuple[str, bool]] = []
        for parte in texto.split(","):
            campo = parte.strip()
            if campo:
                criterios.append((campo.lstrip("-"), campo.startswith("-")))
        return criterios

    @property
    def desplazamiento(self) -> int:
        return (self.page - 1) * self.size


class ParametrosBusqueda(ParametrosListado):
    """Listado con búsqueda de texto libre (§1.5)."""

    q: str | None = Field(
        default=None, min_length=2, max_length=120, description="Sin distinguir acentos ni caja."
    )

    @field_validator("q", mode="before")
    @classmethod
    def _vacio_es_ausente(cls, valor: Any) -> Any:
        return None if isinstance(valor, str) and not valor.strip() else valor


# El rango invertido (`date_from > date_to`) NO se valida aquí a propósito: §1.5
# lo tipifica como `400 error_solicitud` y un validador de esquema solo puede
# producir un `422`. Lo comprueba la capa de API con `AppError`.


# --------------------------------------------------------------------------- #
# Forma del error (§1.2). Se declara para que aparezca en OpenAPI; las
# respuestas las construye `app/core/errors.py`, que es el único que las emite.
# --------------------------------------------------------------------------- #


class ErrorDetalleRespuesta(Respuesta):
    campo: str = Field(examples=["splits.0.amount"])
    mensaje: str


class ErrorCuerpoRespuesta(Respuesta):
    codigo: str = Field(examples=["splits_no_cuadran"])
    mensaje: str
    detalles: list[ErrorDetalleRespuesta] = Field(default_factory=list)


class ErrorRespuesta(Respuesta):
    error: ErrorCuerpoRespuesta


def suma(importes: Iterable[Decimal]) -> Decimal:
    """Suma exacta en `Decimal` para los validadores que comparan al céntimo."""
    total = Decimal("0.00")
    for importe in importes:
        total += importe
    return total


def sin_repetidos(valores: Collection[Any]) -> bool:
    return len(set(valores)) == len(valores)
