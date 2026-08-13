"""Detección de gasto inusual (F-48).

Marcar una transacción cuyo importe se sale de lo habitual **en esa temática o en
ese comercio**. Como el resto de `app/services/`, son funciones puras sobre
estructuras simples: la API y las alertas dan el mismo número porque llaman aquí.

Por qué la **mediana y la desviación absoluta mediana (MAD)** y no la media y la
desviación típica: la media y la desviación típica se calculan *con* los valores
extremos que precisamente hay que detectar, así que un solo gasto enorme las
infla y tapa el siguiente. Con la compra del televisor de 900 € entre veinte
compras de 40 €, la media sube a 83 € y la desviación típica a 190 €: el
televisor deja de ser inusual (z = 4,3 sin él, z = 0,04 con él) y hace falta un
gasto de 1.000 € para volver a saltar. La mediana y la MAD no se mueven con ese
valor —siguen en 40 € y en unos pocos euros—, que es lo que se espera de una
«referencia de lo habitual». La MAD se escala por 1,4826 para que siga midiendo
en desviaciones típicas y el umbral del hogar (`unusual_expense_sigma`) conserve
su significado.

Los cuatro casos que dejan inútil una detección así, y cómo se resuelven:

1. **Pocas observaciones.** Con dos gastos no existe «lo habitual». Por debajo de
   `MINIMO_OBSERVACIONES` no se emite ningún veredicto: mejor no decir nada que
   inventarse una referencia.
2. **Dispersión cero.** Si los veinte recibos valen exactamente 30 €, la MAD es
   cero y cualquier importe distinto sale a infinitas desviaciones. Se aplica un
   suelo a la dispersión (un porcentaje de la mediana, con un mínimo absoluto),
   así que hace falta separarse de verdad, no un céntimo.
3. **Gastos recurrentes.** El seguro anual de 600 € entre las compras del mes no
   es una anomalía: es un cargo previsto. Nunca se marca, pero **sí** cuenta para
   la referencia, porque es gasto real de esa temática (y la mediana lo aguanta).
4. **Ingresos.** Una nómina no se compara con gastos. Los ingresos quedan fuera
   de la referencia y fuera de los candidatos.

Y dos decisiones más que evitan avisos absurdos:

- Solo se marca **por arriba**. Gastar menos de lo habitual no es una alarma.
- Hay que separarse al menos `DESVIACION_MINIMA` en euros. Un café de 6 € entre
  cafés de 3 € es el 200 %, y avisar de eso es ruido.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from app.services.formato import CERO, cuantizar, euros, numero

#: Escala con la que se publican el z y el «cuántas veces». No son dinero —de ahí
#: que no pasen por `cuantizar()`—, pero el modo de redondeo se fija igualmente:
#: con el del contexto, un z de 2,505 se quedaba en 2,50 y el aviso desaparecía
#: justo en el umbral.
CENTESIMA = Decimal("0.01")

#: Cuántos gastos hacen falta para poder hablar de «lo habitual». Con menos, la
#: mediana es la de una muestra y no la de una costumbre.
MINIMO_OBSERVACIONES = 5

#: Umbral por defecto, el mismo que `households.unusual_expense_sigma`.
SIGMA_POR_DEFECTO = Decimal("2.50")

#: Escala que convierte la MAD en una desviación típica equivalente para una
#: distribución normal (1 / 0,67449). Sin ella, el umbral en «sigmas» del hogar
#: significaría otra cosa según qué estadístico se usara.
FACTOR_MAD = Decimal("1.4826")

#: Suelo de la dispersión, como proporción de la mediana: resuelve la MAD cero.
PISO_RELATIVO = Decimal("0.10")

#: Suelo absoluto de la dispersión, para grupos de importes diminutos.
PISO_ABSOLUTO = Decimal("1.00")

#: Por debajo de esta diferencia en euros no se avisa, por muchas sigmas que dé.
DESVIACION_MINIMA = Decimal("10.00")


class Ambito(StrEnum):
    """Contra qué se compara el importe."""

    TEMATICA = "tematica"
    COMERCIO = "comercio"


@dataclass(frozen=True, slots=True)
class Grupo:
    """El conjunto comparable: una temática o un comercio, con su nombre visible."""

    ambito: Ambito
    clave: str
    nombre: str


@dataclass(frozen=True, slots=True)
class Gasto:
    """Un movimiento ya clasificado. `importe` positivo es gasto."""

    identificador: str
    importe: Decimal
    fecha: date | None = None
    tematica: Grupo | None = None
    comercio: Grupo | None = None
    es_ingreso: bool = False
    es_recurrente: bool = False


@dataclass(frozen=True, slots=True)
class Referencia:
    """Lo habitual en un grupo.

    `mediana` es la referencia que se le enseña al usuario y `dispersion` la que
    divide en el cálculo del z (ya con el suelo aplicado). Se guardan también la
    media y la desviación típica porque van en la carga de la alerta: sirven para
    auditar por qué se avisó, no para decidirlo.
    """

    grupo: Grupo
    observaciones: int
    mediana: Decimal
    mad: Decimal
    dispersion: Decimal
    media: Decimal
    desviacion_tipica: Decimal
    minimo: Decimal
    maximo: Decimal

    @property
    def fiable(self) -> bool:
        return self.observaciones >= MINIMO_OBSERVACIONES


@dataclass(frozen=True, slots=True)
class Anomalia:
    """Un gasto marcado como inusual, con el porqué ya redactado."""

    identificador: str
    importe: Decimal
    referencia: Referencia
    z: Decimal
    veces: Decimal | None
    """Cuántas veces lo habitual. None si la mediana es cero."""
    motivo: str


@dataclass(slots=True)
class _Acumulador:
    grupo: Grupo
    importes: list[Decimal] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Estadística robusta
# --------------------------------------------------------------------------- #


def mediana(valores: Sequence[Decimal]) -> Decimal:
    """El valor central. Con un número par de observaciones, la media de los dos."""
    if not valores:
        return CERO
    ordenados = sorted(valores)
    mitad = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[mitad]
    return (ordenados[mitad - 1] + ordenados[mitad]) / 2


def desviacion_absoluta_mediana(valores: Sequence[Decimal]) -> Decimal:
    """MAD: la mediana de las distancias a la mediana.

    Es el equivalente robusto de la desviación típica. Sin escalar: la escala la
    aplica `referencia_de()`, que es quien decide con qué se compara el umbral.
    """
    if not valores:
        return CERO
    centro = mediana(valores)
    return mediana([abs(valor - centro) for valor in valores])


def media(valores: Sequence[Decimal]) -> Decimal:
    if not valores:
        return CERO
    return sum(valores, CERO) / Decimal(len(valores))


def desviacion_tipica(valores: Sequence[Decimal]) -> Decimal:
    """Desviación típica poblacional. Solo informativa: no decide nada (ver módulo)."""
    if len(valores) < 2:
        return CERO
    centro = media(valores)
    varianza = sum(((valor - centro) ** 2 for valor in valores), CERO) / Decimal(len(valores))
    return varianza.sqrt()


def referencia_de(grupo: Grupo, importes: Sequence[Decimal]) -> Referencia:
    """Resume lo habitual en un grupo. No filtra nada: eso lo hace `referencias()`."""
    centro = mediana(importes)
    mad = desviacion_absoluta_mediana(importes)
    robusta = mad * FACTOR_MAD
    # El suelo resuelve el caso 2 (dispersión cero) y de paso los grupos
    # sospechosamente compactos: con veinte recibos idénticos de 30 €, la
    # dispersión pasa de 0 € a 3 €, así que hace falta separarse de verdad.
    piso = max(centro * PISO_RELATIVO, PISO_ABSOLUTO)
    return Referencia(
        grupo=grupo,
        observaciones=len(importes),
        mediana=cuantizar(centro),
        mad=cuantizar(mad),
        dispersion=max(robusta, piso),
        media=cuantizar(media(importes)),
        desviacion_tipica=cuantizar(desviacion_tipica(importes)),
        minimo=cuantizar(min(importes)) if importes else CERO,
        maximo=cuantizar(max(importes)) if importes else CERO,
    )


# --------------------------------------------------------------------------- #
# Referencias de un historial
# --------------------------------------------------------------------------- #


def _cuenta_para_la_referencia(gasto: Gasto) -> bool:
    """Un ingreso no es gasto y un importe nulo o negativo (una devolución) tampoco.

    Los recurrentes sí entran: son gasto real de la temática y la mediana los
    aguanta sin desplazarse (caso 3).
    """
    return not gasto.es_ingreso and gasto.importe > 0


def referencias(gastos: Iterable[Gasto]) -> dict[tuple[Ambito, str], Referencia]:
    """Lo habitual por temática y por comercio, a partir de todo el historial."""
    acumuladores: dict[tuple[Ambito, str], _Acumulador] = {}
    for gasto in gastos:
        if not _cuenta_para_la_referencia(gasto):
            continue
        for grupo in (gasto.tematica, gasto.comercio):
            if grupo is None:
                continue
            clave = (grupo.ambito, grupo.clave)
            acumulador = acumuladores.get(clave)
            if acumulador is None:
                acumulador = acumuladores[clave] = _Acumulador(grupo)
            acumulador.importes.append(gasto.importe)
    return {
        clave: referencia_de(acumulador.grupo, acumulador.importes)
        for clave, acumulador in acumuladores.items()
    }


def referencia_aplicable(
    gasto: Gasto,
    catalogo: dict[tuple[Ambito, str], Referencia],
    *,
    minimo_observaciones: int = MINIMO_OBSERVACIONES,
) -> Referencia | None:
    """La referencia con la que hay que juzgar este gasto, o None si no hay ninguna.

    Gana la **más específica**: el comercio antes que la temática. No es solo que
    «180 € en Mercadona cuando allí sueles dejarte 45 €» se entienda mejor; es que
    evita el falso positivo grande. En Hogar la mediana puede ser de 30 €, pero si
    en esa tienda de muebles siempre te dejas 300 €, la compra de 300 € no tiene
    nada de inusual. Quedarse con el z más alto de los dos sería justo elegir
    siempre la comparación que más avisa.
    """
    for grupo in (gasto.comercio, gasto.tematica):
        if grupo is None:
            continue
        referencia = catalogo.get((grupo.ambito, grupo.clave))
        if referencia is not None and referencia.observaciones >= minimo_observaciones:
            return referencia
    return None


# --------------------------------------------------------------------------- #
# El veredicto y su explicación
# --------------------------------------------------------------------------- #


def explicar(importe: Decimal, referencia: Referencia) -> str:
    """El porqué en español: «suele rondar los 45,00 € y esta vez han sido 180,00 €».

    Marcar sin explicar no sirve de nada: el usuario tiene que poder decidir si el
    aviso es un error suyo, un error del comercio o un gasto que sí quería hacer.
    """
    cabeza = (
        f"En {referencia.grupo.nombre} el gasto suele rondar los {euros(referencia.mediana)} "
        f"y esta vez han sido {euros(importe)}"
    )
    if referencia.mediana > 0:
        veces = importe / referencia.mediana
        if veces >= 2:
            cola = f"{numero(veces, 1)} veces lo habitual"
        else:
            cola = f"{euros(importe - referencia.mediana)} más de lo habitual"
    else:
        cola = f"{euros(importe)} más de lo habitual"
    # Se dan las dos cifras a propósito: la mediana es con la que se ha decidido y
    # la media es la que el usuario espera ver, así que si se separan mucho ya sabe
    # que en ese grupo hay algún gasto extremo más.
    return (
        f"{cabeza}: {cola}. "
        f"La referencia son {referencia.observaciones} gastos anteriores, "
        f"con una media de {euros(referencia.media)} y un máximo de "
        f"{euros(referencia.maximo)}."
    )


def evaluar(
    gasto: Gasto,
    catalogo: dict[tuple[Ambito, str], Referencia],
    *,
    sigma: Decimal = SIGMA_POR_DEFECTO,
    minimo_observaciones: int = MINIMO_OBSERVACIONES,
    desviacion_minima: Decimal = DESVIACION_MINIMA,
) -> Anomalia | None:
    """¿Es inusual este gasto? None cuando no lo es o cuando no se puede saber."""
    if gasto.es_ingreso or gasto.importe <= 0:
        return None
    if gasto.es_recurrente:
        # Caso 3: un cargo previsto no sorprende a nadie.
        return None

    referencia = referencia_aplicable(gasto, catalogo, minimo_observaciones=minimo_observaciones)
    if referencia is None or referencia.dispersion <= 0:
        return None

    exceso = gasto.importe - referencia.mediana
    # Solo por arriba, y con una diferencia que se note en el bolsillo.
    if exceso < desviacion_minima:
        return None

    z = exceso / referencia.dispersion
    if z < sigma:
        return None

    veces = gasto.importe / referencia.mediana if referencia.mediana > 0 else None
    return Anomalia(
        identificador=gasto.identificador,
        importe=cuantizar(gasto.importe),
        referencia=referencia,
        z=z.quantize(CENTESIMA, rounding=ROUND_HALF_UP),
        veces=(veces.quantize(CENTESIMA, rounding=ROUND_HALF_UP) if veces is not None else None),
        motivo=explicar(gasto.importe, referencia),
    )


def detectar(
    historial: Sequence[Gasto],
    *,
    candidatos: Sequence[Gasto] | None = None,
    sigma: Decimal = SIGMA_POR_DEFECTO,
    minimo_observaciones: int = MINIMO_OBSERVACIONES,
    desviacion_minima: Decimal = DESVIACION_MINIMA,
) -> list[Anomalia]:
    """Punto de entrada: referencia con `historial` y veredicto sobre `candidatos`.

    `historial` es todo lo que se sabe del hogar (la referencia) y `candidatos`
    los gastos del periodo que se está mirando; si no se pasan, se juzga todo el
    historial. El candidato entra en su propia referencia a propósito: quitarlo
    haría el cálculo distinto para cada fila y con la mediana no cambia el
    veredicto —desplaza el centro una posición como mucho—.

    Salen ordenadas de más rara a menos, que es el orden en el que interesan.
    """
    catalogo = referencias(historial)
    anomalias = [
        anomalia
        for gasto in (historial if candidatos is None else candidatos)
        if (
            anomalia := evaluar(
                gasto,
                catalogo,
                sigma=sigma,
                minimo_observaciones=minimo_observaciones,
                desviacion_minima=desviacion_minima,
            )
        )
        is not None
    ]
    anomalias.sort(key=lambda una: (-una.z, -una.importe, una.identificador))
    return anomalias


def por_ambito(anomalias: Iterable[Anomalia]) -> dict[Ambito, list[Anomalia]]:
    """Agrupa por el ámbito con el que se decidió, para el resumen periódico."""
    salida: dict[Ambito, list[Anomalia]] = defaultdict(list)
    for anomalia in anomalias:
        salida[anomalia.referencia.grupo.ambito].append(anomalia)
    return dict(salida)
