"""Importación de extractos bancarios en CSV.

Cada banco español exporta el CSV a su manera: distinto delimitador, distinta
codificación, filas de cabecera antes de la tabla real, el importe en una
columna o en dos (debe y haber), y el signo puesto de formas creativas. Este
módulo detecta todo eso y devuelve filas normalizadas más los errores, para que
el usuario revise antes de confirmar la importación.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.services.normalizacion import sin_acentos
from app.services.numeros import parsear_decimal, parsear_fecha

# Se prueban en este orden: la mayoría de bancos españoles exportan en cp1252.
CODIFICACIONES = ("utf-8-sig", "utf-8", "cp1252", "iso-8859-15", "latin-1")

DELIMITADORES = (";", ",", "\t", "|")

# Alias de cabecera vistos en los CSV de BBVA, Santander, CaixaBank, ING,
# Sabadell, Openbank, Revolut y N26.
ALIAS_CABECERA: dict[str, tuple[str, ...]] = {
    "fecha": (
        "fecha",
        "fecha operacion",
        "fecha de operacion",
        "f. operacion",
        "fecha valor",
        "fecha contable",
        "date",
        "completed date",
        "booking date",
        "value date",
    ),
    "concepto": (
        "concepto",
        "descripcion",
        "descripcion operacion",
        "concepto ampliado",
        "movimiento",
        "detalle",
        "observaciones",
        "referencia",
        "description",
        "payee",
        "merchant",
    ),
    "importe": (
        "importe",
        "importe eur",
        "importe operacion",
        "cantidad",
        "amount",
        "importe (eur)",
        "valor",
    ),
    "cargo": ("debe", "cargo", "cargos", "gasto", "pago", "salida", "debit", "withdrawal"),
    "abono": ("haber", "abono", "abonos", "ingreso", "entrada", "credit", "deposit"),
    "saldo": ("saldo", "saldo disponible", "saldo posterior", "balance"),
    "divisa": ("divisa", "moneda", "currency"),
    "categoria": ("categoria", "category"),
}


class EstadoFila(StrEnum):
    VALIDA = "valida"
    ERROR = "error"
    DUPLICADA = "duplicada"


class ErrorImportacion(Exception):
    """El fichero no se puede importar."""


@dataclass(slots=True)
class MapeoColumnas:
    """Qué columna del CSV corresponde a cada campo."""

    fecha: int | None = None
    concepto: int | None = None
    importe: int | None = None
    cargo: int | None = None
    abono: int | None = None
    saldo: int | None = None
    divisa: int | None = None
    categoria: int | None = None

    @property
    def completo(self) -> bool:
        """Con fecha, concepto y algún importe ya se puede importar."""
        tiene_importe = self.importe is not None or (
            self.cargo is not None or self.abono is not None
        )
        return self.fecha is not None and self.concepto is not None and tiene_importe

    @property
    def campos_que_faltan(self) -> list[str]:
        faltan = []
        if self.fecha is None:
            faltan.append("fecha")
        if self.concepto is None:
            faltan.append("concepto")
        if self.importe is None and self.cargo is None and self.abono is None:
            faltan.append("importe")
        return faltan


@dataclass(slots=True)
class FilaImportada:
    """Una fila del CSV ya interpretada."""

    numero: int
    """Número de línea en el fichero original, para poder señalarla al usuario."""
    fecha: date | None = None
    concepto: str = ""
    importe: Decimal | None = None
    saldo: Decimal | None = None
    divisa: str | None = None
    categoria_sugerida: str | None = None
    estado: EstadoFila = EstadoFila.VALIDA
    error: str | None = None
    huella: str = ""
    """Identifica la fila para detectar duplicados entre importaciones."""
    crudo: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ResultadoImportacion:
    """Todo lo que la pantalla de revisión necesita mostrar."""

    filas: list[FilaImportada] = field(default_factory=list)
    mapeo: MapeoColumnas = field(default_factory=MapeoColumnas)
    cabecera: list[str] = field(default_factory=list)
    delimitador: str = ";"
    codificacion: str = "utf-8"
    fila_cabecera: int = 0
    """Índice de la fila donde estaba la cabecera; antes puede haber metadatos."""
    avisos: list[str] = field(default_factory=list)

    @property
    def validas(self) -> list[FilaImportada]:
        return [f for f in self.filas if f.estado is EstadoFila.VALIDA]

    @property
    def con_error(self) -> list[FilaImportada]:
        return [f for f in self.filas if f.estado is EstadoFila.ERROR]

    @property
    def duplicadas(self) -> list[FilaImportada]:
        return [f for f in self.filas if f.estado is EstadoFila.DUPLICADA]

    @property
    def total_importado(self) -> Decimal:
        return sum((f.importe or Decimal(0) for f in self.validas), Decimal(0))


def _decodificar(datos: bytes) -> tuple[str, str]:
    """Devuelve el texto y el nombre de la codificación que ha funcionado."""
    for codificacion in CODIFICACIONES:
        try:
            return datos.decode(codificacion), codificacion
        except UnicodeDecodeError:
            continue
    # latin-1 acepta cualquier byte, así que esto solo pasa con un fichero vacío.
    raise ErrorImportacion("No se ha podido leer el fichero: codificación no reconocida.")


def _detectar_delimitador(texto: str) -> str:
    """Elige el delimitador que parte el fichero en columnas de forma consistente.

    No se usa `csv.Sniffer`: con importes en formato español confunde la coma
    decimal de "-30,15" con el separador de campos y parte las filas por la
    mitad. Aquí se prueba cada candidato y gana el que da más columnas con el
    mismo número en todas las líneas; a igualdad, manda el orden de
    `DELIMITADORES`, que empieza por el punto y coma porque es el que usan los
    bancos españoles precisamente para no chocar con la coma decimal.
    """
    lineas = [linea for linea in texto.splitlines()[:20] if linea.strip()]
    if not lineas:
        return ";"

    mejor, mejor_puntuacion = ";", (-1, -1)
    for delimitador in DELIMITADORES:
        try:
            filas = list(csv.reader(lineas, delimiter=delimitador))
        except csv.Error:
            continue
        anchuras = {len(fila) for fila in filas if any(celda.strip() for celda in fila)}
        if not anchuras:
            continue
        columnas = max(anchuras)
        if columnas < 2:
            continue
        # Una sola anchura distinta significa que todas las filas encajan.
        puntuacion = (1 if len(anchuras) == 1 else 0, columnas)
        if puntuacion > mejor_puntuacion:
            mejor, mejor_puntuacion = delimitador, puntuacion
    return mejor


def _normalizar_cabecera(texto: str) -> str:
    limpio = sin_acentos(texto).lower().strip().strip('"')
    return re.sub(r"[\s_]+", " ", limpio).strip(" .:")


def detectar_mapeo(cabecera: list[str]) -> MapeoColumnas:
    """Asocia las columnas del CSV con los campos que necesitamos."""
    mapeo = MapeoColumnas()
    normalizadas = [_normalizar_cabecera(celda) for celda in cabecera]

    for campo, alias in ALIAS_CABECERA.items():
        for indice, celda in enumerate(normalizadas):
            if not celda:
                continue
            # Coincidencia exacta primero; si no, que empiece por el alias.
            if celda in alias or any(celda.startswith(a) for a in alias):
                if getattr(mapeo, campo) is None:
                    setattr(mapeo, campo, indice)
                break
    return mapeo


def _localizar_cabecera(filas: list[list[str]]) -> tuple[int, MapeoColumnas]:
    """Busca la fila que hace de cabecera.

    Varios bancos meten el titular, el IBAN y el periodo antes de la tabla, así
    que la cabecera real puede estar en la fila 5 o en la 8.
    """
    mejor_indice, mejor_mapeo, mejor_puntuacion = 0, MapeoColumnas(), -1
    for indice, fila in enumerate(filas[:15]):
        mapeo = detectar_mapeo(fila)
        puntuacion = sum(
            1
            for campo in ("fecha", "concepto", "importe", "cargo", "abono")
            if getattr(mapeo, campo) is not None
        )
        if puntuacion > mejor_puntuacion:
            mejor_indice, mejor_mapeo, mejor_puntuacion = indice, mapeo, puntuacion
        if mapeo.completo:
            return indice, mapeo
    return mejor_indice, mejor_mapeo


def calcular_huella(fecha: date | None, importe: Decimal | None, concepto: str) -> str:
    """Identificador estable de un movimiento, para detectar duplicados.

    Se normaliza el concepto porque el mismo apunte reexportado puede venir con
    espaciado distinto. No se usa el saldo: cambia si se reordenan los apuntes.
    """
    texto = re.sub(r"\s+", " ", sin_acentos(concepto).lower()).strip()
    base = f"{fecha.isoformat() if fecha else ''}|{importe if importe is not None else ''}|{texto}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def _interpretar_importe(fila: list[str], mapeo: MapeoColumnas) -> Decimal | None:
    """Obtiene el importe con su signo, venga en una columna o en dos."""
    if mapeo.importe is not None and mapeo.importe < len(fila):
        return parsear_decimal(fila[mapeo.importe])

    # Formato debe/haber: el cargo es un gasto (negativo) y el abono un ingreso.
    cargo = None
    abono = None
    if mapeo.cargo is not None and mapeo.cargo < len(fila):
        cargo = parsear_decimal(fila[mapeo.cargo])
    if mapeo.abono is not None and mapeo.abono < len(fila):
        abono = parsear_decimal(fila[mapeo.abono])

    if cargo and cargo != 0:
        return -abs(cargo)
    if abono and abono != 0:
        return abs(abono)
    return None


def _celda(fila: list[str], indice: int | None) -> str:
    if indice is None or indice >= len(fila):
        return ""
    return fila[indice].strip()


def importar_csv(
    datos: bytes,
    *,
    mapeo_manual: MapeoColumnas | None = None,
    sin_cabecera: bool = False,
    huellas_existentes: set[str] | None = None,
    max_filas: int = 5000,
) -> ResultadoImportacion:
    """Interpreta un CSV bancario y devuelve las filas listas para revisar.

    No lanza excepción por filas malas: las marca con su error para que el
    usuario las corrija o las descarte. Solo falla si el fichero entero es
    ilegible o no se reconocen las columnas mínimas.

    `sin_cabecera` va de la mano de `mapeo_manual`: si la detección automática
    ha fallado porque el fichero no tiene fila de cabecera, hay que decirlo
    explícitamente o se perdería el primer movimiento.
    """
    if not datos:
        raise ErrorImportacion("El fichero está vacío.")

    texto, codificacion = _decodificar(datos)
    if not texto.strip():
        raise ErrorImportacion("El fichero está vacío.")

    delimitador = _detectar_delimitador(texto)
    filas_crudas = [
        fila for fila in csv.reader(io.StringIO(texto), delimiter=delimitador) if any(fila)
    ]
    if not filas_crudas:
        raise ErrorImportacion("El fichero no contiene filas.")

    resultado = ResultadoImportacion(delimitador=delimitador, codificacion=codificacion)

    if mapeo_manual is not None:
        mapeo = mapeo_manual
        # -1 significa "no hay cabecera": el cuerpo empieza en la primera fila.
        indice_cabecera = -1 if sin_cabecera else 0
    else:
        indice_cabecera, mapeo = _localizar_cabecera(filas_crudas)

    resultado.mapeo = mapeo
    resultado.fila_cabecera = indice_cabecera
    resultado.cabecera = filas_crudas[indice_cabecera] if indice_cabecera >= 0 else []

    if not mapeo.completo:
        faltan = ", ".join(mapeo.campos_que_faltan)
        raise ErrorImportacion(
            f"No se han reconocido las columnas de: {faltan}. "
            "Indica a mano qué columna es cada cosa."
        )

    if indice_cabecera > 0:
        resultado.avisos.append(
            f"Se han ignorado las {indice_cabecera} primeras líneas del fichero: "
            "no formaban parte de la tabla de movimientos."
        )

    huellas_vistas: set[str] = set(huellas_existentes or ())
    cuerpo = filas_crudas[indice_cabecera + 1 :]

    if len(cuerpo) > max_filas:
        resultado.avisos.append(
            f"El fichero tiene {len(cuerpo)} movimientos y el máximo por importación "
            f"son {max_filas}. Se han leído los {max_filas} primeros."
        )
        cuerpo = cuerpo[:max_filas]

    for desplazamiento, fila_cruda in enumerate(cuerpo):
        numero = indice_cabecera + 2 + desplazamiento  # 1-indexado, como lo ve el usuario
        fila = FilaImportada(numero=numero, crudo=list(fila_cruda))

        concepto = _celda(fila_cruda, mapeo.concepto)
        fila.concepto = re.sub(r"\s+", " ", concepto)
        fila.fecha = parsear_fecha(_celda(fila_cruda, mapeo.fecha))
        fila.importe = _interpretar_importe(fila_cruda, mapeo)
        fila.saldo = parsear_decimal(_celda(fila_cruda, mapeo.saldo)) if mapeo.saldo else None
        fila.divisa = _celda(fila_cruda, mapeo.divisa) or None
        fila.categoria_sugerida = _celda(fila_cruda, mapeo.categoria) or None

        problemas = []
        if fila.fecha is None:
            problemas.append("no se entiende la fecha")
        if fila.importe is None:
            problemas.append("no se entiende el importe")
        elif fila.importe == 0:
            problemas.append("el importe es cero")
        if not fila.concepto:
            problemas.append("falta el concepto")

        if problemas:
            fila.estado = EstadoFila.ERROR
            fila.error = "; ".join(problemas).capitalize() + "."
            resultado.filas.append(fila)
            continue

        fila.importe = fila.importe.quantize(Decimal("0.01"))
        fila.huella = calcular_huella(fila.fecha, fila.importe, fila.concepto)
        if fila.huella in huellas_vistas:
            fila.estado = EstadoFila.DUPLICADA
            fila.error = "Este movimiento ya está registrado."
        else:
            huellas_vistas.add(fila.huella)

        resultado.filas.append(fila)

    if not resultado.validas:
        resultado.avisos.append("No hay ningún movimiento nuevo que importar en este fichero.")

    return resultado


def previsualizar(datos: bytes, filas: int = 10) -> dict[str, object]:
    """Lee solo la cabecera y unas pocas filas, para la pantalla de mapeo manual.

    Se usa cuando la detección automática falla: al usuario se le muestra lo que
    hay en el fichero para que diga qué columna es cada cosa.
    """
    texto, codificacion = _decodificar(datos)
    delimitador = _detectar_delimitador(texto)
    todas = [f for f in csv.reader(io.StringIO(texto), delimiter=delimitador) if any(f)]
    indice, mapeo = _localizar_cabecera(todas)
    return {
        "codificacion": codificacion,
        "delimitador": delimitador,
        "fila_cabecera": indice,
        "cabecera": todas[indice] if todas else [],
        "muestra": todas[indice + 1 : indice + 1 + filas],
        "total_filas": max(0, len(todas) - indice - 1),
        "mapeo_detectado": mapeo,
        "campos_que_faltan": mapeo.campos_que_faltan,
    }
