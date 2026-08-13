"""Interpretación de números y fechas tal y como aparecen en las facturas españolas.

Separar esto del extractor permite probarlo a fondo: es donde más fallos
silenciosos se cuelan (`1.234` son mil doscientos treinta y cuatro, no 1,234).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.services.formato import cuantizar

# Unidades habituales en facturas de suministros y de supermercado.
UNIDADES = {
    "ud": "ud",
    "uds": "ud",
    "unidad": "ud",
    "unidades": "ud",
    "u": "ud",
    "kg": "kg",
    "kgs": "kg",
    "kilo": "kg",
    "kilos": "kg",
    "kilogramo": "kg",
    "kilogramos": "kg",
    "g": "g",
    "gr": "g",
    "gramo": "g",
    "gramos": "g",
    "mg": "mg",
    "l": "l",
    "lt": "l",
    "lts": "l",
    "litro": "l",
    "litros": "l",
    "ml": "ml",
    "cl": "cl",
    "m": "m",
    "cm": "cm",
    "mm": "mm",
    "m2": "m2",
    "m²": "m2",
    "m3": "m3",
    "m³": "m3",
    "kwh": "kWh",
    "kw/h": "kWh",
    "kw": "kW",
    "mwh": "MWh",
    "gb": "GB",
    "mes": "mes",
    "meses": "mes",
    "dia": "día",
    "dias": "día",
    "día": "día",
    "días": "día",
    "hora": "hora",
    "horas": "hora",
    "h": "hora",
    "min": "min",
    "caja": "caja",
    "cajas": "caja",
    "pack": "pack",
    "docena": "docena",
    "bote": "bote",
    "botella": "botella",
    "paquete": "paquete",
    "bolsa": "bolsa",
    "lata": "lata",
    "brik": "brik",
}

MESES = {
    "enero": 1,
    "ene": 1,
    "febrero": 2,
    "feb": 2,
    "marzo": 3,
    "mar": 3,
    "abril": 4,
    "abr": 4,
    "mayo": 5,
    "may": 5,
    "junio": 6,
    "jun": 6,
    "julio": 7,
    "jul": 7,
    "agosto": 8,
    "ago": 8,
    "septiembre": 9,
    "sep": 9,
    "sept": 9,
    "setiembre": 9,
    "octubre": 10,
    "oct": 10,
    "noviembre": 11,
    "nov": 11,
    "diciembre": 12,
    "dic": 12,
}

# Un número con separadores de miles y/o decimales, con signo y símbolo opcionales.
PATRON_NUMERO = re.compile(
    r"""(?<![\w.,])            # que no venga pegado a letras ni a otro número
    (?P<signo>[-+]?)
    (?P<cuerpo>\d{1,3}(?:[.\s ]\d{3})+(?:,\d+)?   # 1.234.567,89
              |\d{1,3}(?:,\d{3})+(?:\.\d+)?            # 1,234,567.89
              |\d+(?:[.,]\d+)?)                        # 1234,89 | 1234.89 | 1234
    \s*(?P<moneda>€|EUR|USD|\$)?
    (?![\w])
    """,
    re.VERBOSE | re.IGNORECASE,
)

_LIMPIEZA = str.maketrans({" ": "", " ": "", "€": "", "−": "-"})


def parsear_decimal(texto: str | None) -> Decimal | None:
    """Convierte un número escrito en una factura a Decimal.

    Resuelve la ambigüedad de `.` y `,` mirando cuál aparece más a la derecha:
    ese es el separador decimal. Si solo hay un separador y deja exactamente
    tres cifras a la derecha, se interpreta como separador de miles
    (`1.234` -> 1234), salvo que el número sea claramente un precio unitario.
    """
    if texto is None:
        return None
    limpio = str(texto).strip().translate(_LIMPIEZA)
    limpio = re.sub(r"(EUR|USD|\$)", "", limpio, flags=re.IGNORECASE)
    if not limpio or not re.search(r"\d", limpio):
        return None

    negativo = limpio.startswith("-") or (limpio.startswith("(") and limpio.endswith(")"))
    limpio = limpio.strip("()").lstrip("+-")

    ultima_coma = limpio.rfind(",")
    ultimo_punto = limpio.rfind(".")

    if ultima_coma >= 0 and ultimo_punto >= 0:
        if ultima_coma > ultimo_punto:  # 1.234,56 -> formato español
            limpio = limpio.replace(".", "").replace(",", ".")
        else:  # 1,234.56 -> formato inglés
            limpio = limpio.replace(",", "")
    elif ultima_coma >= 0:
        # En una factura española la coma siempre es el separador decimal. No se
        # interpreta como separador de miles ni con tres cifras detrás, porque
        # los precios unitarios de luz y gas llevan 3 o más decimales
        # ("0,004" es cuatro milésimas, no cuatro euros).
        limpio = limpio.replace(",", ".")
    elif ultimo_punto >= 0:
        decimales = len(limpio) - ultimo_punto - 1
        entera = limpio.split(".")[0]
        # "1.234" son mil doscientos treinta y cuatro; "0.148" son decimales.
        if decimales == 3 and 1 <= len(entera) <= 3 and entera != "0":
            limpio = limpio.replace(".", "")

    try:
        valor = Decimal(limpio)
    except InvalidOperation:
        return None
    return -valor if negativo else valor


def parsear_importe(texto: str | None) -> Decimal | None:
    """Como `parsear_decimal` pero redondeando a los dos decimales del dinero.

    Con `ROUND_HALF_UP` y no con el redondeo bancario que Python trae por defecto:
    en un empate, 12,345 € son 12,35 € en cualquier factura española, y es también
    lo que hace PostgreSQL al guardar en `numeric(14,2)`. Con el modo por defecto
    el mismo importe se redondeaba distinto según quién lo cuantizase.
    """
    valor = parsear_decimal(texto)
    return None if valor is None else cuantizar(valor)


def numeros_de(texto: str) -> list[Decimal]:
    """Todos los números que aparecen en una línea, en orden de aparición."""
    encontrados: list[Decimal] = []
    for coincidencia in PATRON_NUMERO.finditer(texto):
        valor = parsear_decimal(coincidencia.group("signo") + coincidencia.group("cuerpo"))
        if valor is not None:
            encontrados.append(valor)
    return encontrados


def normalizar_unidad(texto: str | None) -> str | None:
    """Devuelve la unidad canónica (`kg`, `l`, `kWh`...) o None si no se reconoce."""
    if not texto:
        return None
    clave = texto.strip().lower().rstrip(".")
    return UNIDADES.get(clave)


_PATRONES_FECHA: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b"), "amd"),
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"), "dma"),
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2})\b"), "dma2"),
]

_PATRON_FECHA_TEXTO = re.compile(
    r"\b(\d{1,2})\s*(?:de\s+)?([a-záéíóú]{3,10})\.?\s*(?:de\s+|del\s+)?(\d{4})\b",
    re.IGNORECASE,
)


def parsear_fecha(texto: str) -> date | None:
    """Primera fecha plausible del texto, en formatos españoles e ISO."""
    for patron, orden in _PATRONES_FECHA:
        coincidencia = patron.search(texto)
        if not coincidencia:
            continue
        a, b, c = (int(g) for g in coincidencia.groups())
        try:
            if orden == "amd":
                return date(a, b, c)
            if orden == "dma":
                return date(c, b, a)
            # Año de dos cifras: 70-99 -> 1900, resto -> 2000.
            return date(c + (1900 if c >= 70 else 2000), b, a)
        except ValueError:
            continue

    coincidencia = _PATRON_FECHA_TEXTO.search(texto)
    if coincidencia:
        dia, nombre_mes, anyo = coincidencia.groups()
        mes = MESES.get(nombre_mes.lower().rstrip("."))
        if mes:
            try:
                return date(int(anyo), mes, int(dia))
            except ValueError:
                return None
    return None
