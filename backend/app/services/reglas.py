"""Auto-categorización de movimientos por reglas del usuario.

Cuando el usuario apunta "MERCADONA 4021" veinte veces al mes, no debería tener
que elegir la temática cada vez. Estas reglas resuelven eso, y también se
aplican a lo que llega por importación de CSV o por líneas de factura.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.services.normalizacion import sin_acentos


class Campo(StrEnum):
    """Sobre qué se evalúa la regla."""

    DESCRIPCION = "descripcion"
    COMERCIO = "comercio"
    IMPORTE = "importe"
    CUENTA = "cuenta"


class Operador(StrEnum):
    CONTIENE = "contiene"
    NO_CONTIENE = "no_contiene"
    EMPIEZA_POR = "empieza_por"
    TERMINA_EN = "termina_en"
    ES_IGUAL = "es_igual"
    COINCIDE_REGEX = "coincide_regex"
    MAYOR_QUE = "mayor_que"
    MENOR_QUE = "menor_que"
    ENTRE = "entre"


OPERADORES_DE_TEXTO = frozenset(
    {
        Operador.CONTIENE,
        Operador.NO_CONTIENE,
        Operador.EMPIEZA_POR,
        Operador.TERMINA_EN,
        Operador.ES_IGUAL,
        Operador.COINCIDE_REGEX,
    }
)
OPERADORES_NUMERICOS = frozenset({Operador.MAYOR_QUE, Operador.MENOR_QUE, Operador.ENTRE})


class ErrorRegla(Exception):
    """La regla está mal definida."""


def normalizar(texto: str | None) -> str:
    """Texto comparable: sin tildes, en minúsculas y con espacios colapsados."""
    if not texto:
        return ""
    return re.sub(r"\s+", " ", sin_acentos(texto).lower()).strip()


@dataclass(slots=True)
class Condicion:
    """Una comparación sobre un campo del movimiento."""

    campo: Campo
    operador: Operador
    valor: str
    valor_hasta: str | None = None
    """Segundo operando, solo para el operador `entre`."""

    def __post_init__(self) -> None:
        if self.campo in (Campo.IMPORTE,) and self.operador in OPERADORES_DE_TEXTO:
            raise ErrorRegla(f"El operador '{self.operador}' no se puede usar sobre el importe.")
        if self.campo not in (Campo.IMPORTE,) and self.operador in OPERADORES_NUMERICOS:
            raise ErrorRegla(f"El operador '{self.operador}' solo se puede usar sobre el importe.")
        if self.operador is Operador.ENTRE and self.valor_hasta is None:
            raise ErrorRegla("El operador 'entre' necesita dos valores.")
        if not str(self.valor).strip():
            raise ErrorRegla("La condición necesita un valor.")
        if self.operador is Operador.COINCIDE_REGEX:
            try:
                re.compile(self.valor)
            except re.error as exc:
                raise ErrorRegla(f"La expresión regular no es válida: {exc}") from exc

    def evaluar(self, movimiento: MovimientoEvaluable) -> bool:
        if self.campo is Campo.IMPORTE:
            return self._evaluar_importe(movimiento.importe)
        texto = {
            Campo.DESCRIPCION: movimiento.descripcion,
            Campo.COMERCIO: movimiento.comercio,
            Campo.CUENTA: movimiento.cuenta,
        }[self.campo]
        return self._evaluar_texto(normalizar(texto))

    def _evaluar_texto(self, texto: str) -> bool:
        objetivo = normalizar(self.valor)
        match self.operador:
            case Operador.CONTIENE:
                return objetivo in texto
            case Operador.NO_CONTIENE:
                return objetivo not in texto
            case Operador.EMPIEZA_POR:
                return texto.startswith(objetivo)
            case Operador.TERMINA_EN:
                return texto.endswith(objetivo)
            case Operador.ES_IGUAL:
                return texto == objetivo
            case Operador.COINCIDE_REGEX:
                # Sobre el texto normalizado, para que el patrón no tenga que
                # preocuparse por tildes ni mayúsculas.
                return re.search(self.valor, texto, re.IGNORECASE) is not None
            case _:
                return False

    def _evaluar_importe(self, importe: Decimal | None) -> bool:
        if importe is None:
            return False
        # Se compara el valor absoluto: al usuario le da igual el signo cuando
        # escribe "más de 50 euros".
        valor = abs(importe)
        try:
            limite = abs(Decimal(str(self.valor).replace(",", ".")))
            match self.operador:
                case Operador.MAYOR_QUE:
                    return valor > limite
                case Operador.MENOR_QUE:
                    return valor < limite
                case Operador.ENTRE:
                    hasta = abs(Decimal(str(self.valor_hasta).replace(",", ".")))
                    inferior, superior = min(limite, hasta), max(limite, hasta)
                    return inferior <= valor <= superior
                case _:
                    return False
        except (ValueError, ArithmeticError):
            return False


@dataclass(slots=True)
class MovimientoEvaluable:
    """Los datos de un movimiento que las reglas pueden mirar."""

    descripcion: str | None = None
    comercio: str | None = None
    importe: Decimal | None = None
    cuenta: str | None = None


@dataclass(slots=True)
class Regla:
    """Un conjunto de condiciones y lo que se aplica si se cumplen."""

    regla_id: str
    nombre: str
    condiciones: list[Condicion]
    categoria_id: str | None = None
    comercio_id: str | None = None
    etiquetas: list[str] | None = None
    prioridad: int = 100
    """Menor número, mayor prioridad. La primera que coincide gana."""
    activa: bool = True
    exigir_todas: bool = True
    """True = todas las condiciones (Y); False = cualquiera (O)."""

    def __post_init__(self) -> None:
        if not self.condiciones:
            raise ErrorRegla("Una regla necesita al menos una condición.")
        if not (self.categoria_id or self.comercio_id or self.etiquetas):
            raise ErrorRegla("Una regla tiene que asignar algo: temática, comercio o etiquetas.")

    def coincide(self, movimiento: MovimientoEvaluable) -> bool:
        if not self.activa:
            return False
        resultados = (condicion.evaluar(movimiento) for condicion in self.condiciones)
        return all(resultados) if self.exigir_todas else any(resultados)


@dataclass(slots=True)
class Asignacion:
    """Lo que una regla ha decidido para un movimiento."""

    regla_id: str
    nombre_regla: str
    categoria_id: str | None = None
    comercio_id: str | None = None
    etiquetas: list[str] | None = None


def aplicar_reglas(
    movimiento: MovimientoEvaluable,
    reglas: list[Regla],
) -> Asignacion | None:
    """Primera regla que coincide, por orden de prioridad.

    Se para en la primera coincidencia en vez de acumular: si dos reglas
    asignan temáticas distintas, aplicar las dos daría un resultado
    impredecible según el orden de la lista.
    """
    for regla in sorted(reglas, key=lambda r: (r.prioridad, r.nombre)):
        if regla.coincide(movimiento):
            return Asignacion(
                regla_id=regla.regla_id,
                nombre_regla=regla.nombre,
                categoria_id=regla.categoria_id,
                comercio_id=regla.comercio_id,
                etiquetas=list(regla.etiquetas) if regla.etiquetas else None,
            )
    return None


def aplicar_a_lote(
    movimientos: list[MovimientoEvaluable],
    reglas: list[Regla],
) -> list[Asignacion | None]:
    """Aplica las reglas a una lista de movimientos, en el mismo orden.

    Las reglas se ordenan una sola vez: con un CSV de cientos de líneas,
    reordenarlas en cada iteración se nota.
    """
    ordenadas = sorted(reglas, key=lambda r: (r.prioridad, r.nombre))
    return [aplicar_reglas(movimiento, ordenadas) for movimiento in movimientos]


def sugerir_regla(
    descripcion: str,
    categoria_id: str,
    *,
    nombre: str | None = None,
) -> Regla:
    """Propone una regla a partir de un movimiento que el usuario acaba de categorizar.

    Se queda con la parte estable de la descripción: los bancos añaden números
    de operación y fechas que cambian en cada apunte, así que se descartan las
    palabras con dígitos y las muy cortas.

    De las que quedan se elige la más larga, que en los apuntes bancarios suele
    ser el nombre del comercio ("COMPRA 4021 MERCADONA SA" -> "mercadona"). Se
    usa una sola palabra a propósito: unir palabras no contiguas daría un patrón
    que ni siquiera coincidiría con el movimiento que lo ha originado.
    """
    palabras = [
        palabra
        for palabra in normalizar(descripcion).split()
        if len(palabra) > 2 and not any(caracter.isdigit() for caracter in palabra)
    ]
    if not palabras:
        raise ErrorRegla("No se puede deducir una regla de esta descripción: no hay texto estable.")
    patron = max(palabras, key=len)
    return Regla(
        regla_id="",
        nombre=nombre or f"Auto: {patron}",
        condiciones=[Condicion(Campo.DESCRIPCION, Operador.CONTIENE, patron)],
        categoria_id=categoria_id,
    )
