"""Extracción de datos de facturas en PDF con librerías libres.

Estrategia en tres pasadas, de la más fiable a la más costosa:

1. **Tablas**: `pdfplumber.extract_tables()` sobre el PDF con capa de texto. Es
   lo que mejor funciona con facturas generadas por ordenador (luz, gas, telco).
2. **Texto plano**: si no hay tablas reconocibles, se analizan las líneas de
   texto buscando el patrón "descripción ... cantidad precio total".
3. **OCR**: si el PDF no tiene capa de texto (factura escaneada o foto), se
   rasteriza con PyMuPDF y se pasa por Tesseract.

Nunca se da por bueno el resultado: cada línea y cada factura llevan una
confianza estimada, y la interfaz obliga al usuario a revisar antes de guardar.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Literal

import pdfplumber

from app.services.formato import CUATRO_DECIMALES, cuantizar
from app.services.normalizacion import DescripcionNormalizada, normalizar_descripcion
from app.services.numeros import (
    normalizar_unidad,
    numeros_de,
    parsear_decimal,
    parsear_fecha,
    parsear_importe,
)

logger = logging.getLogger(__name__)

MetodoExtraccion = Literal["tabla", "texto", "ocr", "ninguno"]

TOLERANCIA = Decimal("0.02")


class PdfInvalido(Exception):
    """El fichero no es un PDF utilizable (corrupto, cifrado o demasiado grande)."""


@dataclass(slots=True)
class LineaExtraida:
    """Una línea de producto o concepto de la factura."""

    descripcion: str
    cantidad: Decimal | None = None
    unidad: str | None = None
    precio_unitario: Decimal | None = None
    total: Decimal | None = None
    confianza: float = 0.5
    """De 0 a 1. Baja cuando hay que inferir valores o no cuadran las cuentas."""
    normalizada: DescripcionNormalizada | None = None

    def completar(self) -> None:
        """Deduce los huecos y ajusta la confianza según la coherencia interna.

        Con dos de los tres valores (cantidad, precio, total) se calcula el
        tercero. Si están los tres pero no cuadran, se respeta el total —que es
        el dato que suma en la factura— y se baja la confianza.
        """
        c, p, t = self.cantidad, self.precio_unitario, self.total

        if c is not None and p is not None and t is None:
            # HALF_UP: en un empate (2,1650 €) el importe sube, como en la factura.
            self.total = cuantizar(c * p)
            self.confianza = min(self.confianza, 0.8)
        elif c is not None and t is not None and p is None:
            if c != 0:
                self.precio_unitario = cuantizar(t / c, CUATRO_DECIMALES)
                self.confianza = min(self.confianza, 0.85)
        elif p is not None and t is not None and c is None:
            if p != 0:
                cantidad = (t / p).quantize(Decimal("0.001"))
                # Solo se acepta si sale un número redondo y razonable.
                if cantidad > 0 and abs(cantidad - round(cantidad)) < Decimal("0.02"):
                    self.cantidad = Decimal(round(cantidad))
                    self.confianza = min(self.confianza, 0.75)
        elif t is not None and c is None and p is None:
            self.cantidad = Decimal(1)
            self.precio_unitario = t
            self.confianza = min(self.confianza, 0.6)

        c, p, t = self.cantidad, self.precio_unitario, self.total
        if c is not None and p is not None and t is not None:
            esperado = cuantizar(c * p)
            desviacion = abs(esperado - t)
            if desviacion <= TOLERANCIA:
                self.confianza = min(1.0, self.confianza + 0.2)
            elif t != 0 and desviacion / abs(t) < Decimal("0.05"):
                # Diferencia pequeña: suele ser un descuento o un redondeo.
                self.confianza = min(self.confianza, 0.6)
            else:
                self.confianza = min(self.confianza, 0.35)

    def normalizar(self) -> None:
        """Calcula la forma canónica de la descripción.

        La unidad de la línea NO se rellena con el tamaño del producto: en
        "6 x LECHE PASCUAL 1L" la cantidad son 6 briks, no 6 litros. El tamaño
        se queda en `normalizada.tamanyo_*`, que es su sitio.
        """
        self.normalizada = normalizar_descripcion(self.descripcion)


@dataclass(slots=True)
class FacturaExtraida:
    """Todo lo que se ha podido leer de un PDF de factura."""

    emisor: str | None = None
    nif_emisor: str | None = None
    numero: str | None = None
    fecha: date | None = None
    base_imponible: Decimal | None = None
    impuestos: Decimal | None = None
    total: Decimal | None = None
    moneda: str = "EUR"
    lineas: list[LineaExtraida] = field(default_factory=list)
    metodo: MetodoExtraccion = "ninguno"
    paginas: int = 0
    confianza: float = 0.0
    avisos: list[str] = field(default_factory=list)
    texto_crudo: str = ""

    @property
    def suma_lineas(self) -> Decimal:
        return sum((linea.total or Decimal(0) for linea in self.lineas), Decimal(0))

    def evaluar(self) -> None:
        """Calcula la confianza global y deja avisos para la pantalla de revisión."""
        puntos = 0.0
        if self.emisor:
            puntos += 0.15
        if self.fecha:
            puntos += 0.2
        if self.total is not None:
            puntos += 0.2
        if self.numero:
            puntos += 0.05
        if self.lineas:
            media = sum(linea.confianza for linea in self.lineas) / len(self.lineas)
            puntos += 0.4 * media
        else:
            self.avisos.append("No se ha reconocido ninguna línea de producto.")

        # El mejor indicador de que la lectura es correcta: que las líneas sumen
        # el total de la factura.
        if self.total is not None and self.lineas:
            diferencia = abs(self.suma_lineas - self.total)
            base = self.base_imponible
            if diferencia <= TOLERANCIA:
                puntos = min(1.0, puntos + 0.15)
            elif base is not None and abs(self.suma_lineas - base) <= TOLERANCIA:
                # Las líneas están sin IVA y el total lo incluye: es correcto.
                puntos = min(1.0, puntos + 0.15)
            elif self.total != 0 and diferencia / abs(self.total) > Decimal("0.1"):
                self.avisos.append(
                    f"Las líneas suman {self.suma_lineas} € y el total de la factura es "
                    f"{self.total} €. Revisa si falta alguna línea."
                )
                puntos = max(0.0, puntos - 0.15)

        if self.metodo == "ocr":
            self.avisos.append(
                "La factura no tenía texto seleccionable y se ha leído con OCR: "
                "revisa las cifras con atención."
            )
            puntos *= 0.8

        if not self.fecha:
            self.avisos.append("No se ha encontrado la fecha de la factura.")
        if self.total is None:
            self.avisos.append("No se ha encontrado el importe total.")

        self.confianza = round(min(1.0, max(0.0, puntos)), 2)


# --- Reconocimiento de la cabecera ------------------------------------------

_PATRON_NIF = re.compile(
    r"\b(?:(?:N\.?I\.?F\.?|C\.?I\.?F\.?|V\.?A\.?T\.?)[\s:.]*)?"
    r"(ES)?([A-HJ-NP-SUVW]\d{7}[0-9A-J]|\d{8}[A-Z]|[XYZ]\d{7}[A-Z])\b",
    re.IGNORECASE,
)

_PATRON_NUMERO_FACTURA = re.compile(
    r"(?:factura|fra\.?|invoice)\s*(?:n[.ºo°]?|num(?:ero)?\.?|number|#)?\s*[:\-]?\s*"
    r"([A-Z0-9][A-Z0-9\-/._]{2,24})",
    re.IGNORECASE,
)

_ETIQUETAS_TOTAL = (
    "total a pagar",
    "importe total",
    "total factura",
    "total (iva incl",
    "total con iva",
    "total impuestos incluidos",
    "importe a pagar",
    "a pagar",
    "total",
)
_ETIQUETAS_BASE = (
    "base imponible",
    "subtotal",
    "importe bruto",
    "total sin iva",
    "base",
)
_ETIQUETAS_IMPUESTO = ("cuota iva", "total iva", "iva", "i.v.a", "impuestos", "igic")

_ETIQUETAS_FECHA = (
    "fecha de emision",
    "fecha emision",
    "fecha factura",
    "fecha de factura",
    "fecha",
    "emitida el",
)


def _sin_tildes_min(texto: str) -> str:
    from app.services.normalizacion import sin_acentos

    return sin_acentos(texto).lower()


def _posicion_etiqueta(texto_plano: str, etiqueta: str) -> int:
    """Posición de la etiqueta como palabra completa, o -1 si no aparece.

    Buscar por subcadena da falsos positivos caros: la etiqueta "iva" aparece
    dentro de "ACEITE OLIVA VIRGEN EXTRA", y se acababa tomando el importe de
    esa línea como la cuota de IVA de la factura.
    """
    patron = rf"(?<![a-z0-9]){re.escape(etiqueta)}(?![a-z])"
    coincidencia = re.search(patron, texto_plano)
    return coincidencia.start() if coincidencia else -1


def _buscar_importe_etiquetado(lineas: list[str], etiquetas: tuple[str, ...]) -> Decimal | None:
    """Busca el importe que acompaña a una de las etiquetas dadas.

    Se recorre en el orden de las etiquetas (de la más específica a la más
    genérica) para que "total a pagar" gane a un "total" de una línea anterior.
    """
    for etiqueta in etiquetas:
        for indice, linea in enumerate(lineas):
            plana = _sin_tildes_min(linea)
            posicion = _posicion_etiqueta(plana, etiqueta)
            if posicion < 0:
                continue
            # Primero se busca el importe en el resto de la misma línea.
            resto = linea[posicion + len(etiqueta) :]
            candidatos = numeros_de(resto)
            # Se descartan los porcentajes ("IVA 21% .... 12,34").
            if "%" in resto:
                candidatos = [
                    n for n in candidatos if not re.search(rf"{re.escape(str(n))}\s*%", resto)
                ]
            if candidatos:
                return cuantizar(candidatos[-1])
            # Si no hay, en la línea siguiente (tablas de totales a dos filas).
            if indice + 1 < len(lineas):
                siguientes = numeros_de(lineas[indice + 1])
                if siguientes:
                    return cuantizar(siguientes[-1])
    return None


def _detectar_emisor(lineas: list[str]) -> str | None:
    """Heurística: el emisor está arriba y suele llevar forma jurídica."""
    formas = ("s.l", "sl.", "s.a", "sa.", "s.l.u", "sociedad", "cooperativa", "coop")
    cabecera = lineas[:18]
    for linea in cabecera:
        plana = _sin_tildes_min(linea)
        if any(forma in plana for forma in formas) and len(linea.strip()) > 4:
            return re.sub(r"\s+", " ", linea).strip()[:120]
    # Si no hay forma jurídica, la primera línea con suficiente texto y sin
    # pinta de dirección ni de número.
    for linea in cabecera:
        limpia = re.sub(r"\s+", " ", linea).strip()
        plana = _sin_tildes_min(limpia)
        if (
            len(limpia) >= 4
            and not re.search(r"\d{4}", limpia)
            and not any(p in plana for p in ("factura", "calle", "c/", "avda", "tel", "www", "@"))
        ):
            return limpia[:120]
    return None


def _detectar_fecha(lineas: list[str]) -> date | None:
    for etiqueta in _ETIQUETAS_FECHA:
        for linea in lineas:
            plana = _sin_tildes_min(linea)
            posicion = plana.find(etiqueta)
            if posicion >= 0:
                fecha = parsear_fecha(linea[posicion:])
                if fecha:
                    return fecha
    # Sin etiqueta: la primera fecha del documento, que suele ser la de emisión.
    for linea in lineas[:40]:
        fecha = parsear_fecha(linea)
        if fecha:
            return fecha
    return None


def _leer_cabecera(factura: FacturaExtraida, texto: str) -> None:
    lineas = [linea for linea in texto.splitlines() if linea.strip()]
    if not lineas:
        return

    factura.emisor = _detectar_emisor(lineas)
    factura.fecha = _detectar_fecha(lineas)

    nif = _PATRON_NIF.search(texto)
    if nif:
        factura.nif_emisor = nif.group(2).upper()

    numero = _PATRON_NUMERO_FACTURA.search(texto)
    if numero:
        candidato = numero.group(1).strip(".-/")
        # Se descartan capturas que en realidad son palabras.
        if re.search(r"\d", candidato):
            factura.numero = candidato

    factura.total = _buscar_importe_etiquetado(lineas, _ETIQUETAS_TOTAL)
    factura.base_imponible = _buscar_importe_etiquetado(lineas, _ETIQUETAS_BASE)
    factura.impuestos = _buscar_importe_etiquetado(lineas, _ETIQUETAS_IMPUESTO)

    if factura.total is None and factura.base_imponible and factura.impuestos:
        factura.total = cuantizar(factura.base_imponible + factura.impuestos)

    hay_dolares = "$" in texto or "USD" in texto.upper()
    hay_euros = "€" in texto or "EUR" in texto.upper()
    if hay_dolares and not hay_euros:
        factura.moneda = "USD"


# --- Pasada 1: tablas -------------------------------------------------------

_CABECERAS = {
    "descripcion": (
        "descripcion",
        "concepto",
        "articulo",
        "producto",
        "detalle",
        "denominacion",
        "item",
    ),
    "cantidad": ("cantidad", "cant", "uds", "unidades", "n.uds", "qty", "consumo"),
    "unidad": ("unidad", "um", "medida"),
    "precio": (
        "precio",
        "p. unit",
        "p.unit",
        "precio unitario",
        "precio ud",
        "pvp",
        "importe unitario",
        "eur/ud",
        "precio/ud",
        "unitario",
    ),
    "total": ("total", "importe", "subtotal", "importe total", "total linea"),
}


def _mapear_cabecera(fila: list[str | None]) -> dict[str, int] | None:
    """Asocia cada campo con su índice de columna a partir de la fila de cabecera."""
    mapa: dict[str, int] = {}
    for indice, celda in enumerate(fila):
        if not celda:
            continue
        plana = _sin_tildes_min(str(celda)).strip()
        if not plana:
            continue
        for campo, alias in _CABECERAS.items():
            if campo in mapa:
                continue
            # "precio" antes que "total" porque "importe unitario" contiene ambos.
            if any(plana == a or plana.startswith(a) for a in alias):
                mapa[campo] = indice
                break
    # Sin descripción y sin importe no hay tabla de líneas que valga.
    if "descripcion" in mapa and ("total" in mapa or "precio" in mapa):
        return mapa
    return None


def _linea_desde_fila(fila: list[str | None], mapa: dict[str, int]) -> LineaExtraida | None:
    def celda(campo: str) -> str | None:
        indice = mapa.get(campo)
        if indice is None or indice >= len(fila):
            return None
        valor = fila[indice]
        return str(valor).strip() if valor else None

    descripcion = celda("descripcion")
    if not descripcion:
        return None
    descripcion = re.sub(r"\s+", " ", descripcion)
    plana = _sin_tildes_min(descripcion)
    # Filas de totales colgadas al final de la tabla.
    if plana in {"total", "subtotal", "base imponible", "iva", "suma"} or len(descripcion) < 2:
        return None

    cantidad_texto = celda("cantidad")
    cantidad = None
    unidad = normalizar_unidad(celda("unidad"))
    if cantidad_texto:
        numeros = numeros_de(cantidad_texto)
        if numeros:
            cantidad = numeros[0]
        if unidad is None:
            unidad = normalizar_unidad(re.sub(r"[\d.,\s]", "", cantidad_texto))

    # El precio unitario NO se redondea a céntimos: en luz, gas y telefonía
    # llega con cuatro o seis decimales y redondearlo falsearía el histórico.
    precio_crudo = parsear_decimal(celda("precio"))
    linea = LineaExtraida(
        descripcion=descripcion,
        cantidad=cantidad,
        unidad=unidad,
        precio_unitario=cuantizar(precio_crudo, CUATRO_DECIMALES) if precio_crudo else None,
        total=parsear_importe(celda("total")),
        confianza=0.75,  # las tablas son la fuente más fiable
    )
    if linea.total is None and linea.precio_unitario is None:
        return None
    return linea


def _extraer_de_tablas(pdf: pdfplumber.PDF) -> list[LineaExtraida]:
    lineas: list[LineaExtraida] = []
    for pagina in pdf.pages:
        try:
            tablas = pagina.extract_tables()
        except Exception:  # noqa: BLE001 - pdfplumber lanza errores variados
            logger.debug("No se han podido extraer tablas de una página", exc_info=True)
            continue
        for tabla in tablas:
            if len(tabla) < 2:
                continue
            mapa = None
            inicio = 0
            # La cabecera no siempre es la primera fila: se prueban las tres primeras.
            for indice, fila in enumerate(tabla[:3]):
                mapa = _mapear_cabecera(fila)
                if mapa:
                    inicio = indice + 1
                    break
            if not mapa:
                continue
            for fila in tabla[inicio:]:
                linea = _linea_desde_fila(fila, mapa)
                if linea:
                    lineas.append(linea)
    return lineas


# --- Pasada 2: texto plano --------------------------------------------------

# Descripción seguida de dos o tres números al final de la línea.
_PATRON_LINEA_TEXTO = re.compile(
    r"^(?P<descripcion>.*?[A-Za-zÁÉÍÓÚÑáéíóúñ]{3}.*?)\s+"
    r"(?P<numeros>(?:[-+]?\d[\d.,\s]*(?:€|EUR)?\s+){1,3}[-+]?\d[\d.,]*\s*(?:€|EUR)?)\s*$"
)

_LINEAS_A_IGNORAR = (
    "base imponible",
    "total",
    "subtotal",
    "iva",
    "i.v.a",
    "cuota",
    "forma de pago",
    "vencimiento",
    "domiciliacion",
    "iban",
    "swift",
    "pagina",
    "n. factura",
    "fecha",
    "cliente",
    "direccion",
    "telefono",
    "www",
    "codigo postal",
    "periodo de facturacion",
)


def _extraer_de_texto(texto: str) -> list[LineaExtraida]:
    lineas: list[LineaExtraida] = []
    for cruda in texto.splitlines():
        limpia = cruda.strip()
        if len(limpia) < 6:
            continue
        plana = _sin_tildes_min(limpia)
        if any(plana.startswith(ignorar) for ignorar in _LINEAS_A_IGNORAR):
            continue
        coincidencia = _PATRON_LINEA_TEXTO.match(limpia)
        if not coincidencia:
            continue

        descripcion = re.sub(r"\s+", " ", coincidencia.group("descripcion")).strip(" .:-")
        if len(descripcion) < 3 or not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3}", descripcion):
            continue

        numeros = numeros_de(coincidencia.group("numeros"))
        if not numeros:
            continue

        # Interpretación posicional: el último número es el importe de la línea.
        if len(numeros) >= 3:
            cantidad, precio, total = numeros[-3], numeros[-2], numeros[-1]
        elif len(numeros) == 2:
            cantidad, precio, total = None, numeros[-2], numeros[-1]
        else:
            cantidad, precio, total = None, None, numeros[-1]

        linea = LineaExtraida(
            descripcion=descripcion,
            cantidad=cantidad,
            precio_unitario=cuantizar(precio, CUATRO_DECIMALES) if precio is not None else None,
            total=cuantizar(total),
            confianza=0.5,  # menos fiable que una tabla con cabecera
        )
        lineas.append(linea)
    return lineas


# --- Pasada 3: OCR ----------------------------------------------------------


def _texto_por_ocr(datos: bytes, idiomas: str, max_paginas: int) -> str:
    """Rasteriza el PDF y lo pasa por Tesseract. Devuelve '' si no está disponible."""
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.warning("OCR no disponible: falta pymupdf, pytesseract o Pillow")
        return ""

    partes: list[str] = []
    try:
        with pymupdf.open(stream=datos, filetype="pdf") as documento:
            for numero, pagina in enumerate(documento):
                if numero >= max_paginas:
                    break
                # 300 ppp es el mínimo con el que Tesseract lee bien cifras pequeñas.
                mapa = pagina.get_pixmap(dpi=300)
                imagen = Image.open(BytesIO(mapa.tobytes("png")))
                partes.append(pytesseract.image_to_string(imagen, lang=idiomas))
    except pytesseract.TesseractNotFoundError:
        logger.warning("Tesseract no está instalado en el sistema: se omite el OCR")
        return ""
    except Exception:  # noqa: BLE001
        logger.exception("Fallo durante el OCR de la factura")
        return ""
    return "\n".join(partes)


# --- Punto de entrada -------------------------------------------------------


def validar_pdf(datos: bytes, max_bytes: int, max_paginas: int) -> int:
    """Comprueba que el fichero es un PDF manejable y devuelve su número de páginas.

    No se confía en el `content-type` ni en la extensión: se mira la firma del
    fichero y se cuentan las páginas para no procesar un PDF de miles de hojas
    que tumbaría el proceso.
    """
    if not datos:
        raise PdfInvalido("El fichero está vacío.")
    if len(datos) > max_bytes:
        raise PdfInvalido(f"El fichero pesa más de {max_bytes // (1024 * 1024)} MB.")
    if not datos.lstrip()[:5].startswith(b"%PDF-"):
        raise PdfInvalido("El fichero no es un PDF.")

    try:
        with pdfplumber.open(BytesIO(datos)) as pdf:
            paginas = len(pdf.pages)
    except Exception as exc:  # noqa: BLE001 - la librería lanza tipos variados
        raise PdfInvalido("El PDF está dañado o protegido con contraseña.") from exc

    if paginas == 0:
        raise PdfInvalido("El PDF no tiene páginas.")
    if paginas > max_paginas:
        raise PdfInvalido(f"El PDF tiene {paginas} páginas y el máximo son {max_paginas}.")
    return paginas


def extraer_factura(
    datos: bytes,
    *,
    max_bytes: int = 20 * 1024 * 1024,
    max_paginas: int = 40,
    ocr_habilitado: bool = True,
    idiomas_ocr: str = "spa+eng",
) -> FacturaExtraida:
    """Lee un PDF de factura y devuelve lo que ha podido interpretar.

    No lanza excepción si el reconocimiento sale pobre: devuelve la factura con
    la confianza baja y los avisos correspondientes, porque el usuario siempre
    pasa por la pantalla de revisión antes de guardar.
    """
    paginas = validar_pdf(datos, max_bytes, max_paginas)
    factura = FacturaExtraida(paginas=paginas)

    with pdfplumber.open(BytesIO(datos)) as pdf:
        texto = "\n".join(pagina.extract_text() or "" for pagina in pdf.pages)

        # Menos de 80 caracteres significa que no hay capa de texto real.
        if len(texto.strip()) < 80 and ocr_habilitado:
            logger.info("PDF sin capa de texto: se recurre al OCR")
            texto_ocr = _texto_por_ocr(datos, idiomas_ocr, max_paginas)
            if texto_ocr.strip():
                factura.metodo = "ocr"
                factura.texto_crudo = texto_ocr
                _leer_cabecera(factura, texto_ocr)
                factura.lineas = _extraer_de_texto(texto_ocr)
            else:
                factura.avisos.append(
                    "El PDF no tiene texto y no se ha podido leer con OCR. "
                    "Introduce los datos a mano."
                )
        else:
            factura.texto_crudo = texto
            _leer_cabecera(factura, texto)
            lineas = _extraer_de_tablas(pdf)
            if lineas:
                factura.metodo = "tabla"
            else:
                lineas = _extraer_de_texto(texto)
                factura.metodo = "texto" if lineas else "ninguno"
            factura.lineas = lineas

    # Descartar duplicados exactos que aparecen cuando una tabla se repite en
    # la cabecera de cada página.
    vistas: set[tuple[str, Decimal | None]] = set()
    unicas: list[LineaExtraida] = []
    for linea in factura.lineas:
        clave = (linea.descripcion.lower(), linea.total)
        if clave in vistas:
            continue
        vistas.add(clave)
        linea.completar()
        linea.normalizar()
        unicas.append(linea)
    factura.lineas = unicas

    factura.evaluar()
    logger.info(
        "Factura leída por %s: %d líneas, confianza %.2f",
        factura.metodo,
        len(factura.lineas),
        factura.confianza,
    )
    return factura
