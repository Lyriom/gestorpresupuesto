"""Pruebas de la extracción de facturas sobre PDF generados al vuelo."""

from decimal import Decimal

import pytest

from app.services.extraccion_pdf import PdfInvalido, extraer_factura, validar_pdf


def _buscar(factura, fragmento: str):
    for linea in factura.lineas:
        if fragmento.lower() in linea.descripcion.lower():
            return linea
    return None


class TestFacturaSupermercado:
    """Factura sin rejilla: se resuelve con la pasada de texto plano."""

    def test_lee_la_cabecera(self, factura_supermercado_texto):
        factura = extraer_factura(factura_supermercado_texto, ocr_habilitado=False)

        assert factura.emisor is not None
        assert "AHORRO" in factura.emisor.upper()
        assert factura.nif_emisor == "B12345674"
        assert factura.numero == "FS-2026/0184"
        assert factura.fecha is not None
        assert (factura.fecha.year, factura.fecha.month, factura.fecha.day) == (2026, 8, 5)
        assert factura.total == Decimal("32.08")
        assert factura.base_imponible == Decimal("30.85")
        assert factura.moneda == "EUR"

    def test_lee_las_lineas_de_producto(self, factura_supermercado_texto):
        factura = extraer_factura(factura_supermercado_texto, ocr_habilitado=False)

        assert factura.metodo in ("texto", "tabla")
        leche = _buscar(factura, "leche pascual")
        assert leche is not None
        assert leche.cantidad == Decimal("6")
        assert leche.precio_unitario == Decimal("1.15")
        assert leche.total == Decimal("6.90")

        aceite = _buscar(factura, "aceite oliva")
        assert aceite is not None
        assert aceite.total == Decimal("18.90")

    def test_descarta_las_filas_de_totales(self, factura_supermercado_texto):
        factura = extraer_factura(factura_supermercado_texto, ocr_habilitado=False)
        descripciones = [linea.descripcion.lower() for linea in factura.lineas]
        assert not any(d.startswith("total") for d in descripciones)
        assert not any(d.startswith("base imponible") for d in descripciones)
        assert not any(d.startswith("iva") for d in descripciones)

    def test_normaliza_el_tamanyo_del_producto(self, factura_supermercado_texto):
        factura = extraer_factura(factura_supermercado_texto, ocr_habilitado=False)
        leche = _buscar(factura, "leche pascual")
        assert leche.normalizada is not None
        assert leche.normalizada.tamanyo_valor == Decimal("1")
        assert leche.normalizada.tamanyo_unidad == "l"
        assert "pascual" in leche.normalizada.canonica

    def test_las_lineas_cuadran_con_la_base_imponible(self, factura_supermercado_texto):
        factura = extraer_factura(factura_supermercado_texto, ocr_habilitado=False)
        assert factura.suma_lineas == Decimal("30.85")
        # Si las líneas cuadran, la confianza tiene que ser alta.
        assert factura.confianza >= 0.7


class TestFacturaLuz:
    """Factura de suministro con rejilla: se resuelve por tablas."""

    def test_usa_la_pasada_de_tablas(self, factura_luz_tabla):
        factura = extraer_factura(factura_luz_tabla, ocr_habilitado=False)
        assert factura.metodo == "tabla"

    def test_lee_cabecera_con_fecha_en_texto(self, factura_luz_tabla):
        factura = extraer_factura(factura_luz_tabla, ocr_habilitado=False)
        assert factura.nif_emisor == "A78374725"
        assert factura.fecha is not None
        assert (factura.fecha.year, factura.fecha.month, factura.fecha.day) == (2026, 7, 12)
        assert factura.total == Decimal("33.01")

    def test_lee_el_consumo_con_su_unidad(self, factura_luz_tabla):
        factura = extraer_factura(factura_luz_tabla, ocr_habilitado=False)
        energia = _buscar(factura, "energia consumida")
        assert energia is not None
        assert energia.cantidad == Decimal("148.00")
        assert energia.unidad == "kWh"
        assert energia.total == Decimal("22.04")
        # El precio unitario de la luz tiene más de dos decimales.
        assert energia.precio_unitario == Decimal("0.1489")

    def test_recoge_todos_los_conceptos(self, factura_luz_tabla):
        factura = extraer_factura(factura_luz_tabla, ocr_habilitado=False)
        assert len(factura.lineas) >= 3
        assert _buscar(factura, "potencia contratada") is not None
        assert _buscar(factura, "alquiler") is not None


class TestCoherenciaDeLineas:
    def test_deduce_el_total_cuando_falta(self):
        from app.services.extraccion_pdf import LineaExtraida

        linea = LineaExtraida(
            descripcion="Café molido", cantidad=Decimal("3"), precio_unitario=Decimal("2.50")
        )
        linea.completar()
        assert linea.total == Decimal("7.50")

    def test_deduce_el_precio_unitario_cuando_falta(self):
        from app.services.extraccion_pdf import LineaExtraida

        linea = LineaExtraida(descripcion="Arroz", cantidad=Decimal("4"), total=Decimal("5.00"))
        linea.completar()
        assert linea.precio_unitario == Decimal("1.2500")

    def test_baja_la_confianza_si_no_cuadran_las_cuentas(self):
        from app.services.extraccion_pdf import LineaExtraida

        buena = LineaExtraida(
            descripcion="A",
            cantidad=Decimal("2"),
            precio_unitario=Decimal("3.00"),
            total=Decimal("6.00"),
        )
        buena.completar()
        mala = LineaExtraida(
            descripcion="B",
            cantidad=Decimal("2"),
            precio_unitario=Decimal("3.00"),
            total=Decimal("99.00"),
        )
        mala.completar()
        assert buena.confianza > mala.confianza
        assert mala.confianza <= 0.35

    def test_una_linea_solo_con_total_asume_una_unidad(self):
        from app.services.extraccion_pdf import LineaExtraida

        linea = LineaExtraida(descripcion="Cuota de mantenimiento", total=Decimal("12.00"))
        linea.completar()
        assert linea.cantidad == Decimal("1")
        assert linea.precio_unitario == Decimal("12.00")


class TestValidacion:
    def test_rechaza_un_fichero_que_no_es_pdf(self):
        with pytest.raises(PdfInvalido, match="no es un PDF"):
            validar_pdf(b"<html>esto no es un pdf</html>", 1024 * 1024, 10)

    def test_rechaza_un_fichero_vacio(self):
        with pytest.raises(PdfInvalido, match="vac"):
            validar_pdf(b"", 1024 * 1024, 10)

    def test_rechaza_un_fichero_demasiado_grande(self, factura_supermercado_texto):
        with pytest.raises(PdfInvalido, match="MB"):
            validar_pdf(factura_supermercado_texto, 10, 10)

    def test_rechaza_demasiadas_paginas(self, factura_supermercado_texto):
        with pytest.raises(PdfInvalido, match="páginas"):
            validar_pdf(factura_supermercado_texto, 1024 * 1024, 0)

    def test_acepta_una_factura_valida(self, factura_supermercado_texto):
        assert validar_pdf(factura_supermercado_texto, 1024 * 1024, 10) == 1


class TestPdfSinTexto:
    def test_avisa_cuando_no_hay_nada_que_leer(self, pdf_sin_texto):
        factura = extraer_factura(pdf_sin_texto, ocr_habilitado=False)
        assert factura.lineas == []
        assert factura.confianza < 0.3
        assert factura.avisos
