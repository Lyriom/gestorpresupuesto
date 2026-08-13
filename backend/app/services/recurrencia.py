"""Reglas de repetición para gastos e ingresos recurrentes.

Cubre lo que hace falta en un gestor doméstico —alquiler el día 1, nómina el
último día laborable, seguro cada seis meses, Netflix cada mes— sin montar un
motor de RRULE completo, que sería mucho más código para casos que aquí no se
dan.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from dateutil.relativedelta import relativedelta


class Frecuencia(StrEnum):
    DIARIA = "diaria"
    SEMANAL = "semanal"
    QUINCENAL = "quincenal"
    MENSUAL = "mensual"
    BIMESTRAL = "bimestral"
    TRIMESTRAL = "trimestral"
    SEMESTRAL = "semestral"
    ANUAL = "anual"


# Meses que suma cada frecuencia; las que no son mensuales van aparte.
_MESES_POR_FRECUENCIA = {
    Frecuencia.MENSUAL: 1,
    Frecuencia.BIMESTRAL: 2,
    Frecuencia.TRIMESTRAL: 3,
    Frecuencia.SEMESTRAL: 6,
    Frecuencia.ANUAL: 12,
}

_DIAS_POR_FRECUENCIA = {
    Frecuencia.DIARIA: 1,
    Frecuencia.SEMANAL: 7,
    Frecuencia.QUINCENAL: 14,
}

NOMBRES_FRECUENCIA = {
    Frecuencia.DIARIA: "cada día",
    Frecuencia.SEMANAL: "cada semana",
    Frecuencia.QUINCENAL: "cada dos semanas",
    Frecuencia.MENSUAL: "cada mes",
    Frecuencia.BIMESTRAL: "cada dos meses",
    Frecuencia.TRIMESTRAL: "cada trimestre",
    Frecuencia.SEMESTRAL: "cada seis meses",
    Frecuencia.ANUAL: "cada año",
}


class ErrorRecurrencia(Exception):
    """La regla de repetición no es válida."""


@dataclass(slots=True)
class ReglaRepeticion:
    """Cada cuánto se repite un movimiento y hasta cuándo.

    `dia_del_mes` con valor -1 significa "último día del mes", que es lo que
    hace falta para las nóminas. Si el mes no tiene ese día (un 31 en febrero),
    se usa el último día disponible en vez de saltarse la repetición.
    """

    frecuencia: Frecuencia
    intervalo: int = 1
    """Multiplicador: intervalo 2 con frecuencia mensual es cada dos meses."""
    dia_del_mes: int | None = None
    dia_de_la_semana: int | None = None
    """0 = lunes ... 6 = domingo. Solo para frecuencias semanales."""
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    repeticiones_max: int | None = None
    solo_dias_laborables: bool = False
    """Si cae en sábado o domingo, se adelanta al viernes anterior."""

    def __post_init__(self) -> None:
        if self.intervalo < 1:
            raise ErrorRecurrencia("El intervalo tiene que ser al menos 1.")
        if self.dia_del_mes is not None and not (
            self.dia_del_mes == -1 or 1 <= self.dia_del_mes <= 31
        ):
            raise ErrorRecurrencia(
                "El día del mes debe estar entre 1 y 31, o ser -1 para el último."
            )
        if self.dia_de_la_semana is not None and not 0 <= self.dia_de_la_semana <= 6:
            raise ErrorRecurrencia("El día de la semana debe estar entre 0 (lunes) y 6 (domingo).")
        if self.fecha_fin and self.fecha_inicio and self.fecha_fin < self.fecha_inicio:
            raise ErrorRecurrencia("La fecha de fin no puede ser anterior a la de inicio.")
        if self.repeticiones_max is not None and self.repeticiones_max < 1:
            raise ErrorRecurrencia("El número de repeticiones tiene que ser al menos 1.")

    @property
    def descripcion(self) -> str:
        """Texto legible de la regla, para mostrar en la interfaz."""
        base = NOMBRES_FRECUENCIA[self.frecuencia]
        if self.intervalo > 1:
            unidad = {
                Frecuencia.DIARIA: "días",
                Frecuencia.SEMANAL: "semanas",
                Frecuencia.QUINCENAL: "quincenas",
                Frecuencia.MENSUAL: "meses",
                Frecuencia.BIMESTRAL: "bimestres",
                Frecuencia.TRIMESTRAL: "trimestres",
                Frecuencia.SEMESTRAL: "semestres",
                Frecuencia.ANUAL: "años",
            }[self.frecuencia]
            base = f"cada {self.intervalo} {unidad}"

        if self.dia_del_mes == -1:
            base += ", el último día del mes"
        elif self.dia_del_mes is not None:
            base += f", el día {self.dia_del_mes}"

        if self.solo_dias_laborables:
            base += " (adelantado si cae en fin de semana)"
        return base


def _ajustar_dia(referencia: date, dia: int) -> date:
    """Coloca la fecha en el día pedido del mes de `referencia`.

    Si el mes no llega a ese día (31 de febrero), se usa el último día del mes.
    """
    ultimo = calendar.monthrange(referencia.year, referencia.month)[1]
    if dia == -1:
        return referencia.replace(day=ultimo)
    return referencia.replace(day=min(dia, ultimo))


def _a_dia_laborable(fecha: date) -> date:
    """Adelanta al viernes si la fecha cae en sábado o domingo."""
    if fecha.weekday() == 5:  # sábado
        return fecha - timedelta(days=1)
    if fecha.weekday() == 6:  # domingo
        return fecha - timedelta(days=2)
    return fecha


def siguiente_fecha(regla: ReglaRepeticion, desde: date) -> date | None:
    """Primera fecha de la regla estrictamente posterior a `desde`.

    Devuelve None si la regla ya ha terminado.
    """
    inicio = regla.fecha_inicio or desde
    if regla.fecha_fin and desde >= regla.fecha_fin:
        return None

    if regla.frecuencia in _DIAS_POR_FRECUENCIA:
        paso = timedelta(days=_DIAS_POR_FRECUENCIA[regla.frecuencia] * regla.intervalo)
        candidato = inicio
        # Se avanza desde el inicio para no perder el anclaje de la serie.
        while candidato <= desde:
            candidato += paso
    else:
        meses = _MESES_POR_FRECUENCIA[regla.frecuencia] * regla.intervalo
        candidato = inicio
        if regla.dia_del_mes is not None:
            candidato = _ajustar_dia(candidato, regla.dia_del_mes)
        while candidato <= desde:
            candidato = candidato + relativedelta(months=meses)
            if regla.dia_del_mes is not None:
                candidato = _ajustar_dia(candidato, regla.dia_del_mes)

    if regla.solo_dias_laborables:
        ajustada = _a_dia_laborable(candidato)
        # El ajuste puede dejar la fecha en el pasado: en ese caso se salta a la
        # siguiente repetición.
        if ajustada <= desde:
            return siguiente_fecha(regla, candidato)
        candidato = ajustada

    if regla.fecha_fin and candidato > regla.fecha_fin:
        return None
    return candidato


def generar_fechas(
    regla: ReglaRepeticion,
    desde: date,
    hasta: date,
    *,
    limite: int = 200,
) -> list[date]:
    """Todas las ocurrencias de la regla en el intervalo (desde, hasta].

    El límite evita que una regla diaria con un rango de años genere miles de
    fechas por un descuido en la interfaz.
    """
    if hasta < desde:
        return []

    fechas: list[date] = []
    cursor = desde
    while len(fechas) < limite:
        siguiente = siguiente_fecha(regla, cursor)
        if siguiente is None or siguiente > hasta:
            break
        if regla.repeticiones_max is not None and len(fechas) >= regla.repeticiones_max:
            break
        fechas.append(siguiente)
        cursor = siguiente
    return fechas


def proximas_ocurrencias(regla: ReglaRepeticion, hoy: date, cuantas: int = 3) -> list[date]:
    """Las siguientes `cuantas` fechas a partir de hoy, para el panel de avisos."""
    fechas: list[date] = []
    cursor = hoy - timedelta(days=1)  # incluye hoy si toca
    while len(fechas) < cuantas:
        siguiente = siguiente_fecha(regla, cursor)
        if siguiente is None:
            break
        fechas.append(siguiente)
        cursor = siguiente
    return fechas


def dias_hasta(fecha: date, hoy: date) -> int:
    """Días que faltan para una fecha. Negativo si ya ha pasado."""
    return (fecha - hoy).days


def esta_proximo(fecha: date, hoy: date, dias_aviso: int = 3) -> bool:
    """Si toca avisar de un cargo que llega en los próximos días."""
    restantes = dias_hasta(fecha, hoy)
    return 0 <= restantes <= dias_aviso
