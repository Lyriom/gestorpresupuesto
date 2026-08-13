"""Análisis del historial de precios de un producto.

Es la lógica que responde a "¿cuánto ha subido esto?" y "¿dónde me sale más
barato?". Se mantiene como funciones puras sobre estructuras simples para poder
probarla sin base de datos.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

CUATRO_DECIMALES = Decimal("0.0001")
CENTIMO = Decimal("0.01")

# Por debajo de este cambio se considera ruido de redondeo, no una subida.
UMBRAL_RUIDO = Decimal("0.005")  # 0,5 %
# A partir de aquí se genera una alerta para el usuario.
UMBRAL_ALERTA = Decimal("0.05")  # 5 %


class Tendencia(StrEnum):
    SUBE = "sube"
    BAJA = "baja"
    ESTABLE = "estable"
    SIN_DATOS = "sin_datos"


@dataclass(frozen=True, slots=True)
class PuntoPrecio:
    """Un precio unitario observado en una factura concreta."""

    fecha: date
    precio: Decimal
    comercio: str | None = None
    factura_id: str | None = None
    cantidad: Decimal | None = None


@dataclass(slots=True)
class ComparativaComercio:
    """Último precio conocido de un producto en un comercio."""

    comercio: str
    precio: Decimal
    fecha: date
    observaciones: int


@dataclass(slots=True)
class AnalisisPrecio:
    """Resumen del historial de precios de un producto."""

    observaciones: int = 0
    precio_actual: Decimal | None = None
    precio_anterior: Decimal | None = None
    fecha_actual: date | None = None
    variacion_ultima: Decimal | None = None
    """Proporción de cambio respecto a la observación anterior (0,08 = +8 %)."""
    variacion_total: Decimal | None = None
    """Proporción de cambio entre la primera y la última observación."""
    precio_minimo: Decimal | None = None
    precio_maximo: Decimal | None = None
    precio_medio: Decimal | None = None
    fecha_minimo: date | None = None
    fecha_maximo: date | None = None
    tendencia: Tendencia = Tendencia.SIN_DATOS
    hay_alerta: bool = False
    mensaje_alerta: str | None = None
    por_comercio: list[ComparativaComercio] = field(default_factory=list)
    comercio_mas_barato: str | None = None
    ahorro_por_unidad: Decimal | None = None
    """Diferencia entre el precio actual y el más barato encontrado."""


def variacion(anterior: Decimal, actual: Decimal) -> Decimal | None:
    """Proporción de cambio entre dos precios. None si el anterior es cero."""
    if anterior == 0:
        return None
    return ((actual - anterior) / anterior).quantize(CUATRO_DECIMALES)


def _tendencia_de(proporcion: Decimal | None) -> Tendencia:
    if proporcion is None:
        return Tendencia.SIN_DATOS
    if proporcion > UMBRAL_RUIDO:
        return Tendencia.SUBE
    if proporcion < -UMBRAL_RUIDO:
        return Tendencia.BAJA
    return Tendencia.ESTABLE


def analizar_historial(
    puntos: list[PuntoPrecio],
    *,
    umbral_alerta: Decimal = UMBRAL_ALERTA,
) -> AnalisisPrecio:
    """Resume el historial de precios de un producto.

    Los puntos pueden llegar desordenados: se ordenan por fecha. Si en la misma
    fecha hay varias observaciones (dos facturas el mismo día), se conservan
    todas para las estadísticas pero la "actual" es la última de esa fecha.
    """
    analisis = AnalisisPrecio()
    validos = [p for p in puntos if p.precio is not None and p.precio > 0]
    if not validos:
        return analisis

    ordenados = sorted(validos, key=lambda p: p.fecha)
    precios = [p.precio for p in ordenados]

    analisis.observaciones = len(ordenados)
    analisis.precio_actual = ordenados[-1].precio
    analisis.fecha_actual = ordenados[-1].fecha
    analisis.precio_minimo = min(precios)
    analisis.precio_maximo = max(precios)
    analisis.precio_medio = (sum(precios) / len(precios)).quantize(CUATRO_DECIMALES)
    analisis.fecha_minimo = next(p.fecha for p in ordenados if p.precio == analisis.precio_minimo)
    analisis.fecha_maximo = next(p.fecha for p in ordenados if p.precio == analisis.precio_maximo)

    if len(ordenados) >= 2:
        analisis.precio_anterior = ordenados[-2].precio
        analisis.variacion_ultima = variacion(ordenados[-2].precio, ordenados[-1].precio)
        analisis.variacion_total = variacion(ordenados[0].precio, ordenados[-1].precio)
        analisis.tendencia = _tendencia_de(analisis.variacion_ultima)
    else:
        # Con una sola observación no hay nada que comparar todavía.
        analisis.tendencia = Tendencia.SIN_DATOS

    if analisis.variacion_ultima is not None and analisis.variacion_ultima >= umbral_alerta:
        porcentaje = (analisis.variacion_ultima * 100).quantize(CENTIMO)
        analisis.hay_alerta = True
        analisis.mensaje_alerta = (
            f"El precio ha subido un {porcentaje} % respecto a la compra anterior "
            f"({analisis.precio_anterior} € → {analisis.precio_actual} €)."
        )

    analisis.por_comercio = comparar_comercios(ordenados)
    if analisis.por_comercio:
        mas_barato = min(analisis.por_comercio, key=lambda c: c.precio)
        analisis.comercio_mas_barato = mas_barato.comercio
        if analisis.precio_actual is not None and mas_barato.precio < analisis.precio_actual:
            analisis.ahorro_por_unidad = (analisis.precio_actual - mas_barato.precio).quantize(
                CUATRO_DECIMALES
            )

    return analisis


def comparar_comercios(puntos: list[PuntoPrecio]) -> list[ComparativaComercio]:
    """Último precio por comercio, ordenado de más barato a más caro.

    Se usa el último precio de cada comercio y no la media: para decidir dónde
    comprar hoy, lo que importa es lo que cuesta ahora en cada sitio.
    """
    por_comercio: dict[str, list[PuntoPrecio]] = defaultdict(list)
    for punto in puntos:
        if punto.comercio:
            por_comercio[punto.comercio].append(punto)

    comparativas = []
    for comercio, observaciones in por_comercio.items():
        ultima = max(observaciones, key=lambda p: p.fecha)
        comparativas.append(
            ComparativaComercio(
                comercio=comercio,
                precio=ultima.precio,
                fecha=ultima.fecha,
                observaciones=len(observaciones),
            )
        )
    return sorted(comparativas, key=lambda c: c.precio)


@dataclass(slots=True)
class SubidaDetectada:
    """Una subida de precio que merece avisar al usuario."""

    producto_id: str
    nombre: str
    precio_anterior: Decimal
    precio_actual: Decimal
    proporcion: Decimal
    fecha: date
    comercio: str | None = None

    @property
    def porcentaje(self) -> Decimal:
        return (self.proporcion * 100).quantize(CENTIMO)


def detectar_subidas(
    historiales: dict[str, tuple[str, list[PuntoPrecio]]],
    *,
    umbral: Decimal = UMBRAL_ALERTA,
) -> list[SubidaDetectada]:
    """Recorre varios productos y devuelve los que han subido por encima del umbral.

    `historiales` es un diccionario `producto_id -> (nombre, puntos)`. El
    resultado va ordenado de mayor a menor subida, que es el orden en el que
    interesa mostrarlo.
    """
    subidas: list[SubidaDetectada] = []
    for producto_id, (nombre, puntos) in historiales.items():
        analisis = analizar_historial(puntos, umbral_alerta=umbral)
        if (
            analisis.hay_alerta
            and analisis.precio_anterior is not None
            and analisis.precio_actual is not None
            and analisis.variacion_ultima is not None
        ):
            ultimo = max((p for p in puntos if p.precio > 0), key=lambda p: p.fecha)
            subidas.append(
                SubidaDetectada(
                    producto_id=producto_id,
                    nombre=nombre,
                    precio_anterior=analisis.precio_anterior,
                    precio_actual=analisis.precio_actual,
                    proporcion=analisis.variacion_ultima,
                    fecha=analisis.fecha_actual or ultimo.fecha,
                    comercio=ultimo.comercio,
                )
            )
    return sorted(subidas, key=lambda s: s.proporcion, reverse=True)


@dataclass(slots=True)
class LineaCesta:
    """Un producto de la cesta con su precio en cada comercio."""

    producto_id: str
    nombre: str
    cantidad: Decimal
    precios: dict[str, Decimal]
    """comercio -> precio unitario más reciente conocido."""

    @property
    def comercio_mas_barato(self) -> str | None:
        if not self.precios:
            return None
        return min(self.precios, key=lambda c: self.precios[c])


@dataclass(slots=True)
class ComparativaCesta:
    """Coste total de la misma cesta en cada comercio."""

    totales: dict[str, Decimal]
    lineas: list[LineaCesta]
    incompletos: dict[str, list[str]] = field(default_factory=dict)
    """comercio -> nombres de producto de los que no hay precio ahí."""

    @property
    def mas_barato(self) -> str | None:
        completos = {c: t for c, t in self.totales.items() if not self.incompletos.get(c)}
        candidatos = completos or self.totales
        return min(candidatos, key=lambda c: candidatos[c]) if candidatos else None

    @property
    def ahorro_maximo(self) -> Decimal:
        """Diferencia entre el comercio más caro y el más barato."""
        completos = {c: t for c, t in self.totales.items() if not self.incompletos.get(c)}
        candidatos = completos or self.totales
        if len(candidatos) < 2:
            return Decimal("0.00")
        return (max(candidatos.values()) - min(candidatos.values())).quantize(CENTIMO)


def comparar_cesta(lineas: list[LineaCesta]) -> ComparativaCesta:
    """Calcula cuánto costaría la misma cesta en cada comercio.

    Un comercio del que no se tiene precio de algún producto queda marcado como
    incompleto: su total es más bajo pero no es comparable, así que se avisa en
    vez de dejar que parezca el más barato.
    """
    comercios = {comercio for linea in lineas for comercio in linea.precios}
    totales: dict[str, Decimal] = {}
    incompletos: dict[str, list[str]] = defaultdict(list)

    for comercio in comercios:
        total = Decimal("0.00")
        for linea in lineas:
            precio = linea.precios.get(comercio)
            if precio is None:
                incompletos[comercio].append(linea.nombre)
                continue
            total += precio * linea.cantidad
        totales[comercio] = total.quantize(CENTIMO)

    return ComparativaCesta(totales=totales, lineas=lineas, incompletos=dict(incompletos))


def inflacion_personal(
    historiales: list[list[PuntoPrecio]],
    desde: date,
    hasta: date,
) -> Decimal | None:
    """Variación media de precio de los productos del usuario entre dos fechas.

    Es la "inflación personal": no la del INE, sino la de la cesta real de esta
    persona. Solo cuentan los productos con al menos una observación antes de
    `desde` y otra después, para no comparar cosas distintas.
    """
    variaciones: list[Decimal] = []
    for puntos in historiales:
        validos = [p for p in puntos if p.precio > 0]
        antiguos = [p for p in validos if p.fecha <= desde]
        recientes = [p for p in validos if desde < p.fecha <= hasta]
        if not antiguos or not recientes:
            continue
        base = max(antiguos, key=lambda p: p.fecha).precio
        ultimo = max(recientes, key=lambda p: p.fecha).precio
        cambio = variacion(base, ultimo)
        if cambio is not None:
            variaciones.append(cambio)

    if not variaciones:
        return None
    return (sum(variaciones) / len(variaciones)).quantize(CUATRO_DECIMALES)
