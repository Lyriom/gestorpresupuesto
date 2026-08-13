"""Formateo de cifras en español para los textos que ve el usuario.

El frontend formatea con `Intl` casi todo, pero hay mensajes que el backend
redacta enteros —los avisos del presupuesto, las alertas de subida de precio, los
resúmenes por correo— y ahí no puede colarse el `Decimal` en bruto: "250.00 €"
con punto decimal se lee como un error de la aplicación.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CERO = Decimal("0")

CENTIMO = Decimal("0.01")
"""Escala del dinero: los dos decimales de `numeric(14,2)`."""

CUATRO_DECIMALES = Decimal("0.0001")
"""Escala de los precios unitarios: el kWh a `0,1489 €` los pierde con dos."""


def cuantizar(valor: Decimal, escala: Decimal = CENTIMO) -> Decimal:
    """Cuantiza un importe con el redondeo del dinero: `ROUND_HALF_UP`.

    Es el único sitio del proyecto donde se decide el modo de redondeo de un
    importe. `Decimal.quantize()` sin `rounding=` usa el del contexto, que en
    Python es `ROUND_HALF_EVEN` (redondeo bancario): con él `12,345 €` se
    convierte en `12,34 €` y `12,355 €` en `12,36 €`, o sea que el empate cae
    a un lado o a otro según la cifra anterior. PostgreSQL redondea siempre al
    alza al guardar en `numeric(14,2)`, así que el mismo importe salía distinto
    según quién lo cuantizase.

    No vale para porcentajes, proporciones ni tipos de interés: esos no son
    dinero y su escala la fija su propia columna.
    """
    return valor.quantize(escala, rounding=ROUND_HALF_UP)


def _con_separadores(entero: str) -> str:
    grupos: list[str] = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    return ".".join(grupos)


def numero(valor: Decimal, decimales: int = 2) -> str:
    """`1.234,56` — separador de miles con punto y decimal con coma.

    El redondeo es `ROUND_HALF_UP`: el formateo con `f"{…:.2f}"` usa el contexto
    decimal, que en Python redondea al par (2,665 € se leía «2,66 €»).
    """
    redondeado = abs(valor).quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
    entero, _, parte_decimal = f"{redondeado:.{decimales}f}".partition(".")
    texto = _con_separadores(entero)
    if parte_decimal:
        texto = f"{texto},{parte_decimal}"
    return f"{'-' if valor < CERO else ''}{texto}"


def euros(valor: Decimal, decimales: int = 2) -> str:
    """`1.234,56 €`."""
    return f"{numero(valor, decimales)} €"


def precio(valor: Decimal) -> str:
    """Precio unitario con los decimales que de verdad tenga.

    Un litro de leche a `1,15 €` no necesita cuatro decimales, pero el kWh a
    `0,1489 €` los pierde si se redondea a céntimos.
    """
    normalizado = valor.normalize()
    exponente = normalizado.as_tuple().exponent
    decimales = min(4, max(2, -int(exponente) if isinstance(exponente, int) else 2))
    return euros(valor, decimales)


def porcentaje(proporcion: Decimal, decimales: int = 2) -> str:
    """Recibe una proporción (`0,1739`) y devuelve `17,39 %`."""
    return f"{numero(proporcion * 100, decimales)} %"
