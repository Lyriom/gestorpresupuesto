"""Formateo de cifras en español para los textos que ve el usuario.

El frontend formatea con `Intl` casi todo, pero hay mensajes que el backend
redacta enteros —los avisos del presupuesto, las alertas de subida de precio, los
resúmenes por correo— y ahí no puede colarse el `Decimal` en bruto: "250.00 €"
con punto decimal se lee como un error de la aplicación.
"""

from __future__ import annotations

from decimal import Decimal

CERO = Decimal("0")


def _con_separadores(entero: str) -> str:
    grupos: list[str] = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    return ".".join(grupos)


def numero(valor: Decimal, decimales: int = 2) -> str:
    """`1.234,56` — separador de miles con punto y decimal con coma."""
    entero, _, parte_decimal = f"{abs(valor):.{decimales}f}".partition(".")
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
