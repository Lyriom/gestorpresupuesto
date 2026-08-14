"""Utilidades compartidas por los tests."""

from __future__ import annotations

import os

# Los ajustes se leen al importar la aplicación, así que hay que fijarlos antes
# de que cualquier test importe app.*
os.environ.setdefault("SECRET_KEY", "clave-de-pruebas-suficientemente-larga-1234")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pymupdf  # noqa: E402
import pytest  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services import formato  # noqa: E402


@pytest.fixture(autouse=True)
def _moneda_de_la_instalacion():
    """Deja la moneda de los textos como está configurada, antes y después.

    `formato.fijar_moneda()` guarda la moneda en una variable de módulo, que es lo
    correcto para un proceso servidor pero se filtra entre pruebas: una que la
    cambie para comprobar el formato en euros hacía fallar a las siguientes de
    otro fichero, y solo al ejecutar la batería entera, nunca la prueba sola.
    """
    formato.fijar_moneda(settings.default_currency)
    yield
    formato.fijar_moneda(settings.default_currency)


def _pdf_desde_lineas(
    lineas: list[tuple[float, float, str]],
    *,
    rectangulos: list[tuple[float, float, float, float]] | None = None,
) -> bytes:
    """Crea un PDF de una página con el texto en las posiciones indicadas.

    Los rectángulos opcionales dibujan la rejilla de una tabla, que es lo que
    pdfplumber necesita para detectarla con la estrategia por líneas.
    """
    documento = pymupdf.open()
    pagina = documento.new_page(width=595, height=842)  # A4 en puntos
    for x, y, texto in lineas:
        pagina.insert_text((x, y), texto, fontname="helv", fontsize=9)
    for x0, y0, x1, y1 in rectangulos or []:
        pagina.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=0.6)
    datos = documento.tobytes()
    documento.close()
    return datos


@pytest.fixture
def factura_supermercado_texto() -> bytes:
    """Factura sin rejilla: obliga a usar la pasada de texto plano."""
    filas = [
        (50, 60, "SUPERMERCADOS EL AHORRO S.L."),
        (50, 74, "NIF: B12345674"),
        (50, 88, "Calle Mayor 14, 28013 Madrid"),
        (400, 60, "FACTURA Nº FS-2026/0184"),
        (400, 74, "Fecha de emision: 05/08/2026"),
        (50, 130, "Descripcion                      Cantidad   Precio    Importe"),
        (50, 150, "LECHE PASCUAL 1L BRIK               6        1,15       6,90"),
        (50, 166, "ACEITE OLIVA VIRGEN EXTRA 1L        2        9,45      18,90"),
        (50, 182, "PAN DE MOLDE INTEGRAL 460G          1        1,85       1,85"),
        (50, 198, "HUEVOS FRESCOS TALLA M 12 UDS        1        3,20       3,20"),
        (50, 240, "Base imponible                                          30,85"),
        (50, 256, "IVA 4%                                                   1,23"),
        (50, 272, "TOTAL A PAGAR                                           32,08"),
    ]
    return _pdf_desde_lineas(filas)


@pytest.fixture
def factura_luz_tabla() -> bytes:
    """Factura de suministro con rejilla dibujada: pasada de tablas."""
    filas = [
        (50, 60, "ENERGIA IBERICA S.A."),
        (50, 74, "C.I.F.: A78374725"),
        (400, 60, "Factura n. 2026-LUZ-00931"),
        (400, 74, "Fecha factura: 12 de julio de 2026"),
        (55, 145, "Concepto"),
        (250, 145, "Cantidad"),
        (330, 145, "Precio"),
        (430, 145, "Importe"),
        (55, 175, "Energia consumida P1"),
        (250, 175, "148,00 kWh"),
        (330, 175, "0,148900"),
        (430, 175, "22,04"),
        (55, 205, "Potencia contratada P1"),
        (250, 205, "30,00"),
        (330, 205, "0,103763"),
        (430, 205, "3,11"),
        (55, 235, "Alquiler de equipo de medida"),
        (250, 235, "30,00"),
        (330, 235, "0,026630"),
        (430, 235, "0,80"),
        (50, 300, "Base imponible: 25,95"),
        (50, 316, "Impuesto electricidad 5,113%: 1,33"),
        (50, 332, "IVA 21%: 5,73"),
        (50, 348, "TOTAL IMPORTE FACTURA: 33,01"),
    ]
    rejilla = [
        (50, 130, 500, 160),  # cabecera
        (50, 160, 500, 190),
        (50, 190, 500, 220),
        (50, 220, 500, 250),
        # separadores verticales
        (50, 130, 245, 250),
        (245, 130, 325, 250),
        (325, 130, 425, 250),
    ]
    return _pdf_desde_lineas(filas, rectangulos=rejilla)


@pytest.fixture
def pdf_sin_texto() -> bytes:
    """PDF con una página en blanco: no hay nada que extraer sin OCR."""
    documento = pymupdf.open()
    documento.new_page(width=595, height=842)
    datos = documento.tobytes()
    documento.close()
    return datos


@pytest.fixture
def factura_con_telefono() -> bytes:
    """Factura con el teléfono en el encabezado, como las escaneadas reales."""
    filas = [
        (50, 60, "SUPERMERCADOS EL AHORRO S.L."),
        (50, 74, "NIF: B12345674"),
        (50, 88, "Tel. 910 000 000"),
        (400, 60, "FACTURA Nº FS-2026/0200"),
        (400, 74, "Fecha de emision: 07/08/2026"),
        (50, 130, "Descripcion                      Cantidad   Precio    Importe"),
        (50, 150, "LECHE PASCUAL 1L BRIK               6        1,15       6,90"),
        (50, 166, "PAN DE MOLDE INTEGRAL 460G          1        1,85       1,85"),
        (50, 240, "Base imponible                                           8,75"),
        (50, 256, "TOTAL A PAGAR                                            9,10"),
    ]
    return _pdf_desde_lineas(filas)
