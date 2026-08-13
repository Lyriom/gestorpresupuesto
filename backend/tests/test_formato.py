"""Pruebas del formateo de cifras de los mensajes que redacta el backend."""

from decimal import Decimal

import pytest

from app.services import formato


class TestNumero:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            (Decimal("0"), "0,00"),
            (Decimal("1.5"), "1,50"),
            (Decimal("30"), "30,00"),
            (Decimal("250"), "250,00"),
            (Decimal("1234.56"), "1.234,56"),
            (Decimal("1234567.89"), "1.234.567,89"),
            (Decimal("-42.35"), "-42,35"),
            (Decimal("-1234.56"), "-1.234,56"),
        ],
    )
    def test_separadores_espanyoles(self, valor, esperado):
        assert formato.numero(valor) == esperado

    def test_sin_decimales(self):
        assert formato.numero(Decimal("1234"), decimales=0) == "1.234"


class TestEuros:
    def test_lleva_el_simbolo_detras(self):
        assert formato.euros(Decimal("1234.5")) == "1.234,50 €"

    def test_nunca_deja_el_punto_decimal_del_decimal(self):
        # El fallo que motivó este módulo: los avisos mostraban "250.00 €".
        assert "." not in formato.euros(Decimal("250")).split(",")[1]
        assert formato.euros(Decimal("250")) == "250,00 €"


class TestPrecio:
    def test_dos_decimales_cuando_bastan(self):
        assert formato.precio(Decimal("1.15")) == "1,15 €"

    def test_conserva_los_decimales_del_kwh(self):
        assert formato.precio(Decimal("0.1489")) == "0,1489 €"

    def test_recorta_a_cuatro_decimales(self):
        assert formato.precio(Decimal("0.148900")) == "0,1489 €"

    def test_un_entero_sale_con_dos_decimales(self):
        assert formato.precio(Decimal("9")) == "9,00 €"


class TestPorcentaje:
    def test_convierte_la_proporcion(self):
        assert formato.porcentaje(Decimal("0.1739")) == "17,39 %"

    def test_negativo(self):
        assert formato.porcentaje(Decimal("-0.25")) == "-25,00 %"

    def test_cero(self):
        assert formato.porcentaje(Decimal("0")) == "0,00 %"


class TestEnLosMensajesReales:
    def test_el_aviso_de_sobrepaso_va_en_espanyol(self):
        from app.services.presupuesto import EntradaCategoria, calcular_barra

        barra = calcular_barra(
            "2026-08",
            "3000",
            [
                EntradaCategoria(
                    categoria_id="ocio",
                    nombre="Ocio",
                    asignado=Decimal("1200"),
                    gastado=Decimal("1450.50"),
                )
            ],
        )
        aviso = next(a for a in barra.avisos if "pasado" in a)
        assert "250,50 €" in aviso
        assert "250.50" not in aviso

    def test_la_alerta_de_precio_va_en_espanyol(self):
        from datetime import date

        from app.services.precios import PuntoPrecio, analizar_historial

        analisis = analizar_historial(
            [
                PuntoPrecio(date(2026, 7, 1), Decimal("0.1489")),
                PuntoPrecio(date(2026, 8, 1), Decimal("0.1612")),
            ]
        )
        assert analisis.mensaje_alerta is not None
        # El precio del kWh conserva sus cuatro decimales y la coma decimal.
        assert "0,1489 €" in analisis.mensaje_alerta
        assert "0,1612 €" in analisis.mensaje_alerta
        assert "8,26 %" in analisis.mensaje_alerta
