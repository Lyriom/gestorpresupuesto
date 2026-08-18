"""Cálculo de la barra de presupuesto del periodo.

Es el corazón de la pantalla principal: los ingresos del periodo se reparten
entre temáticas y la barra muestra cuánto se ha asignado, cuánto se ha gastado y
cuánto queda sin repartir. Todo el cálculo vive aquí, en funciones puras, para
que la API y los informes den siempre el mismo número.

Un periodo es un mes (`2026-08`) o una semana (`2026-W33`). La aritmética de los
dos vive en este módulo y en ningún otro sitio: `inicio_de()`, `fin_de()`,
`periodo_anterior()` y `periodo_siguiente()` son las que saben si hay que sumar
un mes o siete días, y todo lo demás —la barra, el arrastre, los routers— trabaja
con las fechas que devuelven sin volver a mirar la forma de la cadena.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.services.formato import CENTIMO, cuantizar, dinero

CERO = Decimal("0.00")

PATRON_MES = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

#: Las semanas van de la 01 a la 53 porque hay años ISO de 53 semanas. Que el año
#: concreto tenga la que se pide lo comprueba `inicio_de()` con el calendario, que
#: es quien lo sabe de verdad; la expresión regular solo descarta lo imposible.
PATRON_SEMANA = re.compile(r"^(\d{4})-W(0[1-9]|[1-4]\d|5[0-3])$")


class Granularidad(StrEnum):
    """De cuánto en cuánto se presupuesta.

    La semana es **la semana ISO, de lunes a domingo**, y no una semana que empiece
    el día que diga `first_day_of_week`. Es la que entiende `date.fromisocalendar()`,
    la que devuelve `date_trunc('week', …)` de PostgreSQL —donde vive la restricción
    que garantiza que un periodo semanal empieza en lunes— y la que ya usaba el
    informe de flujo de caja para agrupar por semanas. Con una sola definición los
    tres coinciden sin convertir nada; con dos, el presupuesto de una semana y el
    gasto de esa misma semana podrían no cuadrar por un día.
    """

    MES = "month"
    SEMANA = "week"


class EstadoSegmento(StrEnum):
    """Situación de una temática dentro de la barra."""

    SIN_GASTO = "sin_gasto"
    EN_MARGEN = "en_margen"
    """Va bien: ha gastado menos del 80 % de lo asignado."""
    AJUSTADO = "ajustado"
    """Ha gastado entre el 80 % y el 100 %: conviene vigilarlo."""
    AGOTADO = "agotado"
    """Ha gastado justo lo asignado."""
    SOBREPASADO = "sobrepasado"
    """Se ha pasado de lo asignado."""
    SIN_ASIGNAR = "sin_asignar"
    """Hay gasto pero no se asignó presupuesto."""


class ErrorPresupuesto(Exception):
    """La operación sobre el presupuesto no es válida."""


def granularidad_de(periodo: str) -> Granularidad:
    """Qué clase de periodo es, deducido de su forma.

    La granularidad no se pasa por parámetro a todas partes: va dentro de la propia
    cadena. Así un `2026-W33` guardado hace meses sigue significando una semana
    aunque el hogar haya vuelto a presupuestar por meses, y ninguna consulta tiene
    que acordarse de mirar un ajuste para interpretar lo que ya está guardado.
    """
    if PATRON_MES.match(periodo or ""):
        return Granularidad.MES
    if PATRON_SEMANA.match(periodo or ""):
        return Granularidad.SEMANA
    raise ErrorPresupuesto(
        f"El periodo '{periodo}' no es válido. Debe tener el formato AAAA-MM "
        f"para un mes o AAAA-Wss para una semana."
    )


def inicio_de(periodo: str) -> date:
    """El primer día del periodo: el 1 del mes o el lunes de la semana."""
    if granularidad_de(periodo) is Granularidad.MES:
        anyo, mes = (int(parte) for parte in periodo.split("-"))
        return date(anyo, mes, 1)
    anyo, semana = (int(parte) for parte in periodo.split("-W"))
    try:
        return date.fromisocalendar(anyo, semana, 1)
    except ValueError as exc:
        raise ErrorPresupuesto(
            f"El periodo '{periodo}' no existe: {anyo} no tiene semana {semana}."
        ) from exc


def fin_de(periodo: str) -> date:
    """El último día del periodo, incluido."""
    inicio = inicio_de(periodo)
    if granularidad_de(periodo) is Granularidad.MES:
        return date(inicio.year, inicio.month, calendar.monthrange(inicio.year, inicio.month)[1])
    return inicio + timedelta(days=6)


def rango_de(periodo: str) -> tuple[date, date]:
    """Primer y último día del periodo, ambos incluidos."""
    return inicio_de(periodo), fin_de(periodo)


def dias_de(periodo: str) -> int:
    inicio, fin = rango_de(periodo)
    return (fin - inicio).days + 1


def periodo_de(fecha: date, granularidad: Granularidad = Granularidad.MES) -> str:
    """El periodo al que pertenece una fecha.

    El año de una semana ISO es el suyo, no el del calendario: el 31 de diciembre
    de 2025 cae en la primera semana de 2026, así que devuelve `2026-W01`. Sale de
    `isocalendar()`, que ya lo resuelve.
    """
    if granularidad is Granularidad.MES:
        return f"{fecha.year:04d}-{fecha.month:02d}"
    anyo, semana, _ = fecha.isocalendar()
    return f"{anyo:04d}-W{semana:02d}"


def validar_periodo(periodo: str) -> str:
    """Comprueba que el periodo exista, no solo que tenga la forma buena."""
    inicio_de(periodo)
    return periodo


def periodo_anterior(periodo: str) -> str:
    granularidad = granularidad_de(periodo)
    if granularidad is Granularidad.SEMANA:
        return periodo_de(inicio_de(periodo) - timedelta(days=7), granularidad)
    anyo, mes = (int(parte) for parte in periodo.split("-"))
    return f"{anyo - 1}-12" if mes == 1 else f"{anyo}-{mes - 1:02d}"


def periodo_siguiente(periodo: str) -> str:
    granularidad = granularidad_de(periodo)
    if granularidad is Granularidad.SEMANA:
        return periodo_de(fin_de(periodo) + timedelta(days=1), granularidad)
    anyo, mes = (int(parte) for parte in periodo.split("-"))
    return f"{anyo + 1}-01" if mes == 12 else f"{anyo}-{mes + 1:02d}"


def _dinero(valor: Decimal | int | float | str | None) -> Decimal:
    """Normaliza cualquier entrada a un importe con dos decimales.

    El redondeo lo decide `formato.cuantizar()`, que es el único sitio del
    proyecto donde vive el modo del dinero.
    """
    if valor is None:
        return CERO
    if not isinstance(valor, Decimal):
        valor = Decimal(str(valor))
    return cuantizar(valor)


@dataclass(slots=True)
class EntradaCategoria:
    """Lo que se sabe de una temática en un periodo, antes de calcular la barra."""

    categoria_id: str
    nombre: str
    color: str | None = None
    icono: str | None = None
    categoria_padre_id: str | None = None
    asignado: Decimal = CERO
    gastado: Decimal = CERO
    arrastrado: Decimal = CERO
    """Sobrante del mes anterior traspasado a este (rollover)."""
    permite_arrastre: bool = False


@dataclass(slots=True)
class SegmentoBarra:
    """Una temática ya calculada, lista para dibujar en la barra."""

    categoria_id: str
    nombre: str
    color: str | None
    icono: str | None
    categoria_padre_id: str | None
    asignado: Decimal
    gastado: Decimal
    arrastrado: Decimal
    disponible: Decimal
    """Lo que queda por gastar: asignado + arrastrado - gastado."""
    porcentaje_consumido: Decimal
    """De 0 a 100 sobre lo asignado; puede pasar de 100 si hay sobrepaso."""
    porcentaje_de_la_barra: Decimal
    """Anchura del segmento sobre el total de la barra."""
    estado: EstadoSegmento
    sobrepaso: Decimal
    """Cuánto se ha pasado de lo asignado. Cero si no se ha pasado."""

    @property
    def presupuesto_efectivo(self) -> Decimal:
        return self.asignado + self.arrastrado


@dataclass(slots=True)
class BarraPresupuesto:
    """Todo lo que la pantalla principal necesita para dibujar el mes."""

    periodo: str
    ingresos: Decimal
    total_asignado: Decimal
    total_gastado: Decimal
    total_arrastrado: Decimal
    sin_asignar: Decimal
    """Ingresos menos lo asignado. Negativo si se ha repartido más de lo que entra."""
    disponible: Decimal
    """Ingresos más arrastres menos gastado."""
    porcentaje_asignado: Decimal
    porcentaje_gastado: Decimal
    segmentos: list[SegmentoBarra] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def sobreasignado(self) -> bool:
        """Se ha repartido más dinero del que hay."""
        return self.sin_asignar < CERO

    @property
    def categorias_sobrepasadas(self) -> list[SegmentoBarra]:
        return [s for s in self.segmentos if s.estado is EstadoSegmento.SOBREPASADO]


def _estado_de(efectivo: Decimal, gastado: Decimal, disponible: Decimal) -> EstadoSegmento:
    """Clasifica una temática. `efectivo` es lo asignado más lo arrastrado.

    El umbral de aviso se mide sobre el presupuesto efectivo: una temática con
    100 € asignados y 200 € arrastrados que ha gastado 150 € va sobrada, no
    ajustada.
    """
    if efectivo == CERO:
        return EstadoSegmento.SIN_ASIGNAR if gastado > CERO else EstadoSegmento.SIN_GASTO
    if gastado == CERO:
        return EstadoSegmento.SIN_GASTO
    if disponible < CERO:
        return EstadoSegmento.SOBREPASADO
    if disponible == CERO:
        return EstadoSegmento.AGOTADO
    if gastado / efectivo >= Decimal("0.8"):
        return EstadoSegmento.AJUSTADO
    return EstadoSegmento.EN_MARGEN


def _porcentaje(parte: Decimal, total: Decimal) -> Decimal:
    """Qué parte del total se ha consumido, de 0 en adelante.

    Nunca baja de cero, y no por pudor con los números: si en el mes hay más
    devoluciones que compras en una temática —se compró un abrigo en julio y se
    devolvió en agosto— lo gastado sale negativo, que es la verdad y así se
    enseña. Pero el segmento de la barra se dibuja con este porcentaje, y una
    anchura negativa no significa nada. El importe conserva el signo; el trozo
    pintado se queda en vacío.
    """
    if total <= CERO:
        return CERO
    # No es dinero, así que no pasa por `cuantizar()`; el modo se fija aquí porque
    # el porcentaje se enseña al usuario y el empate tiene que subir.
    porcentaje = (parte / total * 100).quantize(CENTIMO, rounding=ROUND_HALF_UP)
    return max(porcentaje, CERO)


def calcular_barra(
    periodo: str,
    ingresos: Decimal | int | float | str,
    entradas: list[EntradaCategoria],
) -> BarraPresupuesto:
    """Construye la barra del mes a partir de los ingresos y las temáticas.

    La anchura de cada segmento se calcula sobre el mayor entre los ingresos y
    lo asignado: si el usuario reparte más de lo que ingresa, la barra sigue
    sumando el 100 % y el exceso se ve como sobreasignación en vez de
    desbordar el contenedor.
    """
    validar_periodo(periodo)
    ingresos_dec = _dinero(ingresos)

    total_asignado = sum((_dinero(e.asignado) for e in entradas), CERO)
    total_gastado = sum((_dinero(e.gastado) for e in entradas), CERO)
    total_arrastrado = sum(
        (_dinero(e.arrastrado) for e in entradas if e.permite_arrastre),
        CERO,
    )

    base_barra = max(ingresos_dec, total_asignado)

    segmentos: list[SegmentoBarra] = []
    for entrada in entradas:
        asignado = _dinero(entrada.asignado)
        gastado = _dinero(entrada.gastado)
        arrastrado = _dinero(entrada.arrastrado) if entrada.permite_arrastre else CERO
        disponible = asignado + arrastrado - gastado
        sobrepaso = -disponible if disponible < CERO else CERO

        segmentos.append(
            SegmentoBarra(
                categoria_id=entrada.categoria_id,
                nombre=entrada.nombre,
                color=entrada.color,
                icono=entrada.icono,
                categoria_padre_id=entrada.categoria_padre_id,
                asignado=asignado,
                gastado=gastado,
                arrastrado=arrastrado,
                disponible=disponible,
                porcentaje_consumido=_porcentaje(gastado, asignado + arrastrado),
                porcentaje_de_la_barra=_porcentaje(asignado, base_barra),
                estado=_estado_de(asignado + arrastrado, gastado, disponible),
                sobrepaso=sobrepaso,
            )
        )

    # Se ordenan de mayor a menor asignación: la barra se lee de izquierda a
    # derecha y lo importante va primero.
    segmentos.sort(key=lambda s: (-s.asignado, s.nombre))

    sin_asignar = ingresos_dec - total_asignado
    barra = BarraPresupuesto(
        periodo=periodo,
        ingresos=ingresos_dec,
        total_asignado=total_asignado,
        total_gastado=total_gastado,
        total_arrastrado=total_arrastrado,
        sin_asignar=sin_asignar,
        disponible=ingresos_dec + total_arrastrado - total_gastado,
        porcentaje_asignado=_porcentaje(total_asignado, ingresos_dec),
        porcentaje_gastado=_porcentaje(total_gastado, base_barra),
        segmentos=segmentos,
    )

    if ingresos_dec == CERO:
        barra.avisos.append(
            "No has registrado ingresos este mes: añade tu nómina o ingresos para "
            "poder repartir el presupuesto."
        )
    elif sin_asignar < CERO:
        barra.avisos.append(
            f"Has repartido {dinero(-sin_asignar)} más de lo que has ingresado este mes."
        )

    sobrepasadas = barra.categorias_sobrepasadas
    if sobrepasadas:
        if len(sobrepasadas) == 1:
            barra.avisos.append(
                f"Te has pasado {dinero(sobrepasadas[0].sobrepaso)} en {sobrepasadas[0].nombre}."
            )
        else:
            total = sum((s.sobrepaso for s in sobrepasadas), CERO)
            barra.avisos.append(
                f"Te has pasado del presupuesto en {len(sobrepasadas)} temáticas "
                f"({dinero(total)} en total)."
            )

    sin_presupuesto = [s for s in segmentos if s.estado is EstadoSegmento.SIN_ASIGNAR]
    if sin_presupuesto:
        nombres = ", ".join(s.nombre for s in sin_presupuesto[:3])
        resto = "" if len(sin_presupuesto) <= 3 else f" y {len(sin_presupuesto) - 3} más"
        barra.avisos.append(f"Hay gasto sin presupuesto asignado en: {nombres}{resto}.")

    return barra


def validar_asignacion(importe: Decimal | int | float | str) -> Decimal:
    """Una asignación de presupuesto no puede ser negativa."""
    valor = _dinero(importe)
    if valor < CERO:
        raise ErrorPresupuesto("El presupuesto asignado a una temática no puede ser negativo.")
    return valor


@dataclass(slots=True)
class Reasignacion:
    """Resultado de mover presupuesto de una temática a otra."""

    origen_id: str
    destino_id: str
    importe: Decimal
    asignado_origen: Decimal
    asignado_destino: Decimal


def reasignar(
    origen_id: str,
    asignado_origen: Decimal | int | float | str,
    destino_id: str,
    asignado_destino: Decimal | int | float | str,
    importe: Decimal | int | float | str,
    *,
    gastado_origen: Decimal | int | float | str = CERO,
) -> Reasignacion:
    """Mueve presupuesto de una temática a otra sin cambiar el total repartido.

    Es lo que ocurre cuando el usuario arrastra un tramo de la barra de una
    temática a otra. No se permite dejar una temática con menos presupuesto del
    que ya ha gastado: eso la dejaría en sobrepaso artificial.
    """
    if origen_id == destino_id:
        raise ErrorPresupuesto("El origen y el destino no pueden ser la misma temática.")

    cantidad = _dinero(importe)
    if cantidad <= CERO:
        raise ErrorPresupuesto("El importe a mover tiene que ser mayor que cero.")

    origen = _dinero(asignado_origen)
    destino = _dinero(asignado_destino)
    gastado = _dinero(gastado_origen)

    if cantidad > origen:
        raise ErrorPresupuesto(
            f"No puedes mover {cantidad} €: la temática de origen solo tiene {origen} € asignados."
        )

    restante = origen - cantidad
    if restante < gastado:
        disponible = origen - gastado
        raise ErrorPresupuesto(
            f"Solo puedes mover {disponible} €: en la temática de origen ya se han "
            f"gastado {gastado} €."
        )

    return Reasignacion(
        origen_id=origen_id,
        destino_id=destino_id,
        importe=cantidad,
        asignado_origen=restante,
        asignado_destino=destino + cantidad,
    )


def calcular_arrastre(
    asignado: Decimal | int | float | str,
    gastado: Decimal | int | float | str,
    arrastrado_previo: Decimal | int | float | str = CERO,
    *,
    permite_arrastre: bool,
    arrastrar_deuda: bool = True,
) -> Decimal:
    """Sobrante (o déficit) que pasa al mes siguiente.

    Si la temática no permite arrastre, el sobrante se pierde y el mes empieza
    de cero, que es el comportamiento clásico de presupuesto mensual. Si lo
    permite, el sobrante se acumula; y cuando `arrastrar_deuda` está activo, un
    sobrepaso también se arrastra en negativo, como hace YNAB.
    """
    if not permite_arrastre:
        return CERO
    saldo = _dinero(asignado) + _dinero(arrastrado_previo) - _dinero(gastado)
    if saldo < CERO and not arrastrar_deuda:
        return CERO
    return saldo


def reparto_sugerido(
    ingresos: Decimal | int | float | str,
    gasto_medio_por_categoria: dict[str, Decimal],
) -> dict[str, Decimal]:
    """Propone un reparto del mes según lo que se gastó de media en cada temática.

    Se usa en el onboarding y cuando el usuario pide "repartir como el mes
    pasado". Si la media histórica supera los ingresos, se escala todo de forma
    proporcional para no proponer un presupuesto imposible. El ajuste del
    redondeo se acumula en la temática con más peso, de modo que la suma cuadre
    exactamente con los ingresos.
    """
    ingresos_dec = _dinero(ingresos)
    total_medio = sum((_dinero(v) for v in gasto_medio_por_categoria.values()), CERO)
    if total_medio <= CERO or ingresos_dec <= CERO:
        return dict.fromkeys(gasto_medio_por_categoria, CERO)

    factor = min(Decimal(1), ingresos_dec / total_medio)
    propuesta = {
        clave: _dinero(_dinero(valor) * factor)
        for clave, valor in gasto_medio_por_categoria.items()
    }

    # Corrección del redondeo para que la suma no se desvíe por céntimos.
    if factor < 1:
        desviacion = ingresos_dec - sum(propuesta.values(), CERO)
        if desviacion != CERO and propuesta:
            mayor = max(propuesta, key=lambda c: propuesta[c])
            propuesta[mayor] = _dinero(propuesta[mayor] + desviacion)
    return propuesta
