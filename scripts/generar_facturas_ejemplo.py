#!/usr/bin/env python3
"""Genera facturas PDF de ejemplo para probar la subida y el historial de precios.

Crea varias facturas del mismo supermercado en meses distintos, con precios que
suben, para poder ver funcionando la comparativa y las alertas sin esperar meses
a acumular facturas reales. También genera facturas de luz y una escaneada (sin
capa de texto) para probar el OCR.

Uso:
    python scripts/generar_facturas_ejemplo.py [directorio]

Por defecto escribe en `ejemplos/facturas/`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

try:
    import pymupdf
except ImportError:  # pragma: no cover - solo es una utilidad de desarrollo
    print("Falta PyMuPDF. Instálalo con: pip install pymupdf", file=sys.stderr)
    raise SystemExit(1) from None

A4 = (595, 842)
MARGEN = 50


@dataclass(frozen=True)
class Linea:
    descripcion: str
    cantidad: Decimal
    precio: Decimal

    @property
    def total(self) -> Decimal:
        return (self.cantidad * self.precio).quantize(Decimal("0.01"))


def _euros(valor: Decimal) -> str:
    """Formato español: separador de miles con punto y decimal con coma."""
    entero, _, decimales = f"{valor:.2f}".partition(".")
    negativo = entero.startswith("-")
    entero = entero.lstrip("-")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    return f"{'-' if negativo else ''}{'.'.join(grupos)},{decimales}"


class Pagina:
    """Envoltorio mínimo sobre PyMuPDF para ir escribiendo líneas de texto."""

    def __init__(self, documento: pymupdf.Document) -> None:
        self.pagina = documento.new_page(width=A4[0], height=A4[1])
        self.y = 60.0

    def texto(
        self,
        contenido: str,
        *,
        x: float = MARGEN,
        tamanyo: float = 9,
        negrita: bool = False,
        salto: float = 14,
    ) -> None:
        self.pagina.insert_text(
            (x, self.y),
            contenido,
            fontname="hebo" if negrita else "helv",
            fontsize=tamanyo,
        )
        self.y += salto

    def en_linea(self, contenido: str, x: float, tamanyo: float = 9, negrita: bool = False) -> None:
        """Escribe sin avanzar el cursor vertical, para montar columnas."""
        self.pagina.insert_text(
            (x, self.y),
            contenido,
            fontname="hebo" if negrita else "helv",
            fontsize=tamanyo,
        )

    def salto(self, alto: float = 14) -> None:
        self.y += alto

    def rejilla(self, filas: int, columnas: list[float], alto_fila: float = 22) -> None:
        """Dibuja la rejilla de una tabla para que pdfplumber la detecte."""
        y0 = self.y - 12
        y1 = y0 + alto_fila * filas
        for x in columnas:
            self.pagina.draw_rect(pymupdf.Rect(x, y0, x, y1), color=(0.4, 0.4, 0.4), width=0.5)
        for indice in range(filas + 1):
            y = y0 + alto_fila * indice
            self.pagina.draw_rect(
                pymupdf.Rect(columnas[0], y, columnas[-1], y),
                color=(0.4, 0.4, 0.4),
                width=0.5,
            )


def factura_supermercado(
    ruta: Path,
    *,
    numero: str,
    fecha: str,
    lineas: list[Linea],
    iva: Decimal = Decimal("0.04"),
) -> None:
    """Factura de supermercado con la tabla dibujada."""
    documento = pymupdf.open()
    p = Pagina(documento)

    p.texto("SUPERMERCADOS EL AHORRO, S.L.", tamanyo=13, negrita=True)
    p.texto("NIF: B12345674")
    p.texto("Calle Mayor 14, 28013 Madrid")
    p.texto("Tel. 910 000 000")
    p.salto(10)
    p.en_linea(f"FACTURA Nº {numero}", 360, tamanyo=11, negrita=True)
    p.salto(16)
    p.en_linea(f"Fecha de emisión: {fecha}", 360)
    p.salto(30)

    columnas = [MARGEN, 300, 360, 440, 520]
    p.rejilla(len(lineas) + 1, columnas)

    p.en_linea("Descripción", MARGEN + 5, negrita=True)
    p.en_linea("Cantidad", 305, negrita=True)
    p.en_linea("Precio", 365, negrita=True)
    p.en_linea("Importe", 445, negrita=True)
    p.salto(22)

    base = Decimal("0.00")
    for linea in lineas:
        base += linea.total
        p.en_linea(linea.descripcion, MARGEN + 5)
        p.en_linea(_euros(linea.cantidad), 305)
        p.en_linea(_euros(linea.precio), 365)
        p.en_linea(_euros(linea.total), 445)
        p.salto(22)

    cuota = (base * iva).quantize(Decimal("0.01"))
    p.salto(20)
    p.texto(f"Base imponible: {_euros(base)} €", x=340)
    p.texto(f"IVA {int(iva * 100)}%: {_euros(cuota)} €", x=340)
    p.texto(f"TOTAL A PAGAR: {_euros(base + cuota)} €", x=340, negrita=True, tamanyo=11)

    documento.save(ruta)
    documento.close()


def factura_luz(
    ruta: Path,
    *,
    numero: str,
    fecha: str,
    kwh: Decimal,
    precio_kwh: Decimal,
    dias: int = 30,
    precio_potencia: Decimal = Decimal("0.103763"),
) -> None:
    """Factura de suministro eléctrico, con precios de seis decimales."""
    documento = pymupdf.open()
    p = Pagina(documento)

    p.texto("ENERGÍA IBÉRICA, S.A.", tamanyo=13, negrita=True)
    p.texto("C.I.F.: A78374725")
    p.texto("Paseo de la Castellana 200, 28046 Madrid")
    p.salto(10)
    p.en_linea(f"Factura n. {numero}", 360, tamanyo=11, negrita=True)
    p.salto(16)
    p.en_linea(f"Fecha factura: {fecha}", 360)
    p.salto(16)
    p.en_linea(f"Periodo de facturación: {dias} días", 360)
    p.salto(30)

    energia = (kwh * precio_kwh).quantize(Decimal("0.01"))
    potencia = (Decimal(dias) * precio_potencia).quantize(Decimal("0.01"))
    alquiler = (Decimal(dias) * Decimal("0.026630")).quantize(Decimal("0.01"))

    conceptos = [
        ("Energía consumida P1", f"{_euros(kwh)} kWh", f"{precio_kwh:.6f}", energia),
        ("Potencia contratada P1", f"{dias},00", f"{precio_potencia:.6f}", potencia),
        ("Alquiler de equipo de medida", f"{dias},00", "0,026630", alquiler),
    ]

    columnas = [MARGEN, 280, 370, 450, 530]
    p.rejilla(len(conceptos) + 1, columnas)

    p.en_linea("Concepto", MARGEN + 5, negrita=True)
    p.en_linea("Cantidad", 285, negrita=True)
    p.en_linea("Precio", 375, negrita=True)
    p.en_linea("Importe", 455, negrita=True)
    p.salto(22)

    base = Decimal("0.00")
    for descripcion, cantidad, precio, importe in conceptos:
        base += importe
        p.en_linea(descripcion, MARGEN + 5)
        p.en_linea(cantidad, 285)
        p.en_linea(precio, 375)
        p.en_linea(_euros(importe), 455)
        p.salto(22)

    impuesto = (base * Decimal("0.05113")).quantize(Decimal("0.01"))
    iva = ((base + impuesto) * Decimal("0.21")).quantize(Decimal("0.01"))
    p.salto(20)
    p.texto(f"Base imponible: {_euros(base)} €", x=320)
    p.texto(f"Impuesto electricidad 5,113%: {_euros(impuesto)} €", x=320)
    p.texto(f"IVA 21%: {_euros(iva)} €", x=320)
    p.texto(
        f"TOTAL IMPORTE FACTURA: {_euros(base + impuesto + iva)} €",
        x=320,
        negrita=True,
        tamanyo=11,
    )

    documento.save(ruta)
    documento.close()


def factura_escaneada(ruta: Path, origen: Path) -> None:
    """Convierte una factura en imagen, para probar el camino del OCR.

    Se rasteriza a 200 ppp —suficiente para que Tesseract lea bien las cifras—
    y se inserta comprimida en JPEG. Sin comprimir, una sola página en mapa de
    bits pesa más de 10 MB y supera el límite de subida de la aplicación.
    """
    with pymupdf.open(origen) as documento:
        jpegs = [
            (pagina.get_pixmap(dpi=200).tobytes("jpeg", jpg_quality=80), pagina.rect)
            for pagina in documento
        ]

    salida = pymupdf.open()
    for datos, rectangulo in jpegs:
        pagina = salida.new_page(width=rectangulo.width, height=rectangulo.height)
        pagina.insert_image(pagina.rect, stream=datos)
    salida.save(ruta, deflate=True, garbage=4)
    salida.close()


def main() -> None:
    destino = Path(sys.argv[1] if len(sys.argv) > 1 else "ejemplos/facturas")
    destino.mkdir(parents=True, exist_ok=True)

    # Misma cesta en tres meses, con subidas desiguales: el aceite sube mucho,
    # la leche poco y el pan se mantiene. Así la comparativa tiene algo que decir.
    cestas = {
        "2026-06": [
            Linea("LECHE PASCUAL ENTERA 1L BRIK", Decimal("6"), Decimal("1.09")),
            Linea("ACEITE OLIVA VIRGEN EXTRA 1L", Decimal("2"), Decimal("8.95")),
            Linea("PAN DE MOLDE INTEGRAL 460G", Decimal("1"), Decimal("1.85")),
            Linea("HUEVOS FRESCOS TALLA M 12 UDS", Decimal("1"), Decimal("2.95")),
            Linea("CAFE MOLIDO NATURAL 250G", Decimal("2"), Decimal("3.40")),
        ],
        "2026-07": [
            Linea("LECHE PASCUAL ENTERA 1L BRIK", Decimal("6"), Decimal("1.12")),
            Linea("ACEITE OLIVA VIRGEN EXTRA 1L", Decimal("2"), Decimal("9.80")),
            Linea("PAN DE MOLDE INTEGRAL 460G", Decimal("2"), Decimal("1.85")),
            Linea("HUEVOS FRESCOS TALLA M 12 UDS", Decimal("1"), Decimal("3.10")),
            Linea("CAFE MOLIDO NATURAL 250G", Decimal("1"), Decimal("3.55")),
        ],
        "2026-08": [
            Linea("LECHE PASCUAL ENTERA 1L BRIK", Decimal("6"), Decimal("1.15")),
            Linea("ACEITE OLIVA VIRGEN EXTRA 1L", Decimal("2"), Decimal("11.45")),
            Linea("PAN DE MOLDE INTEGRAL 460G", Decimal("1"), Decimal("1.85")),
            Linea("HUEVOS FRESCOS TALLA M 12 UDS", Decimal("2"), Decimal("3.20")),
            Linea("CAFE MOLIDO NATURAL 250G", Decimal("2"), Decimal("3.95")),
        ],
    }

    generadas: list[Path] = []
    for indice, (periodo, lineas) in enumerate(cestas.items(), start=1):
        anyo, mes = periodo.split("-")
        ruta = destino / f"supermercado-{periodo}.pdf"
        factura_supermercado(
            ruta,
            numero=f"FS-{anyo}/{int(mes):04d}",
            fecha=f"0{indice + 4}/{mes}/{anyo}",
            lineas=lineas,
        )
        generadas.append(ruta)

    # La luz sube el precio del kWh mes a mes, con consumos distintos.
    for periodo, kwh, precio in (
        ("2026-06", Decimal("142.00"), Decimal("0.138900")),
        ("2026-07", Decimal("165.00"), Decimal("0.148900")),
        ("2026-08", Decimal("198.00"), Decimal("0.161200")),
    ):
        anyo, mes = periodo.split("-")
        ruta = destino / f"luz-{periodo}.pdf"
        factura_luz(
            ruta,
            numero=f"{anyo}-LUZ-{int(mes):05d}",
            fecha=f"12/{mes}/{anyo}",
            kwh=kwh,
            precio_kwh=precio,
        )
        generadas.append(ruta)

    # Una escaneada, a partir de la última del supermercado.
    escaneada = destino / "supermercado-escaneada.pdf"
    factura_escaneada(escaneada, destino / "supermercado-2026-08.pdf")
    generadas.append(escaneada)

    print(f"Generadas {len(generadas)} facturas en {destino}/:")
    for ruta in generadas:
        print(f"  {ruta.name}  ({ruta.stat().st_size // 1024} KB)")
    print(
        "\nLa factura escaneada no tiene capa de texto: sirve para comprobar el OCR.\n"
        "El aceite sube un 28 % entre junio y agosto, y el kWh un 16 %."
    )


if __name__ == "__main__":
    main()
