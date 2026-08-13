"""Plantillas de extracción por proveedor (F-40).

El problema que resuelve: si el PDF de una compañía se interpreta mal **siempre
igual**, el usuario corrige lo mismo cada mes. Una plantilla guarda cómo leer las
facturas de ese emisor para no repetir la corrección.

La plantilla es **datos, no código**: expresiones regulares con nombre para los
campos de la cabecera, los índices o los encabezados de las columnas de la tabla
de líneas, un patrón de fila para las facturas sin rejilla y una lista de filas a
ignorar. Todo se guarda en las cuatro columnas `jsonb` que ya tiene
`extraction_templates` (`page_settings`, `header_patterns`, `line_patterns` y
`post_rules`) y se publica en la API como dos diccionarios planos
(`field_patterns` y `table_columns`), así que el usuario puede leerla y editarla
sin que nadie despliegue nada.

Cómo encaja con `extraccion_pdf.py`, que **no se toca**:

- `aplicar()` parte de las tres pasadas de siempre y **encima** aplica la
  plantilla. Una plantilla solo necesita reglas para lo que el extractor falla,
  que es justo lo que el usuario corrige a mano; el resto lo sigue resolviendo el
  extractor genérico.
- `extraer_con_plantillas()` es el envoltorio: si hay plantilla para el emisor se
  prueba primero y, si no da un resultado utilizable, se cae a `extraer_factura()`
  sin que la factura se quede sin leer.

Y la parte que le da el valor de verdad: `deducir()` compara lo que el extractor
leyó con lo que el usuario dejó tras revisar y **propone las reglas que habrían
acertado**. Ninguna regla propuesta se devuelve sin verificarla antes contra el
texto de la factura: una plantilla que no acierta es peor que no tener plantilla.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

import pdfplumber

# Se importan tres ayudantes privados de `extraccion_pdf` a propósito: son las
# tres pasadas que ya funcionan y la lectura de cabecera con todas sus
# heurísticas afinadas. Copiarlas aquí sería garantizar que las dos copias se
# separen, y reescribir el módulo estaba descartado.
from app.services.extraccion_pdf import (
    FacturaExtraida,
    LineaExtraida,
    _extraer_de_tablas,
    _extraer_de_texto,
    _leer_cabecera,
    _linea_desde_fila,
    _texto_por_ocr,
    validar_pdf,
)
from app.services.formato import CUATRO_DECIMALES, cuantizar
from app.services.normalizacion import sin_acentos
from app.services.numeros import parsear_fecha, parsear_importe

logger = logging.getLogger(__name__)

#: Campos de cabecera para los que se admite una regla. Son exactamente los de
#: `FacturaExtraida`: la plantilla no puede rellenar algo que no exista.
CAMPOS_TEXTO = ("issuer", "issuer_tax_id", "number", "currency")
CAMPOS_FECHA = ("date",)
CAMPOS_IMPORTE = ("taxable_base", "tax_amount", "total")
CAMPOS_CABECERA = CAMPOS_TEXTO + CAMPOS_FECHA + CAMPOS_IMPORTE

#: Campo de la plantilla → atributo de `FacturaExtraida`.
_ATRIBUTO = {
    "issuer": "emisor",
    "issuer_tax_id": "nif_emisor",
    "number": "numero",
    "currency": "moneda",
    "date": "fecha",
    "taxable_base": "base_imponible",
    "tax_amount": "impuestos",
    "total": "total",
}

#: Columnas de la tabla de líneas. Las claves públicas van en inglés; el mapa que
#: consume `_linea_desde_fila()` las quiere en español.
COLUMNAS = ("description", "quantity", "unit", "unit_price", "total")
_COLUMNA_INTERNA = {
    "description": "descripcion",
    "quantity": "cantidad",
    "unit": "unidad",
    "unit_price": "precio",
    "total": "total",
}

#: Grupos con nombre que puede declarar `line_row`, y a qué columna equivalen.
_GRUPOS_LINEA = COLUMNAS

#: Claves reservadas de `field_patterns` que no son campos de cabecera.
CLAVE_FILA = "line_row"
PREFIJO_IGNORAR = "ignore"
PREFIJO_COLUMNA = "column:"

#: Cuánto texto se lee para decidir qué plantilla toca. El emisor está arriba.
PAGINAS_DE_PORTADA = 1

#: Por debajo de esto se considera que el PDF no tiene capa de texto (el mismo
#: criterio que `extraer_factura`).
MINIMO_CAPA_DE_TEXTO = 80


class PlantillaInvalida(ValueError):
    """La plantilla no se puede aplicar: expresión regular o campo imposible."""


# --------------------------------------------------------------------------- #
# La plantilla
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class PlantillaExtraccion:
    """Cómo leer las facturas de un emisor. Datos puros, inspeccionables."""

    nombre: str = ""
    identificador: str | None = None
    """El `extraction_templates.id` de quien la cargó, para poder anotar el acierto."""
    patron_emisor: str | None = None
    """Con qué se reconoce que esta factura es de ese emisor."""
    nif_emisor: str | None = None
    prioridad: int = 100
    campos: dict[str, str] = field(default_factory=dict)
    """Campo de cabecera → expresión regular. Gana al extractor genérico."""
    columnas: dict[str, int] = field(default_factory=dict)
    """Columna → índice de columna en la tabla del PDF."""
    encabezados: dict[str, str] = field(default_factory=dict)
    """Columna → expresión regular del texto de su encabezado (alternativa al índice)."""
    patron_linea: str | None = None
    """Fila de la tabla, con grupos con nombre, para las facturas sin rejilla."""
    ignorar: list[str] = field(default_factory=list)
    """Filas que no son líneas de producto: cuotas, portes, subtotales."""
    forzar_ocr: bool = False
    descartar_sin_importe: bool = True
    unidad_por_defecto: str | None = None

    @property
    def toca_las_lineas(self) -> bool:
        """¿La plantilla dice algo sobre cómo leer las líneas?"""
        return bool(self.columnas or self.encabezados or self.patron_linea)


#: Repeticiones que multiplican: `*`, `+` y `{n,m}`. La interrogación se queda
#: fuera porque `(...)?` como mucho prueba dos caminos, no una explosión.
#: Es un conjunto y no una cadena a propósito: con `"" in "*+{"` Python responde
#: que sí, y el grupo que cierra al final del patrón se tomaría por repetido.
_REPETICIONES = frozenset("*+{")


def _repeticion_anidada(patron: str) -> bool:
    r"""¿Hay un grupo que repite y cuyo contenido ya repetía?

    Es la forma clásica que se atasca: `(\d+)+`, `(a*)*`, `([a-z]+){2,}`. Contra un
    texto que *casi* encaja, el motor prueba todas las maneras de repartir los
    caracteres entre las dos repeticiones, y son exponenciales en la longitud del
    texto. Con cuarenta caracteres el `re` de Python ya no termina en toda una
    tarde, y no hay manera de interrumpirlo: no acepta un límite de tiempo y el
    hilo que lo ejecuta se queda ahí para siempre.

    Se recorre el patrón a mano en vez de con otra expresión regular porque hay
    que saber en cada momento si se está dentro de un `[...]` —donde un `+` es un
    signo más y no una repetición— y si el carácter viene escapado.
    """
    aperturas: list[int] = []
    # Por cada grupo abierto, si su contenido lleva ya una repetición.
    repite_dentro: list[bool] = []
    en_clase = False
    escapado = False
    i = 0
    while i < len(patron):
        caracter = patron[i]
        if escapado:
            escapado = False
        elif caracter == "\\":
            escapado = True
        elif en_clase:
            if caracter == "]":
                en_clase = False
        elif caracter == "[":
            en_clase = True
        elif caracter == "(":
            aperturas.append(i)
            repite_dentro.append(False)
        elif caracter == ")":
            if aperturas:
                aperturas.pop()
                anidada = repite_dentro.pop()
                siguiente = patron[i + 1] if i + 1 < len(patron) else ""
                if anidada and siguiente in _REPETICIONES:
                    return True
                # Un grupo que repite cuenta como repetición para el de fuera:
                # `((a+)b)+` es igual de malo aunque el `+` esté un nivel más
                # adentro.
                if repite_dentro and (anidada or siguiente in _REPETICIONES):
                    repite_dentro[-1] = True
        elif caracter in _REPETICIONES and repite_dentro:
            repite_dentro[-1] = True
        i += 1
    return False


def compilar(patron: str, *, donde: str) -> re.Pattern[str]:
    """Compila una expresión de la plantilla dando un error legible si está mal."""
    if _repeticion_anidada(patron):
        raise PlantillaInvalida(
            f"La expresión regular de «{donde}» tiene una repetición dentro de otra "
            "(por ejemplo «(\\d+)+»). Con una factura que casi encajase se quedaría "
            "calculando sin fin y esa factura no llegaría a leerse nunca. "
            "Sobra uno de los dos: «(\\d+)» hace lo mismo."
        )
    try:
        return re.compile(patron, re.IGNORECASE | re.MULTILINE)
    except re.error as exc:
        raise PlantillaInvalida(
            f"La expresión regular de «{donde}» no es válida: {exc.msg}."
        ) from exc


def validar(plantilla: PlantillaExtraccion) -> list[str]:
    """Todo lo que impide usar la plantilla, en la frase que verá el usuario."""
    errores: list[str] = []
    for nombre, patron in plantilla.campos.items():
        if nombre not in CAMPOS_CABECERA:
            errores.append(
                f"«{nombre}» no es un campo de cabecera. "
                f"Los admitidos son: {', '.join(CAMPOS_CABECERA)}."
            )
            continue
        try:
            compilar(patron, donde=nombre)
        except PlantillaInvalida as exc:
            errores.append(str(exc))
    for nombre, patron in plantilla.encabezados.items():
        if nombre not in COLUMNAS:
            errores.append(f"«{nombre}» no es una columna de la tabla de líneas.")
            continue
        try:
            compilar(patron, donde=f"{PREFIJO_COLUMNA}{nombre}")
        except PlantillaInvalida as exc:
            errores.append(str(exc))
    for nombre, indice in plantilla.columnas.items():
        if nombre not in COLUMNAS:
            errores.append(f"«{nombre}» no es una columna de la tabla de líneas.")
        elif indice < 0:
            errores.append(f"El índice de la columna «{nombre}» no puede ser negativo.")
    if plantilla.columnas and "description" not in plantilla.columnas:
        errores.append("El mapa de columnas necesita al menos «description».")
    for indice, patron in enumerate(plantilla.ignorar):
        try:
            compilar(patron, donde=f"{PREFIJO_IGNORAR}[{indice}]")
        except PlantillaInvalida as exc:
            errores.append(str(exc))
    if plantilla.patron_linea:
        try:
            compilado = compilar(plantilla.patron_linea, donde=CLAVE_FILA)
        except PlantillaInvalida as exc:
            errores.append(str(exc))
        else:
            if "description" not in compilado.groupindex:
                errores.append(
                    f"«{CLAVE_FILA}» necesita un grupo con nombre «description»: "
                    r"por ejemplo (?P<description>.+?)."
                )
    if plantilla.patron_emisor:
        try:
            compilar(plantilla.patron_emisor, donde="issuer_pattern")
        except PlantillaInvalida as exc:
            errores.append(str(exc))
    return errores


# --------------------------------------------------------------------------- #
# Persistencia: las cuatro columnas `jsonb` que ya existen
# --------------------------------------------------------------------------- #


def a_jsonb(plantilla: PlantillaExtraccion) -> dict[str, dict[str, Any]]:
    """Reparte la plantilla en las cuatro columnas `jsonb` de la tabla."""
    return {
        "page_settings": {"force_ocr": plantilla.forzar_ocr},
        "header_patterns": dict(plantilla.campos),
        "line_patterns": {
            "columns": dict(plantilla.columnas),
            "headers": dict(plantilla.encabezados),
            "row_pattern": plantilla.patron_linea,
            "ignore": list(plantilla.ignorar),
        },
        "post_rules": {
            "drop_lines_without_total": plantilla.descartar_sin_importe,
            "default_unit": plantilla.unidad_por_defecto,
        },
    }


def desde_jsonb(
    *,
    nombre: str,
    identificador: str | None = None,
    patron_emisor: str | None = None,
    nif_emisor: str | None = None,
    prioridad: int = 100,
    page_settings: dict[str, Any] | None = None,
    header_patterns: dict[str, Any] | None = None,
    line_patterns: dict[str, Any] | None = None,
    post_rules: dict[str, Any] | None = None,
) -> PlantillaExtraccion:
    """La inversa de `a_jsonb()`, tolerante con las plantillas a medio rellenar."""
    lineas = line_patterns or {}
    reglas = post_rules or {}
    return PlantillaExtraccion(
        nombre=nombre,
        identificador=identificador,
        patron_emisor=patron_emisor,
        nif_emisor=nif_emisor,
        prioridad=prioridad,
        campos={
            clave: str(valor)
            for clave, valor in (header_patterns or {}).items()
            if isinstance(valor, str)
        },
        columnas={
            clave: int(valor)
            for clave, valor in (lineas.get("columns") or {}).items()
            if isinstance(valor, int) or (isinstance(valor, str) and valor.isdigit())
        },
        encabezados={
            clave: str(valor)
            for clave, valor in (lineas.get("headers") or {}).items()
            if isinstance(valor, str)
        },
        patron_linea=lineas.get("row_pattern") or None,
        ignorar=[patron for patron in (lineas.get("ignore") or []) if isinstance(patron, str)],
        forzar_ocr=bool((page_settings or {}).get("force_ocr")),
        descartar_sin_importe=bool(reglas.get("drop_lines_without_total", True)),
        unidad_por_defecto=reglas.get("default_unit") or None,
    )


# --------------------------------------------------------------------------- #
# Forma pública: los dos diccionarios planos del contrato de la API
# --------------------------------------------------------------------------- #


def campos_editables(plantilla: PlantillaExtraccion) -> dict[str, str]:
    """`field_patterns` del contrato: todas las reglas en un solo mapa plano.

    Las claves reservadas (`line_row`, `ignore…`, `column:…`) van junto a los
    campos de cabecera porque la pantalla de la plantilla es una sola tabla de
    «nombre de la regla → expresión»: si el usuario tiene que editar la plantilla,
    tiene que verla entera.
    """
    salida: dict[str, str] = dict(plantilla.campos)
    if plantilla.patron_linea:
        salida[CLAVE_FILA] = plantilla.patron_linea
    for nombre, patron in plantilla.encabezados.items():
        salida[f"{PREFIJO_COLUMNA}{nombre}"] = patron
    for indice, patron in enumerate(plantilla.ignorar, start=1):
        salida[f"{PREFIJO_IGNORAR}:{indice}"] = patron
    return salida


def con_campos_editables(
    plantilla: PlantillaExtraccion,
    campos: dict[str, str] | None = None,
    columnas: dict[str, int] | None = None,
) -> PlantillaExtraccion:
    """Vuelca `field_patterns` y `table_columns` sobre la plantilla."""
    if campos is not None:
        cabecera: dict[str, str] = {}
        encabezados: dict[str, str] = {}
        ignorar: list[str] = []
        patron_linea: str | None = None
        for clave, patron in campos.items():
            if clave == CLAVE_FILA:
                patron_linea = patron
            elif clave.startswith(PREFIJO_COLUMNA):
                encabezados[clave[len(PREFIJO_COLUMNA) :]] = patron
            elif clave.split(":", 1)[0] == PREFIJO_IGNORAR:
                ignorar.append(patron)
            else:
                cabecera[clave] = patron
        plantilla.campos = cabecera
        plantilla.encabezados = encabezados
        plantilla.ignorar = ignorar
        plantilla.patron_linea = patron_linea
    if columnas is not None:
        plantilla.columnas = dict(columnas)
    return plantilla


# --------------------------------------------------------------------------- #
# Selección: ¿qué plantilla toca?
# --------------------------------------------------------------------------- #


def texto_de_portada(datos: bytes, *, paginas: int = PAGINAS_DE_PORTADA) -> str:
    """Texto de las primeras páginas, que es donde está el emisor.

    Elegir plantilla no puede costar lo mismo que extraer la factura: si hubiera
    que rasterizar y pasar el OCR solo para saber de quién es, salía más caro que
    la extracción genérica.
    """
    try:
        with pdfplumber.open(BytesIO(datos)) as pdf:
            return "\n".join(pagina.extract_text() or "" for pagina in pdf.pages[: max(1, paginas)])
    except Exception:  # noqa: BLE001 - pdfplumber lanza tipos variados
        logger.debug("No se ha podido leer la portada para elegir plantilla", exc_info=True)
        return ""


def coincide(plantilla: PlantillaExtraccion, texto: str) -> bool:
    """¿Esta factura es de ese emisor?

    Basta con el NIF o con el patrón del emisor. El NIF es el criterio bueno: no
    cambia cuando la compañía rediseña la factura ni cuando se renombra.
    """
    plano = sin_acentos(texto)
    if plantilla.nif_emisor:
        aguja = re.sub(r"[^0-9A-Za-z]", "", plantilla.nif_emisor)
        if aguja and aguja.lower() in re.sub(r"[^0-9A-Za-z]", "", plano).lower():
            return True
    if plantilla.patron_emisor:
        try:
            return (
                compilar(plantilla.patron_emisor, donde="issuer_pattern").search(plano) is not None
            )
        except PlantillaInvalida:
            return False
    return False


def seleccionar(plantillas: Iterable[PlantillaExtraccion], texto: str) -> list[PlantillaExtraccion]:
    """Las plantillas que reconocen esta factura, de más específica a menos.

    Menor prioridad gana, que es lo que dice la columna: así una plantilla del
    hogar (prioridad baja) se pone delante de la de serie de la instalación.
    """
    candidatas = [plantilla for plantilla in plantillas if coincide(plantilla, texto)]
    candidatas.sort(key=lambda una: (una.prioridad, una.nombre))
    return candidatas


# --------------------------------------------------------------------------- #
# Aplicar la plantilla
# --------------------------------------------------------------------------- #


def _valor_bruto(texto: str, patron: str, *, donde: str) -> str | None:
    """Lo que captura la regla: el grupo `valor`, el primero o toda la coincidencia."""
    coincidencia = compilar(patron, donde=donde).search(texto)
    if coincidencia is None:
        return None
    if "valor" in coincidencia.groupdict():
        capturado = coincidencia.group("valor")
    elif coincidencia.groups():
        capturado = coincidencia.group(1)
    else:
        capturado = coincidencia.group(0)
    return capturado.strip() if capturado else None


def valor_de_campo(texto: str, campo: str, patron: str) -> Any | None:
    """Aplica una regla de cabecera y convierte al tipo del campo."""
    bruto = _valor_bruto(texto, patron, donde=campo)
    if not bruto:
        return None
    if campo in CAMPOS_IMPORTE:
        return parsear_importe(bruto)
    if campo in CAMPOS_FECHA:
        return parsear_fecha(bruto)
    if campo == "issuer_tax_id":
        return re.sub(r"[^0-9A-Za-z]", "", bruto).upper() or None
    if campo == "currency":
        return bruto.upper()[:3]
    return re.sub(r"\s+", " ", bruto).strip()[:200]


def _aplicar_cabecera(factura: FacturaExtraida, texto: str, plantilla: PlantillaExtraccion) -> None:
    """Las reglas de la plantilla pisan lo que leyó el extractor genérico.

    Si una regla no encuentra nada se conserva el valor genérico y se avisa: es
    mejor una cabecera a medias que una cabecera vacía, y el aviso es la señal de
    que la plantilla se ha quedado vieja porque el emisor cambió el diseño.
    """
    for campo, patron in plantilla.campos.items():
        atributo = _ATRIBUTO.get(campo)
        if atributo is None:
            continue
        valor = valor_de_campo(texto, campo, patron)
        if valor is None:
            factura.avisos.append(
                f"La plantilla «{plantilla.nombre}» no ha encontrado {campo} en esta factura."
            )
            continue
        setattr(factura, atributo, valor)


def _mapa_de_columnas(
    plantilla: PlantillaExtraccion, cabecera: Sequence[str | None]
) -> dict[str, int] | None:
    """Traduce las columnas de la plantilla al mapa que consume `_linea_desde_fila`."""
    mapa: dict[str, int] = {}
    for nombre, indice in plantilla.columnas.items():
        interno = _COLUMNA_INTERNA.get(nombre)
        if interno is not None:
            mapa[interno] = indice
    for nombre, patron in plantilla.encabezados.items():
        interno = _COLUMNA_INTERNA.get(nombre)
        if interno is None:
            continue
        compilado = compilar(patron, donde=f"{PREFIJO_COLUMNA}{nombre}")
        for indice, celda in enumerate(cabecera):
            if celda and compilado.search(str(celda)):
                mapa[interno] = indice
                break
    if "descripcion" not in mapa:
        return None
    return mapa


def _lineas_por_columnas(
    pdf: pdfplumber.PDF, plantilla: PlantillaExtraccion
) -> list[LineaExtraida]:
    """Lee la tabla con las columnas que fija la plantilla, no con las que adivine."""
    lineas: list[LineaExtraida] = []
    for pagina in pdf.pages:
        try:
            tablas = pagina.extract_tables()
        except Exception:  # noqa: BLE001 - pdfplumber lanza errores variados
            logger.debug("No se han podido extraer tablas de una página", exc_info=True)
            continue
        for tabla in tablas:
            if not tabla:
                continue
            mapa = _mapa_de_columnas(plantilla, tabla[0])
            if mapa is None:
                continue
            # Con encabezados declarados, la primera fila es la cabecera y no es
            # una línea; con índices fijos no hay cabecera que saltar.
            inicio = 1 if plantilla.encabezados else 0
            for fila in tabla[inicio:]:
                linea = _linea_desde_fila(list(fila), mapa)
                if linea is not None:
                    lineas.append(linea)
    return lineas


def _lineas_por_patron(texto: str, plantilla: PlantillaExtraccion) -> list[LineaExtraida]:
    """Aplica `line_row` fila a fila: el caso de las facturas sin rejilla."""
    assert plantilla.patron_linea is not None  # noqa: S101 - lo comprueba quien llama
    compilado = compilar(plantilla.patron_linea, donde=CLAVE_FILA)
    lineas: list[LineaExtraida] = []
    for cruda in texto.splitlines():
        limpia = cruda.strip()
        if not limpia:
            continue
        coincidencia = compilado.search(limpia)
        if coincidencia is None:
            continue
        piezas = {
            nombre: (coincidencia.groupdict().get(nombre) or "").strip()
            for nombre in _GRUPOS_LINEA
            if nombre in compilado.groupindex
        }
        descripcion = re.sub(r"\s+", " ", piezas.get("description", "")).strip(" .:-")
        if len(descripcion) < 2:
            continue
        precio = parsear_importe(piezas.get("unit_price") or None)
        lineas.append(
            LineaExtraida(
                descripcion=descripcion,
                cantidad=parsear_importe(piezas.get("quantity") or None),
                unidad=(piezas.get("unit") or None) or plantilla.unidad_por_defecto,
                precio_unitario=(
                    cuantizar(precio, CUATRO_DECIMALES) if precio is not None else None
                ),
                total=parsear_importe(piezas.get("total") or None),
                # Una regla escrita para este emisor concreto es más fiable que la
                # heurística de texto plano, pero menos que una tabla con rejilla.
                confianza=0.7,
            )
        )
    return lineas


def _ignorables(plantilla: PlantillaExtraccion) -> list[re.Pattern[str]]:
    return [
        compilar(patron, donde=f"{PREFIJO_IGNORAR}[{indice}]")
        for indice, patron in enumerate(plantilla.ignorar)
    ]


def _filtrar(lineas: list[LineaExtraida], plantilla: PlantillaExtraccion) -> list[LineaExtraida]:
    """Quita las filas que la plantilla marca como «esto no es un producto»."""
    patrones = _ignorables(plantilla)
    conservadas = [
        linea
        for linea in lineas
        if not any(patron.search(linea.descripcion) for patron in patrones)
    ]
    if plantilla.descartar_sin_importe:
        conservadas = [
            linea
            for linea in conservadas
            if linea.total is not None or linea.precio_unitario is not None
        ]
    if plantilla.unidad_por_defecto:
        for linea in conservadas:
            if linea.unidad is None:
                linea.unidad = plantilla.unidad_por_defecto
    return conservadas


def _cerrar(factura: FacturaExtraida) -> None:
    """El remate común: completar, normalizar, quitar repetidas y puntuar."""
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


def _utilizable(factura: FacturaExtraida, plantilla: PlantillaExtraccion) -> bool:
    """¿Ha servido la plantilla, o hay que caer a las tres pasadas de siempre?

    Si la plantilla dice cómo leer las líneas y no ha salido ninguna, ha fallado:
    devolver una factura sin líneas «según la plantilla» escondería el problema.
    """
    if plantilla.toca_las_lineas and not factura.lineas:
        return False
    return factura.total is not None or bool(factura.lineas)


def aplicar(
    datos: bytes,
    plantilla: PlantillaExtraccion,
    *,
    max_bytes: int = 20 * 1024 * 1024,
    max_paginas: int = 40,
    ocr_habilitado: bool = True,
    idiomas_ocr: str = "spa+eng",
) -> FacturaExtraida | None:
    """Lee el PDF con la plantilla. None si no ha dado un resultado utilizable.

    Se apoya en las tres pasadas de `extraccion_pdf` y aplica encima las reglas:
    una plantilla solo tiene que arreglar lo que el extractor falla con ese
    emisor, que es exactamente lo que el usuario corregía a mano cada mes.
    """
    errores = validar(plantilla)
    if errores:
        raise PlantillaInvalida(errores[0])

    paginas = validar_pdf(datos, max_bytes, max_paginas)
    factura = FacturaExtraida(paginas=paginas)

    with pdfplumber.open(BytesIO(datos)) as pdf:
        texto = "\n".join(pagina.extract_text() or "" for pagina in pdf.pages)
        por_ocr = plantilla.forzar_ocr or len(texto.strip()) < MINIMO_CAPA_DE_TEXTO
        if por_ocr and ocr_habilitado:
            texto_ocr = _texto_por_ocr(datos, idiomas_ocr, max_paginas)
            if texto_ocr.strip():
                texto = texto_ocr
                factura.metodo = "ocr"

        factura.texto_crudo = texto
        _leer_cabecera(factura, texto)
        _aplicar_cabecera(factura, texto, plantilla)

        if plantilla.columnas or plantilla.encabezados:
            lineas = _lineas_por_columnas(pdf, plantilla)
            if lineas and factura.metodo != "ocr":
                factura.metodo = "tabla"
        elif plantilla.patron_linea:
            lineas = _lineas_por_patron(texto, plantilla)
            if lineas and factura.metodo != "ocr":
                factura.metodo = "texto"
        else:
            # La plantilla solo arregla la cabecera: las líneas, como siempre.
            lineas = _extraer_de_tablas(pdf)
            if lineas:
                if factura.metodo != "ocr":
                    factura.metodo = "tabla"
            else:
                lineas = _extraer_de_texto(texto)
                if factura.metodo != "ocr":
                    factura.metodo = "texto" if lineas else "ninguno"
        factura.lineas = _filtrar(lineas, plantilla)

    _cerrar(factura)
    if not _utilizable(factura, plantilla):
        return None
    return factura


# --------------------------------------------------------------------------- #
# El envoltorio: plantilla primero, tres pasadas después
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Resultado:
    """Lo leído y con qué se ha leído, para poder anotar aciertos y fallos."""

    factura: FacturaExtraida
    plantilla: PlantillaExtraccion | None = None
    fallidas: list[PlantillaExtraccion] = field(default_factory=list)
    """Las que reconocieron la factura pero no dieron un resultado utilizable."""


def extraer_con_plantillas(
    datos: bytes,
    plantillas: Sequence[PlantillaExtraccion] = (),
    *,
    exigir_coincidencia: bool = True,
    max_bytes: int = 20 * 1024 * 1024,
    max_paginas: int = 40,
    ocr_habilitado: bool = True,
    idiomas_ocr: str = "spa+eng",
) -> Resultado:
    """Punto de entrada de la extracción con plantillas, con caída a la genérica.

    `exigir_coincidencia=False` es para cuando el usuario ha elegido la plantilla
    a mano: se prueba aunque su patrón no reconozca el documento, porque el
    usuario sabe algo que el patrón no dice.
    """
    from app.services.extraccion_pdf import extraer_factura

    opciones = {
        "max_bytes": max_bytes,
        "max_paginas": max_paginas,
        "ocr_habilitado": ocr_habilitado,
        "idiomas_ocr": idiomas_ocr,
    }
    if exigir_coincidencia:
        candidatas = seleccionar(plantillas, texto_de_portada(datos))
    else:
        candidatas = sorted(plantillas, key=lambda una: (una.prioridad, una.nombre))

    fallidas: list[PlantillaExtraccion] = []
    for plantilla in candidatas:
        try:
            factura = aplicar(datos, plantilla, **opciones)  # type: ignore[arg-type]
        except PlantillaInvalida:
            logger.warning("Plantilla «%s» inválida: se ignora", plantilla.nombre)
            fallidas.append(plantilla)
            continue
        if factura is not None:
            factura.avisos.append(f"Leída con la plantilla «{plantilla.nombre}» del emisor.")
            return Resultado(factura, plantilla, fallidas)
        fallidas.append(plantilla)

    factura = extraer_factura(datos, **opciones)  # type: ignore[arg-type]
    if fallidas:
        factura.avisos.append(
            "La plantilla del emisor no ha servido con esta factura y se ha leído con el "
            "método general. Revisa la plantilla: puede que el emisor haya cambiado el diseño."
        )
    return Resultado(factura, None, fallidas)


# --------------------------------------------------------------------------- #
# Deducir la plantilla de una factura ya corregida
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LineaCorregida:
    """Una línea tal y como la dejó el usuario tras revisar."""

    descripcion: str
    cantidad: Decimal | None = None
    unidad: str | None = None
    precio_unitario: Decimal | None = None
    total: Decimal | None = None
    excluida: bool = False


@dataclass(frozen=True, slots=True)
class FacturaCorregida:
    """La verdad: lo que el usuario dejó bueno, más el texto crudo del PDF."""

    texto: str
    emisor: str | None = None
    nif_emisor: str | None = None
    numero: str | None = None
    fecha: date | None = None
    base_imponible: Decimal | None = None
    impuestos: Decimal | None = None
    total: Decimal | None = None
    moneda: str | None = None
    lineas: tuple[LineaCorregida, ...] = ()


@dataclass(slots=True)
class Deduccion:
    """La plantilla propuesta y el porqué de cada regla, en español."""

    plantilla: PlantillaExtraccion
    deducidos: list[str] = field(default_factory=list)
    """Campos para los que se ha encontrado una regla que acierta."""
    ya_correctos: list[str] = field(default_factory=list)
    """Campos que el extractor genérico ya lee bien: no necesitan regla."""
    sin_resolver: list[str] = field(default_factory=list)
    """Campos corregidos a mano que no se han podido explicar con una regla."""
    notas: list[str] = field(default_factory=list)


#: Cuerpos de expresión por tipo de campo. Sueltos y sin grupos: se envuelven al
#: montar la regla.
# El espacio y el tabulador entran (hay facturas con «1 234,56») pero el salto de
# línea no: `\s` habría dejado que un importe se llevara cifras de la línea
# siguiente y la regla se verificaba mal.
_CUERPO_IMPORTE = r"-?\d[\d.,\t ]{0,14}\d|-?\d"
_CUERPO_FECHA = (
    r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"|\d{1,2}\s+de\s+[a-zA-ZáéíóúÁÉÍÓÚ]+\s+de(?:l)?\s+\d{4}"
)
_CUERPO_TEXTO = r"[^\n]{1,120}?"

#: Catálogo de formas de fila que se prueban cuando el extractor no vio las
#: líneas. Se elige la que reproduce lo que el usuario dejó, no la más bonita.
_FILAS_CANDIDATAS = (
    r"^(?P<description>.+?)\s+(?P<quantity>[\d.,]+)\s*(?P<unit>[A-Za-z/]{1,4})?\s+"
    r"(?P<unit_price>[\d.,]+)\s+(?P<total>-?[\d.,]+)\s*€?$",
    r"^(?P<description>.+?)\s+(?P<quantity>[\d.,]+)\s+(?P<unit_price>[\d.,]+)\s+"
    r"(?P<total>-?[\d.,]+)\s*€?$",
    r"^(?P<description>.+?)\s{2,}(?P<total>-?[\d.,]+)\s*€?$",
    r"^(?P<description>.+?)\s+(?P<total>-?[\d.,]+)\s*€?$",
)

#: Proporción de líneas que una forma de fila tiene que reproducir para valer.
ACIERTO_MINIMO_DE_FILA = Decimal("0.8")


def _apariciones(valor: str) -> list[str]:
    """Cómo puede estar escrito un valor en el PDF, de lo más literal a lo menos."""
    return [valor, re.sub(r"\s+", " ", valor).strip()]


def _renderizados(campo: str, valor: Any) -> list[str]:
    """Todas las formas plausibles del valor corregido dentro del texto."""
    if campo in CAMPOS_IMPORTE and isinstance(valor, Decimal):
        entero, _, decimales = f"{valor:.2f}".partition(".")
        con_miles = f"{int(entero):,}".replace(",", ".")
        return [f"{entero},{decimales}", f"{con_miles},{decimales}"]
    if campo in CAMPOS_FECHA and isinstance(valor, date):
        return [
            f"{valor.day:02d}/{valor.month:02d}/{valor.year}",
            f"{valor.day}/{valor.month}/{valor.year}",
            f"{valor.day:02d}-{valor.month:02d}-{valor.year}",
            f"{valor.day:02d}.{valor.month:02d}.{valor.year}",
            valor.isoformat(),
        ]
    return _apariciones(str(valor))


def _cuerpo_de(campo: str) -> str:
    if campo in CAMPOS_IMPORTE:
        return _CUERPO_IMPORTE
    if campo in CAMPOS_FECHA:
        return _CUERPO_FECHA
    return _CUERPO_TEXTO


def _reglas_candidatas(texto: str, campo: str, aparicion: str) -> list[str]:
    """Reglas posibles para un valor que está en el texto, de la mejor a la peor.

    La buena es la que se ancla en la **etiqueta** que precede al valor en la
    misma línea («TOTAL A PAGAR 32,08»): sobrevive a que el importe cambie de mes
    y a que la línea se mueva de sitio. La de reserva fija la línea completa, que
    aguanta menos pero salva las facturas donde el dato no lleva etiqueta.
    """
    candidatas: list[str] = []
    cuerpo = _cuerpo_de(campo)
    for linea in texto.splitlines():
        posicion = linea.find(aparicion)
        if posicion < 0:
            continue
        antes = linea[:posicion]
        palabras = re.findall(r"[^\s]+", antes)
        # De la etiqueta más larga a la más corta: «total a pagar» antes que «pagar».
        for cuantas in range(min(4, len(palabras)), 0, -1):
            etiqueta = " ".join(palabras[-cuantas:])
            if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{2}", etiqueta):
                continue
            # `re.escape()` deja el espacio como `\ `; hay que sustituir esa
            # pareja y no el espacio suelto, o queda un `\\s+` que significa
            # «una barra invertida seguida de eses» y la regla no casa nunca.
            hueco = re.sub(r"\\ ", r"\\s+", re.escape(etiqueta))
            candidatas.append(rf"{hueco}\s*[:.]?\s*(?P<valor>{cuerpo})")
        if palabras:
            continue
        # El valor abre la línea y no hay etiqueta a la que agarrarse: se ancla en
        # lo que viene detrás. Si ese texto lleva cifras, no se usa: sería fijar en
        # la plantilla el número de esta factura («… FACTURA Nº TI-2026/0031») y
        # dejaría de coincidir el mes siguiente.
        detras = linea[posicion + len(aparicion) :].strip()
        if re.search(r"\d", detras):
            continue
        cola = rf"\s*{re.sub(r'\\ ', r'\\s+', re.escape(detras))}" if detras else r"\s*$"
        candidatas.append(rf"^\s*(?P<valor>{cuerpo}){cola}")
    return candidatas


def _regla_verificada(texto: str, campo: str, esperado: Any) -> str | None:
    """Propone una regla y la comprueba: solo vale si devuelve el valor corregido.

    Sin esta verificación la deducción sería adivinar. Con ella, lo que se guarda
    en la plantilla ya se sabe que acierta al menos en esta factura.
    """
    for aparicion in _renderizados(campo, esperado):
        if not aparicion or aparicion not in texto:
            continue
        for regla in _reglas_candidatas(texto, campo, aparicion):
            try:
                if valor_de_campo(texto, campo, regla) == esperado:
                    return regla
            except PlantillaInvalida:
                continue
    return None


def _regla_literal(valor: str) -> str:
    """El valor tal cual, escapado y con los espacios flexibles.

    Para el emisor no es un parche sino **la** regla: el emisor de las facturas de
    una compañía es siempre el mismo texto —por eso la plantilla es «por
    proveedor»—, mientras que la heurística genérica se equivoca justo ahí, porque
    en el PDF el nombre comparte línea con el número de factura.
    """
    escapado = re.sub(r"\\ ", r"\\s+", re.escape(valor.strip()))
    return rf"(?P<valor>{escapado})"


def _normalizar_descripcion(texto: str) -> str:
    return re.sub(r"\s+", " ", sin_acentos(texto).lower()).strip()


def _regla_ignorar(descripcion: str, conservadas: Sequence[str]) -> str | None:
    """Regla que descarta esa fila sin llevarse por delante ninguna de las buenas."""
    palabras = re.findall(r"[\wÁÉÍÓÚáéíóúÑñ]+", descripcion)
    for cuantas in range(min(4, len(palabras)), 0, -1):
        aguja = " ".join(palabras[:cuantas])
        if len(aguja) < 3:
            continue
        patron = rf"^\s*{re.sub(r'\\ ', r'\\s+', re.escape(aguja))}"
        try:
            compilado = compilar(patron, donde=PREFIJO_IGNORAR)
        except PlantillaInvalida:
            continue
        if compilado.search(descripcion) and not any(
            compilado.search(buena) for buena in conservadas
        ):
            return patron
    return None


def _mejor_patron_de_fila(texto: str, buenas: Sequence[LineaCorregida]) -> str | None:
    """La forma de fila que mejor reproduce las líneas que dejó el usuario."""
    if not buenas:
        return None
    esperadas = {
        (_normalizar_descripcion(linea.descripcion), linea.total)
        for linea in buenas
        if linea.total is not None
    }
    if not esperadas:
        return None
    minimo = max(1, int(len(esperadas) * ACIERTO_MINIMO_DE_FILA))
    for patron in _FILAS_CANDIDATAS:
        plantilla = PlantillaExtraccion(nombre="prueba", patron_linea=patron)
        leidas = {
            (_normalizar_descripcion(linea.descripcion), linea.total)
            for linea in _lineas_por_patron(texto, plantilla)
        }
        if len(esperadas & leidas) >= minimo:
            return patron
    return None


def deducir(
    corregida: FacturaCorregida,
    leida: FacturaExtraida | None = None,
    *,
    nombre: str = "",
    patron_emisor: str | None = None,
) -> Deduccion:
    """Propone la plantilla que habría leído bien esta factura.

    Compara lo que el extractor leyó (`leida`) con lo que el usuario dejó
    (`corregida`) y **solo** escribe reglas para lo que falló: una plantilla que
    repite lo que ya funciona es una plantilla que se rompe sola en cuanto el
    extractor mejore. Si no se pasa `leida`, se supone que todo estaba mal y se
    intenta explicar cada campo.
    """
    texto = corregida.texto or ""
    plantilla = PlantillaExtraccion(
        nombre=nombre or (corregida.emisor or "Plantilla sin nombre"),
        nif_emisor=corregida.nif_emisor,
    )
    deduccion = Deduccion(plantilla=plantilla)

    valores: dict[str, Any] = {
        "issuer": corregida.emisor,
        "issuer_tax_id": corregida.nif_emisor,
        "number": corregida.numero,
        "date": corregida.fecha,
        "taxable_base": corregida.base_imponible,
        "tax_amount": corregida.impuestos,
        "total": corregida.total,
    }
    for campo, bueno in valores.items():
        if bueno in (None, ""):
            continue
        atributo = _ATRIBUTO[campo]
        actual = getattr(leida, atributo, None) if leida is not None else None
        if leida is not None and actual == bueno:
            deduccion.ya_correctos.append(campo)
            continue
        regla = None
        # En un campo de texto el valor **es** la regla y no cambia de una factura
        # a otra del mismo emisor, así que se prueba antes que el anclaje por
        # etiqueta: para el emisor, «Telefónica S.L.» aguanta mejor que cualquier
        # etiqueta que se le ponga delante.
        if campo in CAMPOS_TEXTO and str(bueno) in texto:
            candidata = _regla_literal(str(bueno))
            if valor_de_campo(texto, campo, candidata) == bueno:
                regla = candidata
        if regla is None:
            regla = _regla_verificada(texto, campo, bueno)
        if regla is None:
            deduccion.sin_resolver.append(campo)
            continue
        plantilla.campos[campo] = regla
        deduccion.deducidos.append(campo)

    # Selector: el patrón del emisor. El NIF ya va aparte y es el criterio bueno.
    if patron_emisor:
        plantilla.patron_emisor = patron_emisor
    elif corregida.emisor:
        palabras = re.findall(r"[\wÁÉÍÓÚáéíóúÑñ&.]+", sin_acentos(corregida.emisor))[:3]
        if palabras:
            plantilla.patron_emisor = re.sub(r"\\ ", r"\\s+", re.escape(" ".join(palabras)))

    _deducir_lineas(deduccion, corregida, leida)
    _redactar_notas(deduccion)
    return deduccion


def _deducir_lineas(
    deduccion: Deduccion, corregida: FacturaCorregida, leida: FacturaExtraida | None
) -> None:
    """Reglas de las líneas: cómo se leen y, sobre todo, qué filas sobran."""
    plantilla = deduccion.plantilla
    buenas = [linea for linea in corregida.lineas if not linea.excluida]
    conservadas = [_normalizar_descripcion(linea.descripcion) for linea in buenas]

    faltan = [
        linea
        for linea in buenas
        if leida is None
        or not any(
            _normalizar_descripcion(otra.descripcion) == _normalizar_descripcion(linea.descripcion)
            for otra in leida.lineas
        )
    ]
    # Si el extractor ya veía casi todas las líneas, no se toca cómo se leen: un
    # `line_row` innecesario solo puede empeorar la siguiente factura.
    if faltan and len(faltan) * 2 >= len(buenas):
        patron = _mejor_patron_de_fila(corregida.texto or "", buenas)
        if patron is not None:
            plantilla.patron_linea = patron
            deduccion.deducidos.append("line_row")
        else:
            deduccion.sin_resolver.append("line_row")

    # Filas que sobran. Se juntan tres orígenes, porque cada uno se le escapa a los
    # otros dos:
    #   1. lo que el extractor leyó y el usuario borró (subtotales, portes),
    #   2. lo que el usuario marcó como «no es un producto» (RN-48: la potencia
    #      contratada, la cuota de servicio), que el extractor quizá ni vio, y
    #   3. lo que el `line_row` recién deducido leería de más: sin esto, la
    #      plantilla resucitaría justo las filas que el usuario acaba de excluir.
    sobrantes: list[str] = []
    if leida is not None:
        sobrantes.extend(_normalizar_descripcion(linea.descripcion) for linea in leida.lineas)
    sobrantes.extend(
        _normalizar_descripcion(linea.descripcion) for linea in corregida.lineas if linea.excluida
    )
    if plantilla.patron_linea:
        sobrantes.extend(
            _normalizar_descripcion(linea.descripcion)
            for linea in _lineas_por_patron(
                corregida.texto or "",
                PlantillaExtraccion(nombre=plantilla.nombre, patron_linea=plantilla.patron_linea),
            )
        )
    for descripcion in dict.fromkeys(sobrantes):
        if descripcion in conservadas:
            continue
        regla = _regla_ignorar(descripcion, conservadas)
        if regla is not None and regla not in plantilla.ignorar:
            plantilla.ignorar.append(regla)


def _redactar_notas(deduccion: Deduccion) -> None:
    """El resumen que se le muestra al usuario antes de guardar la plantilla."""
    plantilla = deduccion.plantilla
    if deduccion.deducidos:
        deduccion.notas.append(
            f"Se han deducido reglas para: {', '.join(sorted(set(deduccion.deducidos)))}."
        )
    if deduccion.ya_correctos:
        deduccion.notas.append(
            "No hacen falta reglas para "
            f"{', '.join(sorted(set(deduccion.ya_correctos)))}: ya se leen bien."
        )
    if plantilla.ignorar:
        cuantas = len(plantilla.ignorar)
        deduccion.notas.append(
            "Se descartará 1 fila que no es un producto."
            if cuantas == 1
            else f"Se descartarán {cuantas} filas que no son productos."
        )
    if deduccion.sin_resolver:
        deduccion.notas.append(
            "No se ha podido deducir ninguna regla para "
            f"{', '.join(sorted(set(deduccion.sin_resolver)))}: corrígelo a mano en la "
            "plantilla o revísalo en cada factura."
        )
    if not deduccion.deducidos and not plantilla.ignorar:
        deduccion.notas.append(
            "Esta factura se lee bien sin plantilla: guardarla solo sirve para fijar el "
            "comercio y la temática por defecto."
        )
