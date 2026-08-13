"""Pruebas del parseo de números y fechas de las facturas."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.numeros import (
    normalizar_unidad,
    numeros_de,
    parsear_decimal,
    parsear_fecha,
    parsear_importe,
)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("1234,56", Decimal("1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("1.234.567,89", Decimal("1234567.89")),
        ("1,234,567.89", Decimal("1234567.89")),
        ("32,08 €", Decimal("32.08")),
        ("€ 32,08", Decimal("32.08")),
        ("-15,50", Decimal("-15.50")),
        ("(15,50)", Decimal("-15.50")),
        ("0,148900", Decimal("0.148900")),
        ("0,004", Decimal("0.004")),  # cuatro milésimas, no cuatro euros
        ("1.234", Decimal("1234")),  # separador de miles, no decimal
        ("0.148", Decimal("0.148")),  # con parte entera 0 el punto es decimal
        ("12", Decimal("12")),
        ("1 234,56", Decimal("1234.56")),
        ("", None),
        ("sin numeros", None),
        (None, None),
    ],
)
def test_parsear_decimal(entrada, esperado):
    assert parsear_decimal(entrada) == esperado


def test_parsear_importe_redondea_a_centimos():
    assert parsear_importe("12,3456") == Decimal("12.35")
    # Un precio unitario en milésimas se pierde al redondearlo: por eso las
    # líneas de factura guardan el precio con parsear_decimal, no con este.
    assert parsear_importe("0,004") == Decimal("0.00")


def test_numeros_de_respeta_el_orden():
    linea = "LECHE PASCUAL 1L BRIK   6   1,15   6,90"
    # El "1" de "1L" no cuenta como cifra suelta: va pegado a una letra y forma
    # parte del tamaño del producto, no de las columnas de importes.
    assert numeros_de(linea) == [Decimal("6"), Decimal("1.15"), Decimal("6.90")]


def test_numeros_de_ignora_texto_pegado():
    assert numeros_de("REF-A1234 producto 9,99") == [Decimal("9.99")]


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("05/08/2026", date(2026, 8, 5)),
        ("5-8-2026", date(2026, 8, 5)),
        ("2026-08-05", date(2026, 8, 5)),
        ("12 de julio de 2026", date(2026, 7, 12)),
        ("3 ago 2026", date(2026, 8, 3)),
        ("31/12/99", date(1999, 12, 31)),
        ("01/01/26", date(2026, 1, 1)),
        ("sin fecha", None),
        ("32/13/2026", None),
    ],
)
def test_parsear_fecha(entrada, esperado):
    assert parsear_fecha(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("kg", "kg"),
        ("Kilos", "kg"),
        ("L", "l"),
        ("litros", "l"),
        ("kWh", "kWh"),
        ("KW/H", "kWh"),
        ("uds", "ud"),
        ("m³", "m3"),
        ("pepinos", None),
        (None, None),
    ],
)
def test_normalizar_unidad(entrada, esperado):
    assert normalizar_unidad(entrada) == esperado
