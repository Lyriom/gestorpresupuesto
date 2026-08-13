"""Normalización de descripciones de producto para poder comparar precios.

El mismo producto aparece escrito de forma distinta en cada factura
("LECHE PASCUAL 1L BRIK", "Leche Pascual brik 1 l", "LECHE PASCUAL1LT"). Para
construir el historial de precios hay que reconocer que son el mismo, así que
se genera una forma canónica y se comparan con distancia difusa.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from rapidfuzz import fuzz

from app.services.numeros import normalizar_unidad, parsear_decimal

# Ruido habitual en las líneas de factura que no identifica al producto.
_PALABRAS_RUIDO = {
    "articulo",
    "art",
    "ref",
    "referencia",
    "cod",
    "codigo",
    "descripcion",
    "producto",
    "iva",
    "incl",
    "incluido",
    "dto",
    "descuento",
    "oferta",
    "promo",
    "promocion",
    "unidad",
    "unidades",
    "ud",
    "uds",
    "pvp",
    "total",
    "importe",
    "precio",
    "eur",
    "euros",
    "linea",
    "cantidad",
}

# Formatos de tamaño pegados al nombre: "1L", "500ML", "2X1KG", "6 UDS".
_PATRON_TAMANYO = re.compile(
    r"""(?P<multiplo>\d+\s*[x×]\s*)?
        (?P<valor>\d+(?:[.,]\d+)?)\s*
        (?P<unidad>kg|kgs|g|gr|grs|mg|l|lt|lts|ml|cl|cc|m|cm|mm|m2|m3|kwh|kw|ud|uds|u|pack|packs)\b
    """,
    re.VERBOSE | re.IGNORECASE,
)

_PATRON_CODIGO = re.compile(r"\b(?:\d{6,14}|[a-z]{1,3}[-/]?\d{4,10})\b", re.IGNORECASE)


def sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


@dataclass(slots=True)
class DescripcionNormalizada:
    """Resultado de normalizar la descripción cruda de una línea de factura."""

    canonica: str
    """Texto normalizado que se usa para comparar y agrupar."""
    marca_probable: str | None
    tamanyo_valor: Decimal | None
    tamanyo_unidad: str | None
    codigo: str | None
    """Código de barras o referencia interna, si aparecía en la descripción."""

    @property
    def tamanyo_texto(self) -> str | None:
        if self.tamanyo_valor is None or not self.tamanyo_unidad:
            return None
        # `normalize()` deja 250 como "2.5E+2", y ese texto acaba dentro de la
        # clave de agrupación del producto: se fuerza notación posicional.
        valor = format(self.tamanyo_valor.normalize(), "f")
        return f"{valor} {self.tamanyo_unidad}"


def normalizar_descripcion(cruda: str) -> DescripcionNormalizada:
    """Extrae la forma canónica, el tamaño y el código de una descripción."""
    texto = sin_acentos(cruda).lower()

    codigo_encontrado = _PATRON_CODIGO.search(texto)
    codigo = codigo_encontrado.group(0) if codigo_encontrado else None

    # El tamaño se guarda aparte: "leche 1l" y "leche 500ml" son productos
    # distintos y no deben compartir historial de precio unitario.
    tamanyo_valor: Decimal | None = None
    tamanyo_unidad: str | None = None
    coincidencia_tamanyo = _PATRON_TAMANYO.search(texto)
    if coincidencia_tamanyo:
        valor = parsear_decimal(coincidencia_tamanyo.group("valor"))
        unidad = normalizar_unidad(coincidencia_tamanyo.group("unidad"))
        if valor is not None and unidad:
            multiplo = coincidencia_tamanyo.group("multiplo")
            if multiplo:
                factor = parsear_decimal(re.sub(r"[x×\s]", "", multiplo))
                if factor:
                    valor *= factor
            tamanyo_valor, tamanyo_unidad = valor, unidad

    # Se quitan códigos, precios sueltos, puntuación y palabras de ruido.
    texto = _PATRON_CODIGO.sub(" ", texto)
    texto = _PATRON_TAMANYO.sub(" ", texto)
    texto = re.sub(r"[^\w\s]", " ", texto)
    texto = re.sub(r"\b\d+(?:[.,]\d+)?\b", " ", texto)

    palabras = [p for p in texto.split() if len(p) > 1 and p not in _PALABRAS_RUIDO]
    canonica = " ".join(palabras).strip()

    # Heurística de marca: la primera palabra larga que no sea un genérico de
    # producto suele ser la marca en las facturas de supermercado.
    marca = None
    if len(palabras) >= 2:
        candidata = palabras[1] if len(palabras[0]) <= 4 else palabras[0]
        if len(candidata) >= 4:
            marca = candidata

    return DescripcionNormalizada(
        canonica=canonica or sin_acentos(cruda).lower().strip(),
        marca_probable=marca,
        tamanyo_valor=tamanyo_valor,
        tamanyo_unidad=tamanyo_unidad,
        codigo=codigo,
    )


def clave_agrupacion(normalizada: DescripcionNormalizada) -> str:
    """Clave estable para el catálogo de productos.

    Incluye el tamaño porque el precio unitario de un litro y de medio litro no
    son comparables. Las palabras se ordenan para que el orden en el que las
    escriba cada proveedor no genere dos productos distintos.
    """
    if normalizada.codigo:
        return f"cod:{normalizada.codigo}"
    palabras = sorted(set(normalizada.canonica.split()))
    base = " ".join(palabras)
    if normalizada.tamanyo_texto:
        return f"{base}|{normalizada.tamanyo_texto}"
    return base


# Umbral a partir del cual dos descripciones se consideran el mismo producto.
# Calibrado a mano: por debajo de 88 empiezan a colarse productos de la misma
# marca pero distinto sabor o formato.
UMBRAL_COINCIDENCIA = 88.0


def similitud(a: str, b: str) -> float:
    """Parecido entre dos descripciones canónicas, de 0 a 100.

    Se combina `token_set_ratio` (tolera palabras extra y orden distinto) con
    `partial_ratio` (tolera abreviaturas), quedándose con el mayor.
    """
    if not a or not b:
        return 0.0
    return max(fuzz.token_set_ratio(a, b), fuzz.partial_ratio(a, b))


def es_mismo_producto(
    a: DescripcionNormalizada,
    b: DescripcionNormalizada,
    umbral: float = UMBRAL_COINCIDENCIA,
) -> bool:
    """Decide si dos descripciones normalizadas son el mismo producto."""
    # Un código de barras coincidente es prueba definitiva.
    if a.codigo and b.codigo:
        return a.codigo == b.codigo
    # Tamaños distintos descartan la coincidencia aunque el nombre sea idéntico.
    ambos_con_tamanyo = bool(a.tamanyo_unidad and b.tamanyo_unidad)
    tamanyos_distintos = a.tamanyo_unidad != b.tamanyo_unidad or a.tamanyo_valor != b.tamanyo_valor
    if ambos_con_tamanyo and tamanyos_distintos:
        return False
    return similitud(a.canonica, b.canonica) >= umbral


def mejor_coincidencia(
    objetivo: str,
    candidatos: dict[str, str],
    umbral: float = UMBRAL_COINCIDENCIA,
) -> tuple[str, float] | None:
    """Busca el candidato más parecido a `objetivo`.

    `candidatos` es un diccionario identificador -> descripción canónica.
    Devuelve el identificador y la puntuación, o None si nada supera el umbral.
    """
    mejor_id: str | None = None
    mejor_puntuacion = 0.0
    for identificador, descripcion in candidatos.items():
        puntuacion = similitud(objetivo, descripcion)
        if puntuacion > mejor_puntuacion:
            mejor_id, mejor_puntuacion = identificador, puntuacion
    if mejor_id is not None and mejor_puntuacion >= umbral:
        return mejor_id, mejor_puntuacion
    return None
