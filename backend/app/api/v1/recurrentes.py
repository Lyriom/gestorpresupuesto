"""Recurrentes y suscripciones (§3.8, F-28 a F-30).

El motor de repeticiones es `app/services/recurrencia.py`: aquí no se calcula
ninguna fecha a mano. Cada fila de `recurring_rules` se traduce a una
`ReglaRepeticion` y son `siguiente_fecha()` y `proximas_ocurrencias()` las que
deciden cuándo toca, incluido el caso espinoso del día 31 en febrero (RN-37).

`recurring_rules` guarda a la vez los recurrentes confirmados y las
suscripciones detectadas: solo cambia `origin`. Una detección descartada se
materializa como regla `status = 'ended'` sin `confirmed_at`, que es lo que hace
que no vuelva a proponerse (RN-39) sin necesidad de otra tabla.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, verificar_csrf
from app.api.v1.transacciones import (
    ajustar_uso_comercio,
    contar,
    cuenta_del_hogar,
    del_hogar,
    ref_comercio,
    ref_tematica,
    tematica_del_hogar,
    texto_plano,
    una_respuesta,
)
from app.core.config import settings
from app.core.errors import Conflicto, NoEncontrado, ReglaDeNegocio
from app.models.alerta import Alert
from app.models.categoria import Category
from app.models.comercio import Payee
from app.models.hogar import Household
from app.models.recurrente import RecurringOccurrence, RecurringRule
from app.models.transaccion import Transaction
from app.schemas.comun import Pagina
from app.schemas.recurrente import (
    A_FRECUENCIA_SERVICIO,
    ULTIMO_DIA_DEL_MES,
    DetectadosFiltro,
    Frecuencia,
    HistorialPrecioRecurrenteRespuesta,
    OcurrenciaRespuesta,
    ProximosFiltro,
    ProximoVencimientoRespuesta,
    PuntoPrecioRecurrenteRespuesta,
    RecurrenteActualizar,
    RecurrenteConfirmarCrear,
    RecurrenteCrear,
    RecurrenteDetectadoRespuesta,
    RecurrenteFiltro,
    RecurrentePublicarCrear,
    RecurrenteRespuesta,
    RecurrenteSaltarCrear,
)
from app.schemas.transaccion import TipoMovimiento, TransaccionRespuesta
from app.services.formato import cuantizar
from app.services.recurrencia import (
    Frecuencia as FrecuenciaServicio,
)
from app.services.recurrencia import (
    ReglaRepeticion,
    dias_hasta,
    proximas_ocurrencias,
    siguiente_fecha,
)

# Las rutas llevan su prefijo completo (`/recurring`), así que el agregador
# incluye este router sin `prefix`. `verificar_csrf` va en el router porque no
# hace nada en GET, HEAD ni OPTIONS: así no se puede olvidar en un endpoint.
router = APIRouter(tags=["recurring"], dependencies=[Depends(verificar_csrf)])

CERO = Decimal("0.00")

#: «Último día laborable del mes» necesita dos cosas que el esquema guarda en
#: columnas distintas: `month_day_policy = 'last_day'` y la marca de que solo
#: valen días de lunes a viernes, que se escribe en `by_weekday`.
LABORABLES = [0, 1, 2, 3, 4]

#: Repeticiones al año de cada frecuencia del motor, para el coste anual.
_AL_ANYO: dict[FrecuenciaServicio, Decimal] = {
    FrecuenciaServicio.DIARIA: Decimal(365),
    FrecuenciaServicio.SEMANAL: Decimal(52),
    FrecuenciaServicio.QUINCENAL: Decimal(26),
    FrecuenciaServicio.MENSUAL: Decimal(12),
    FrecuenciaServicio.BIMESTRAL: Decimal(6),
    FrecuenciaServicio.TRIMESTRAL: Decimal(4),
    FrecuenciaServicio.SEMESTRAL: Decimal(2),
    FrecuenciaServicio.ANUAL: Decimal(1),
}

#: Intervalo típico en días de cada frecuencia, para estimar la de un grupo detectado.
_DIAS_TIPICOS: tuple[tuple[int, Frecuencia], ...] = (
    (7, Frecuencia.WEEKLY),
    (14, Frecuencia.BIWEEKLY),
    (30, Frecuencia.MONTHLY),
    (61, Frecuencia.BIMONTHLY),
    (91, Frecuencia.QUARTERLY),
    (182, Frecuencia.SEMIANNUAL),
    (365, Frecuencia.YEARLY),
)

#: RN-39: al menos tres cargos, intervalo estable (±20 %) e importe estable (≥ 0,8).
DESVIACION_MAXIMA_INTERVALO = Decimal("0.20")
ESTABILIDAD_MINIMA = 0.8

ESTADOS_MATERIALIZADOS = ("created", "matched")


# --------------------------------------------------------------------------- #
# Traducción entre el contrato y las columnas
# --------------------------------------------------------------------------- #


def _es_ultimo_laborable(fila: RecurringRule) -> bool:
    return fila.month_day_policy == "last_day" and (fila.by_weekday or []) == LABORABLES


def frecuencia_publica(fila: RecurringRule) -> Frecuencia:
    """De la frecuencia del motor a la del contrato."""
    servicio = FrecuenciaServicio(fila.frequency)
    if servicio is FrecuenciaServicio.DIARIA:
        return Frecuencia.EVERY_N_DAYS
    if servicio is FrecuenciaServicio.MENSUAL and _es_ultimo_laborable(fila):
        return Frecuencia.LAST_WEEKDAY_OF_MONTH
    for publica, equivalente in A_FRECUENCIA_SERVICIO.items():
        if equivalente is servicio and publica not in (
            Frecuencia.EVERY_N_DAYS,
            Frecuencia.LAST_WEEKDAY_OF_MONTH,
        ):
            return publica
    return Frecuencia.MONTHLY


def dia_del_mes_de(fila: RecurringRule) -> int | None:
    if fila.month_day_policy == "last_day":
        return ULTIMO_DIA_DEL_MES
    return fila.by_month_day[0] if fila.by_month_day else None


def dia_de_la_semana_de(fila: RecurringRule) -> int | None:
    dias = fila.by_weekday or []
    return dias[0] if len(dias) == 1 else None


def regla_de(fila: RecurringRule) -> ReglaRepeticion:
    """La fila como `ReglaRepeticion`, que es quien sabe calcular fechas."""
    return ReglaRepeticion(
        frecuencia=FrecuenciaServicio(fila.frequency),
        intervalo=fila.interval_count,
        dia_del_mes=dia_del_mes_de(fila),
        dia_de_la_semana=dia_de_la_semana_de(fila),
        fecha_inicio=fila.starts_on,
        fecha_fin=fila.ends_on,
        repeticiones_max=fila.max_occurrences,
        solo_dias_laborables=_es_ultimo_laborable(fila),
    )


def _columnas_de_repeticion(
    frecuencia: Frecuencia, dia_del_mes: int | None, dia_semana: int | None
) -> dict[str, object]:
    """Del contrato a las columnas explícitas del esquema."""
    ultimo_laborable = frecuencia is Frecuencia.LAST_WEEKDAY_OF_MONTH
    ultimo_dia = ultimo_laborable or dia_del_mes == ULTIMO_DIA_DEL_MES
    dias_mes = None if ultimo_dia or dia_del_mes is None else [dia_del_mes]
    if ultimo_laborable:
        semana = LABORABLES
    elif dia_semana is not None:
        semana = [dia_semana]
    else:
        semana = None
    return {
        "frequency": A_FRECUENCIA_SERVICIO[frecuencia].value,
        "month_day_policy": "last_day" if ultimo_dia else "clamp",
        "by_month_day": dias_mes,
        "by_weekday": semana,
    }


# --------------------------------------------------------------------------- #
# Respuesta
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Historial:
    """Ocurrencias ya materializadas de un recurrente, de más antigua a más nueva."""

    ocurrencias: list[RecurringOccurrence]

    @property
    def importes(self) -> list[Decimal]:
        return [o.actual_amount for o in self.ocurrencias if o.actual_amount is not None]

    @property
    def ultimo(self) -> Decimal | None:
        importes = self.importes
        return importes[-1] if importes else None

    @property
    def anterior(self) -> Decimal | None:
        importes = self.importes
        return importes[-2] if len(importes) > 1 else None

    @property
    def variacion_pct(self) -> float | None:
        """RN-40: la subida se mide contra el último cargo, nunca contra la media."""
        ultimo, anterior = self.ultimo, self.anterior
        if ultimo is None or anterior is None or anterior == CERO:
            return None
        return float((abs(ultimo) - abs(anterior)) / abs(anterior) * 100)


def _coste_anual(fila: RecurringRule) -> Decimal:
    veces = _AL_ANYO[FrecuenciaServicio(fila.frequency)] / Decimal(fila.interval_count)
    return cuantizar(abs(fila.expected_amount) * veces)


def respuesta_recurrente(
    fila: RecurringRule,
    *,
    tematica: Category | None,
    comercio: Payee | None,
    historial: Historial,
    ocurrencias_visibles: list[RecurringOccurrence] | None = None,
) -> RecurrenteRespuesta:
    importes = historial.importes
    media = cuantizar(sum((abs(i) for i in importes), CERO) / len(importes)) if importes else None
    return RecurrenteRespuesta(
        id=fila.id,
        created_at=fila.created_at,
        updated_at=fila.updated_at,
        name=fila.name,
        kind=fila.kind,  # type: ignore[arg-type]
        account_id=fila.account_id,  # type: ignore[arg-type]
        category=ref_tematica(tematica),
        payee=ref_comercio(comercio),
        amount=abs(fila.expected_amount),
        currency=fila.currency,
        frequency=frecuencia_publica(fila),
        interval=fila.interval_count,
        day_of_month=dia_del_mes_de(fila),
        weekday=dia_de_la_semana_de(fila),
        rule_text=regla_de(fila).descripcion,
        starts_on=fila.starts_on,
        ends_on=fila.ends_on,
        next_occurrence_on=fila.next_due_on,
        last_posted_on=fila.last_seen_on,
        is_active=fila.status == "active",
        is_paused=fila.status == "paused",
        is_subscription=fila.is_subscription,
        auto_post=fila.auto_create,
        remind_days_before=fila.lead_days,
        occurrences_count=len(historial.ocurrencias),
        average_amount=media,
        last_amount=abs(fila.last_amount) if fila.last_amount is not None else None,
        price_change_pct=historial.variacion_pct,
        annual_cost=_coste_anual(fila),
        note=fila.notes,
        occurrences=[
            OcurrenciaRespuesta(
                id=ocurrencia.id,
                occurrence_date=ocurrencia.due_on,
                amount=abs(ocurrencia.actual_amount or ocurrencia.expected_amount),
                transaction_id=ocurrencia.transaction_id,
                is_skipped=ocurrencia.status == "skipped",
                posted_at=ocurrencia.due_on
                if ocurrencia.status in ESTADOS_MATERIALIZADOS
                else None,
            )
            for ocurrencia in (ocurrencias_visibles or [])
        ],
    )


async def _contexto(
    alcance: AlcanceHogar, filas: list[RecurringRule]
) -> tuple[dict[uuid.UUID, Category], dict[uuid.UUID, Payee], dict[uuid.UUID, Historial]]:
    """Temáticas, comercios e historial de toda la página en tres consultas."""
    if not filas:
        return {}, {}, {}
    ids_tematica = {f.category_id for f in filas if f.category_id}
    ids_comercio = {f.payee_id for f in filas if f.payee_id}
    tematicas: dict[uuid.UUID, Category] = {}
    comercios: dict[uuid.UUID, Payee] = {}
    if ids_tematica:
        tematicas = {
            c.id: c
            for c in await alcance.sesion.scalars(
                select(Category).where(Category.id.in_(ids_tematica))
            )
        }
    if ids_comercio:
        comercios = {
            p.id: p
            for p in await alcance.sesion.scalars(select(Payee).where(Payee.id.in_(ids_comercio)))
        }
    ocurrencias = await alcance.sesion.scalars(
        select(RecurringOccurrence)
        .where(
            RecurringOccurrence.household_id == alcance.household_id,
            RecurringOccurrence.recurring_rule_id.in_([f.id for f in filas]),
            RecurringOccurrence.status.in_(ESTADOS_MATERIALIZADOS),
        )
        .order_by(RecurringOccurrence.due_on)
    )
    historiales: dict[uuid.UUID, Historial] = {f.id: Historial([]) for f in filas}
    for ocurrencia in ocurrencias:
        historiales[ocurrencia.recurring_rule_id].ocurrencias.append(ocurrencia)
    return tematicas, comercios, historiales


async def _respuesta_de(alcance: AlcanceHogar, fila: RecurringRule) -> RecurrenteRespuesta:
    # `updated_at` lo escribe un disparador y su `onupdate` es una expresión SQL:
    # después de un UPDATE queda pendiente de leer, así que la fila se refresca de
    # forma explícita en vez de dejar que salte una carga perezosa.
    await alcance.sesion.refresh(fila)
    tematicas, comercios, historiales = await _contexto(alcance, [fila])
    visibles = list(
        await alcance.sesion.scalars(
            select(RecurringOccurrence)
            .where(RecurringOccurrence.recurring_rule_id == fila.id)
            .order_by(RecurringOccurrence.due_on.desc())
            .limit(12)
        )
    )
    return respuesta_recurrente(
        fila,
        tematica=tematicas.get(fila.category_id) if fila.category_id else None,
        comercio=comercios.get(fila.payee_id) if fila.payee_id else None,
        historial=historiales[fila.id],
        ocurrencias_visibles=visibles,
    )


async def _nombre_libre(alcance: AlcanceHogar, nombre: str, excluir: uuid.UUID | None) -> None:
    consulta = select(RecurringRule.id).where(
        RecurringRule.household_id == alcance.household_id,
        func.lower(RecurringRule.name) == nombre.lower(),
        RecurringRule.status != "ended",
    )
    if excluir is not None:
        consulta = consulta.where(RecurringRule.id != excluir)
    if (await alcance.sesion.scalar(consulta)) is not None:
        raise Conflicto(f"Ya tienes un recurrente llamado «{nombre}».", codigo="nombre_duplicado")


async def _recurrente(alcance: AlcanceHogar, identificador: uuid.UUID) -> RecurringRule:
    return await del_hogar(
        alcance, RecurringRule, identificador, mensaje="El recurrente no existe."
    )


def _refrescar_proxima(fila: RecurringRule, desde: date | None = None) -> None:
    """`next_due_on` está denormalizado: se recalcula cada vez que algo cambia."""
    if fila.status != "active":
        fila.next_due_on = None
        return
    referencia = desde or max(fila.last_seen_on or fila.starts_on, date.today() - timedelta(days=1))
    fila.next_due_on = siguiente_fecha(regla_de(fila), referencia)


# --------------------------------------------------------------------------- #
# Altas y bajas
# --------------------------------------------------------------------------- #


@router.get("/recurring", summary="Recurrentes y suscripciones con su próxima fecha")
async def listar_recurrentes(
    alcance: Alcance,
    filtro: Annotated[RecurrenteFiltro, Query()],
) -> Pagina[RecurrenteRespuesta]:
    consulta = select(RecurringRule).where(
        RecurringRule.household_id == alcance.household_id,
        # Las detecciones descartadas son lápidas, no recurrentes que mostrar.
        ~(
            (RecurringRule.status == "ended")
            & (RecurringRule.origin == "detected")
            & RecurringRule.confirmed_at.is_(None)
        ),
    )
    if filtro.kind:
        consulta = consulta.where(RecurringRule.kind == filtro.kind)
    if filtro.is_active is not None:
        consulta = consulta.where(
            RecurringRule.status == "active"
            if filtro.is_active
            else RecurringRule.status != "active"
        )
    if filtro.is_subscription is not None:
        consulta = consulta.where(RecurringRule.is_subscription.is_(filtro.is_subscription))
    if filtro.category_id:
        consulta = consulta.where(RecurringRule.category_id == filtro.category_id)
    if filtro.account_id:
        consulta = consulta.where(RecurringRule.account_id == filtro.account_id)
    if filtro.q:
        consulta = consulta.where(texto_plano(RecurringRule.name).like(f"%{filtro.q.lower()}%"))

    total = await contar(alcance, consulta)
    columnas = {
        "name": RecurringRule.name,
        "next_occurrence_on": RecurringRule.next_due_on,
        "amount": RecurringRule.expected_amount,
        "annual_cost": RecurringRule.expected_amount,
        "created_at": RecurringRule.created_at,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is not None:
            consulta = consulta.order_by(
                columna.desc().nulls_last() if descendente else columna.asc().nulls_last()
            )
    consulta = consulta.order_by(RecurringRule.id.desc())

    filas = list(
        (await alcance.sesion.execute(consulta.offset(filtro.desplazamiento).limit(filtro.size)))
        .scalars()
        .all()
    )
    tematicas, comercios, historiales = await _contexto(alcance, filas)
    items = [
        respuesta_recurrente(
            fila,
            tematica=tematicas.get(fila.category_id) if fila.category_id else None,
            comercio=comercios.get(fila.payee_id) if fila.payee_id else None,
            historial=historiales[fila.id],
        )
        for fila in filas
    ]
    return Pagina.crear(items, page=filtro.page, size=filtro.size, total=total)


@router.post("/recurring", status_code=status.HTTP_201_CREATED, summary="Crea un recurrente")
async def crear_recurrente(
    alcance: AlcanceEscritura, datos: RecurrenteCrear, respuesta: Response
) -> RecurrenteRespuesta:
    """La coherencia de la regla la comprueba el propio motor de repeticiones."""
    await _nombre_libre(alcance, datos.name, None)
    cuenta = await cuenta_del_hogar(alcance, datos.account_id)
    tematica = None
    if datos.category_id is not None:
        tematica = await tematica_del_hogar(alcance, datos.category_id)
        if tematica.kind != datos.kind:
            raise ReglaDeNegocio(f"«{tematica.name}» no corresponde a este tipo de movimiento.")
    comercio = (
        await del_hogar(alcance, Payee, datos.payee_id, mensaje="El comercio no existe.")
        if datos.payee_id
        else None
    )

    fila = RecurringRule(
        household_id=alcance.household_id,
        name=datos.name,
        kind=datos.kind,
        account_id=cuenta.id,
        category_id=tematica.id if tematica else None,
        payee_id=comercio.id if comercio else None,
        expected_amount=datos.amount,
        currency=datos.currency,
        starts_on=datos.starts_on,
        ends_on=datos.ends_on,
        lead_days=datos.remind_days_before,
        auto_create=datos.auto_post,
        is_subscription=datos.is_subscription,
        status="active",
        origin="manual",
        notes=datos.note,
        interval_count=datos.interval,
        **_columnas_de_repeticion(datos.frequency, datos.day_of_month, datos.weekday),  # type: ignore[arg-type]
    )
    # Construir la regla del servicio valida intervalo, día y rango de fechas.
    datos.a_regla_repeticion()
    _refrescar_proxima(fila, datos.starts_on - timedelta(days=1))
    alcance.sesion.add(fila)
    await alcance.sesion.commit()
    respuesta.headers["Location"] = f"{settings.api_prefix}/recurring/{fila.id}"
    return await _respuesta_de(alcance, fila)


@router.get("/recurring/upcoming", summary="Próximos vencimientos (F-49, F-47)")
async def proximos_vencimientos(
    alcance: Alcance,
    filtro: Annotated[ProximosFiltro, Query()],
) -> list[ProximoVencimientoRespuesta]:
    """Ventana en días. Las fechas las genera `proximas_ocurrencias()`."""
    consulta = select(RecurringRule).where(
        RecurringRule.household_id == alcance.household_id,
        RecurringRule.status == "active",
    )
    if filtro.account_id:
        consulta = consulta.where(RecurringRule.account_id == filtro.account_id)
    filas = list((await alcance.sesion.execute(consulta)).scalars().all())
    tematicas, _, _ = await _contexto(alcance, filas)

    hoy = date.today()
    limite = hoy + timedelta(days=filtro.days)
    proximos: list[ProximoVencimientoRespuesta] = []
    for fila in filas:
        for cuando in proximas_ocurrencias(regla_de(fila), hoy, cuantas=6):
            if cuando > limite:
                break
            proximos.append(
                ProximoVencimientoRespuesta(
                    recurring_id=fila.id,
                    name=fila.name,
                    account_id=fila.account_id,  # type: ignore[arg-type]
                    category=ref_tematica(
                        tematicas.get(fila.category_id) if fila.category_id else None
                    ),
                    due_on=cuando,
                    days_until=dias_hasta(cuando, hoy),
                    expected_amount=abs(fila.expected_amount),
                    is_subscription=fila.is_subscription,
                    is_overdue=cuando < hoy,
                )
            )
    proximos.sort(key=lambda vencimiento: (vencimiento.due_on, vencimiento.name))
    return proximos


# --------------------------------------------------------------------------- #
# Detección de suscripciones (F-29, RN-39)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Deteccion:
    """Un grupo de cargos que se comporta como una suscripción."""

    comercio: Payee
    transacciones: list[Transaction]
    intervalo_medio: float
    estabilidad: float
    frecuencia: Frecuencia
    tematica: Category | None

    @property
    def importes(self) -> list[Decimal]:
        return [abs(t.amount) for t in self.transacciones]


def _frecuencia_estimada(dias: float) -> Frecuencia:
    return min(_DIAS_TIPICOS, key=lambda par: abs(par[0] - dias))[1]


def _estabilidad_importes(importes: list[Decimal]) -> float:
    """1,0 = todos los cargos idénticos. RN-39 exige ≥ 0,8."""
    media = sum(importes, CERO) / len(importes)
    if media == CERO:
        return 0.0
    desviacion = sum((abs(importe - media) for importe in importes), CERO) / len(importes)
    return max(0.0, min(1.0, 1.0 - float(desviacion / media)))


async def _detectar(alcance: AlcanceHogar, filtro: DetectadosFiltro) -> list[Deteccion]:
    desde = date.today() - timedelta(days=30 * filtro.months)
    ya_conocidos = set(
        await alcance.sesion.scalars(
            select(RecurringRule.payee_id).where(
                RecurringRule.household_id == alcance.household_id,
                RecurringRule.payee_id.is_not(None),
            )
        )
    )
    filas = list(
        (
            await alcance.sesion.execute(
                select(Transaction)
                .where(
                    Transaction.household_id == alcance.household_id,
                    Transaction.kind == TipoMovimiento.EXPENSE.value,
                    Transaction.payee_id.is_not(None),
                    Transaction.booked_on >= desde,
                    Transaction.excluded_from_reports.is_(False),
                )
                .order_by(Transaction.payee_id, Transaction.booked_on)
            )
        )
        .scalars()
        .all()
    )
    por_comercio: dict[uuid.UUID, list[Transaction]] = {}
    for fila in filas:
        if fila.payee_id in ya_conocidos:
            continue
        por_comercio.setdefault(fila.payee_id, []).append(fila)  # type: ignore[arg-type]

    candidatos = {
        comercio_id: cargos
        for comercio_id, cargos in por_comercio.items()
        if len(cargos) >= filtro.min_occurrences
    }
    if not candidatos:
        return []
    comercios = {
        p.id: p for p in await alcance.sesion.scalars(select(Payee).where(Payee.id.in_(candidatos)))
    }
    ids_tematica = {
        c.category_id for cargos in candidatos.values() for c in cargos if c.category_id
    }
    tematicas = (
        {
            c.id: c
            for c in await alcance.sesion.scalars(
                select(Category).where(Category.id.in_(ids_tematica))
            )
        }
        if ids_tematica
        else {}
    )

    detecciones: list[Deteccion] = []
    for comercio_id, cargos in candidatos.items():
        fechas = [cargo.booked_on for cargo in cargos]
        intervalos = [
            (siguiente - anterior).days
            for anterior, siguiente in zip(fechas, fechas[1:], strict=False)
        ]
        if not intervalos or min(intervalos) <= 0:
            continue
        medio = statistics.fmean(intervalos)
        desviacion = statistics.fmean(abs(i - medio) for i in intervalos) / medio
        if Decimal(str(desviacion)) > DESVIACION_MAXIMA_INTERVALO:
            continue
        estabilidad = _estabilidad_importes([abs(cargo.amount) for cargo in cargos])
        if estabilidad < ESTABILIDAD_MINIMA:
            continue
        frecuentes = [cargo.category_id for cargo in cargos if cargo.category_id]
        detecciones.append(
            Deteccion(
                comercio=comercios[comercio_id],
                transacciones=cargos,
                intervalo_medio=medio,
                estabilidad=estabilidad,
                frecuencia=_frecuencia_estimada(medio),
                tematica=tematicas.get(max(set(frecuentes), key=frecuentes.count))
                if frecuentes
                else None,
            )
        )
    return detecciones


def _a_respuesta_detectado(deteccion: Deteccion) -> RecurrenteDetectadoRespuesta:
    importes = deteccion.importes
    ultimo = importes[-1]
    anterior = importes[-2] if len(importes) > 1 else None
    return RecurrenteDetectadoRespuesta(
        group_id=str(deteccion.comercio.id),
        payee_name=deteccion.comercio.name,
        suggested_name=deteccion.comercio.name,
        occurrences=len(importes),
        first_seen_on=deteccion.transacciones[0].booked_on,
        last_seen_on=deteccion.transacciones[-1].booked_on,
        estimated_frequency=deteccion.frecuencia,
        average_amount=cuantizar(sum(importes, CERO) / len(importes)),
        last_amount=ultimo,
        amount_stability=round(deteccion.estabilidad, 3),
        price_increase_pct=(
            float((ultimo - anterior) / anterior * 100)
            if anterior not in (None, CERO) and anterior
            else None
        ),
        transaction_ids=[t.id for t in deteccion.transacciones],
        suggested_category=ref_tematica(deteccion.tematica),
        account_id=deteccion.transacciones[-1].account_id,
    )


@router.get("/recurring/detected", summary="Suscripciones detectadas y sin confirmar (F-29)")
async def listar_detectados(
    alcance: Alcance,
    filtro: Annotated[DetectadosFiltro, Query()],
) -> Pagina[RecurrenteDetectadoRespuesta]:
    detecciones = await _detectar(alcance, filtro)
    items = [_a_respuesta_detectado(deteccion) for deteccion in detecciones]
    descendente = ("occurrences", True) in filtro.orden
    items.sort(key=lambda item: item.occurrences, reverse=descendente or not filtro.orden)
    pagina = items[filtro.desplazamiento : filtro.desplazamiento + filtro.size]
    return Pagina.crear(pagina, page=filtro.page, size=filtro.size, total=len(items))


async def _deteccion_de(alcance: AlcanceHogar, grupo: str) -> Deteccion:
    try:
        comercio_id = uuid.UUID(grupo)
    except ValueError as exc:
        raise NoEncontrado("Ese grupo detectado no existe.") from exc
    for deteccion in await _detectar(alcance, DetectadosFiltro()):
        if deteccion.comercio.id == comercio_id:
            return deteccion
    raise NoEncontrado("Ese grupo detectado ya no existe: puede que lo hayas confirmado.")


@router.post(
    "/recurring/detected/{grupo}/confirm",
    status_code=status.HTTP_201_CREATED,
    summary="Convierte un grupo detectado en un recurrente real",
)
async def confirmar_detectado(
    alcance: AlcanceEscritura, grupo: str, datos: RecurrenteConfirmarCrear
) -> RecurrenteRespuesta:
    deteccion = await _deteccion_de(alcance, grupo)
    nombre = datos.name or deteccion.comercio.name
    await _nombre_libre(alcance, nombre, None)

    cuenta_id = datos.account_id or deteccion.transacciones[-1].account_id
    cuenta = await cuenta_del_hogar(alcance, cuenta_id)
    tematica_id = datos.category_id or (deteccion.tematica.id if deteccion.tematica else None)
    if tematica_id is not None:
        await tematica_del_hogar(alcance, tematica_id)
    ultimo = deteccion.transacciones[-1]
    frecuencia = datos.frequency or deteccion.frecuencia

    fila = RecurringRule(
        household_id=alcance.household_id,
        name=nombre,
        kind=TipoMovimiento.EXPENSE.value,
        account_id=cuenta.id,
        category_id=tematica_id,
        payee_id=deteccion.comercio.id,
        expected_amount=datos.amount or abs(ultimo.amount),
        currency=ultimo.currency,
        interval_count=1,
        starts_on=deteccion.transacciones[0].booked_on,
        is_subscription=datos.is_subscription,
        status="active",
        origin="detected",
        detection_confidence=Decimal(str(round(deteccion.estabilidad, 3))),
        confirmed_at=datetime.now(UTC),
        last_amount=abs(ultimo.amount),
        last_seen_on=ultimo.booked_on,
        **_columnas_de_repeticion(frecuencia, ultimo.booked_on.day, None),  # type: ignore[arg-type]
    )
    _refrescar_proxima(fila, ultimo.booked_on)
    alcance.sesion.add(fila)
    await alcance.sesion.flush()

    if datos.link_history:
        for transaccion in deteccion.transacciones:
            transaccion.recurring_rule_id = fila.id
    await alcance.sesion.commit()
    return await _respuesta_de(alcance, fila)


@router.post(
    "/recurring/detected/{grupo}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Descarta la detección para que no vuelva a proponerse",
)
async def descartar_detectado(alcance: AlcanceEscritura, grupo: str) -> Response:
    """RN-39: el descarte se guarda como regla terminada y sin confirmar."""
    deteccion = await _deteccion_de(alcance, grupo)
    ultimo = deteccion.transacciones[-1]
    alcance.sesion.add(
        RecurringRule(
            household_id=alcance.household_id,
            name=f"{deteccion.comercio.name} (descartada {date.today().isoformat()})",
            kind=TipoMovimiento.EXPENSE.value,
            account_id=ultimo.account_id,
            payee_id=deteccion.comercio.id,
            expected_amount=abs(ultimo.amount),
            currency=ultimo.currency,
            interval_count=1,
            starts_on=deteccion.transacciones[0].booked_on,
            ends_on=ultimo.booked_on,
            status="ended",
            origin="detected",
            detection_confidence=Decimal(str(round(deteccion.estabilidad, 3))),
            notes="Detección descartada por el usuario.",
            **_columnas_de_repeticion(deteccion.frecuencia, ultimo.booked_on.day, None),  # type: ignore[arg-type]
        )
    )
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Detalle, edición y ciclo de vida
# --------------------------------------------------------------------------- #


@router.get("/recurring/{recurrente_id}", summary="Detalle con sus últimas ocurrencias")
async def obtener_recurrente(alcance: Alcance, recurrente_id: uuid.UUID) -> RecurrenteRespuesta:
    return await _respuesta_de(alcance, await _recurrente(alcance, recurrente_id))


@router.patch("/recurring/{recurrente_id}", summary="Edita importe, regla, cuenta o temática")
async def editar_recurrente(
    alcance: AlcanceEscritura, recurrente_id: uuid.UUID, datos: RecurrenteActualizar
) -> RecurrenteRespuesta:
    fila = await _recurrente(alcance, recurrente_id)
    campos = datos.model_dump(exclude_unset=True)

    if datos.name:
        await _nombre_libre(alcance, datos.name, fila.id)
        fila.name = datos.name
    if datos.account_id:
        fila.account_id = (await cuenta_del_hogar(alcance, datos.account_id)).id
    if "category_id" in campos:
        if datos.category_id is None:
            fila.category_id = None
        else:
            fila.category_id = (await tematica_del_hogar(alcance, datos.category_id)).id
    if "payee_id" in campos:
        fila.payee_id = (
            (await del_hogar(alcance, Payee, datos.payee_id, mensaje="El comercio no existe.")).id
            if datos.payee_id
            else None
        )
    if datos.amount is not None:
        fila.expected_amount = datos.amount
    if datos.currency:
        fila.currency = datos.currency
    if datos.starts_on:
        fila.starts_on = datos.starts_on
    if "ends_on" in campos:
        fila.ends_on = datos.ends_on
    if datos.is_subscription is not None:
        fila.is_subscription = datos.is_subscription
    if datos.auto_post is not None:
        fila.auto_create = datos.auto_post
    if datos.remind_days_before is not None:
        fila.lead_days = datos.remind_days_before
    if "note" in campos:
        fila.notes = datos.note
    if datos.interval is not None:
        fila.interval_count = datos.interval
    if datos.frequency is not None or "day_of_month" in campos or "weekday" in campos:
        columnas = _columnas_de_repeticion(
            datos.frequency or frecuencia_publica(fila),
            datos.day_of_month if "day_of_month" in campos else dia_del_mes_de(fila),
            datos.weekday if "weekday" in campos else dia_de_la_semana_de(fila),
        )
        for columna, valor in columnas.items():
            setattr(fila, columna, valor)

    _refrescar_proxima(fila)
    await alcance.sesion.commit()
    return await _respuesta_de(alcance, fila)


@router.delete(
    "/recurring/{recurrente_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra la plantilla; las transacciones generadas se conservan",
)
async def borrar_recurrente(alcance: AlcanceEscritura, recurrente_id: uuid.UUID) -> Response:
    """RN-38: lo ya generado queda como movimiento normal (`recurring_id = null`)."""
    fila = (
        await alcance.sesion.execute(
            select(RecurringRule).where(
                RecurringRule.household_id == alcance.household_id,
                RecurringRule.id == recurrente_id,
            )
        )
    ).scalar_one_or_none()
    if fila is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await alcance.sesion.delete(fila)
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/recurring/{recurrente_id}/pause", summary="Pausa la generación")
async def pausar_recurrente(
    alcance: AlcanceEscritura, recurrente_id: uuid.UUID
) -> RecurrenteRespuesta:
    fila = await _recurrente(alcance, recurrente_id)
    fila.status = "paused"
    fila.next_due_on = None
    await alcance.sesion.commit()
    return await _respuesta_de(alcance, fila)


@router.post("/recurring/{recurrente_id}/resume", summary="Reanuda la generación")
async def reanudar_recurrente(
    alcance: AlcanceEscritura, recurrente_id: uuid.UUID
) -> RecurrenteRespuesta:
    fila = await _recurrente(alcance, recurrente_id)
    fila.status = "active"
    _refrescar_proxima(fila)
    await alcance.sesion.commit()
    return await _respuesta_de(alcance, fila)


@router.post("/recurring/{recurrente_id}/skip", summary="Salta una ocurrencia concreta")
async def saltar_ocurrencia(
    alcance: AlcanceEscritura, recurrente_id: uuid.UUID, datos: RecurrenteSaltarCrear
) -> RecurrenteRespuesta:
    fila = await _recurrente(alcance, recurrente_id)
    ocurrencia = await _ocurrencia(alcance, fila, datos.occurrence_date)
    if ocurrencia is not None and ocurrencia.status in ESTADOS_MATERIALIZADOS:
        raise Conflicto("Esa cuota ya está materializada: bórrala si quieres deshacerla.")
    if ocurrencia is None:
        ocurrencia = RecurringOccurrence(
            household_id=alcance.household_id,
            recurring_rule_id=fila.id,
            due_on=datos.occurrence_date,
            expected_amount=fila.expected_amount,
        )
        alcance.sesion.add(ocurrencia)
    ocurrencia.status = "skipped"
    ocurrencia.note = datos.reason
    _refrescar_proxima(fila, datos.occurrence_date)
    await alcance.sesion.commit()
    return await _respuesta_de(alcance, fila)


async def _ocurrencia(
    alcance: AlcanceHogar, fila: RecurringRule, cuando: date
) -> RecurringOccurrence | None:
    return (
        await alcance.sesion.execute(
            select(RecurringOccurrence).where(
                RecurringOccurrence.household_id == alcance.household_id,
                RecurringOccurrence.recurring_rule_id == fila.id,
                RecurringOccurrence.due_on == cuando,
            )
        )
    ).scalar_one_or_none()


@router.post(
    "/recurring/{recurrente_id}/post",
    status_code=status.HTTP_201_CREATED,
    summary="Materializa una ocurrencia como transacción real",
)
async def publicar_ocurrencia(
    alcance: AlcanceEscritura, recurrente_id: uuid.UUID, datos: RecurrentePublicarCrear
) -> TransaccionRespuesta:
    """RN-36: una ocurrencia se materializa una sola vez, por `(recurrente, fecha)`."""
    fila = await _recurrente(alcance, recurrente_id)
    if fila.category_id is None:
        raise ReglaDeNegocio(
            "Este recurrente no tiene temática: asígnale una antes de materializarlo."
        )
    if fila.account_id is None:
        raise ReglaDeNegocio("Este recurrente no tiene cuenta: asígnale una antes de generarlo.")

    ocurrencia = await _ocurrencia(alcance, fila, datos.occurrence_date)
    if ocurrencia is not None and ocurrencia.status in ESTADOS_MATERIALIZADOS:
        raise Conflicto(
            "Esa cuota ya se había generado.",
            detalles=[{"campo": "occurrence_date", "mensaje": str(ocurrencia.transaction_id)}],
        )

    importe = abs(datos.amount if datos.amount is not None else fila.expected_amount)
    firmado = -importe if fila.kind == TipoMovimiento.EXPENSE.value else importe
    transaccion = Transaction(
        household_id=alcance.household_id,
        account_id=fila.account_id,
        kind=fila.kind,
        booked_on=datos.occurrence_date,
        amount=firmado,
        currency=fila.currency,
        category_id=fila.category_id,
        payee_id=fila.payee_id,
        description=fila.name,
        notes=datos.note,
        categorized_by="user",
        recurring_rule_id=fila.id,
        created_by_id=alcance.usuario.id,
    )
    alcance.sesion.add(transaccion)
    await alcance.sesion.flush()

    if ocurrencia is None:
        ocurrencia = RecurringOccurrence(
            household_id=alcance.household_id,
            recurring_rule_id=fila.id,
            due_on=datos.occurrence_date,
            expected_amount=fila.expected_amount,
        )
        alcance.sesion.add(ocurrencia)
    ocurrencia.actual_amount = importe
    ocurrencia.transaction_id = transaccion.id
    ocurrencia.status = "created"
    if fila.expected_amount:
        ocurrencia.amount_change_pct = cuantizar(
            (importe - abs(fila.expected_amount)) / abs(fila.expected_amount) * 100
        )
    await alcance.sesion.flush()
    transaccion.recurring_occurrence_id = ocurrencia.id

    await _avisar_de_subida(alcance, fila, importe, datos.occurrence_date)
    fila.last_amount = importe
    fila.last_seen_on = datos.occurrence_date
    _refrescar_proxima(fila, datos.occurrence_date)
    await ajustar_uso_comercio(alcance, fila.payee_id, 1, cuando=datos.occurrence_date)

    identificador = transaccion.id
    await alcance.sesion.commit()
    return await una_respuesta(alcance, identificador)


async def _avisar_de_subida(
    alcance: AlcanceHogar, fila: RecurringRule, importe: Decimal, cuando: date
) -> None:
    """RN-40: la subida se mide contra el último cargo, no contra la media.

    El aviso es idempotente por causa (RN-71): la clave incluye el recurrente y la
    fecha, así que repetir el cálculo no crea un segundo aviso.
    """
    anterior = fila.last_amount
    if anterior is None or anterior <= CERO or importe <= anterior:
        return
    hogar = await alcance.sesion.get(Household, alcance.household_id)
    umbral = hogar.price_alert_pct if hogar else Decimal("5.00")
    subida = (importe - anterior) / anterior * 100
    if subida < umbral:
        return
    clave = f"recurring_price_increase:{fila.id}:{cuando.isoformat()}"
    existente = (
        await alcance.sesion.execute(
            select(Alert).where(
                Alert.household_id == alcance.household_id, Alert.dedupe_key == clave
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        return
    alcance.sesion.add(
        Alert(
            household_id=alcance.household_id,
            type="recurring_price_increase",
            severity="warning",
            title=f"{fila.name} ha subido de precio",
            body=(
                f"El último cargo fue de {anterior:.2f} € y este es de {importe:.2f} €, "
                f"un {subida:.1f} % más."
            ),
            dedupe_key=clave,
            subject_table="recurring_rules",
            subject_id=fila.id,
            category_id=fila.category_id,
            period_month=date(cuando.year, cuando.month, 1),
            payload={
                "previous_amount": f"{anterior:.2f}",
                "new_amount": f"{importe:.2f}",
                "change_pct": f"{subida:.2f}",
            },
        )
    )


@router.get(
    "/recurring/{recurrente_id}/price-history",
    summary="Evolución del importe cobrado, con las subidas marcadas (F-30)",
)
async def historial_de_precio(
    alcance: Alcance, recurrente_id: uuid.UUID
) -> HistorialPrecioRecurrenteRespuesta:
    fila = await _recurrente(alcance, recurrente_id)
    ocurrencias = list(
        await alcance.sesion.scalars(
            select(RecurringOccurrence)
            .where(
                RecurringOccurrence.household_id == alcance.household_id,
                RecurringOccurrence.recurring_rule_id == fila.id,
                RecurringOccurrence.status.in_(ESTADOS_MATERIALIZADOS),
            )
            .order_by(RecurringOccurrence.due_on)
        )
    )
    puntos: list[PuntoPrecioRecurrenteRespuesta] = []
    subidas = 0
    anterior: Decimal | None = None
    for ocurrencia in ocurrencias:
        importe = abs(ocurrencia.actual_amount or ocurrencia.expected_amount)
        variacion = (
            float((importe - anterior) / anterior * 100)
            if anterior is not None and anterior != CERO
            else None
        )
        if variacion is not None and variacion > 0:
            subidas += 1
        puntos.append(
            PuntoPrecioRecurrenteRespuesta(
                occurrence_date=ocurrencia.due_on,
                amount=importe,
                change_pct=variacion,
                is_increase=bool(variacion and variacion > 0),
                transaction_id=ocurrencia.transaction_id,
            )
        )
        anterior = importe

    primero = puntos[0].amount if puntos else None
    ultimo = puntos[-1].amount if puntos else None
    return HistorialPrecioRecurrenteRespuesta(
        recurring_id=fila.id,
        name=fila.name,
        currency=fila.currency,
        first_amount=primero,
        last_amount=ultimo,
        total_change_pct=(
            float((ultimo - primero) / primero * 100)
            if primero and ultimo and primero != CERO
            else None
        ),
        increases=subidas,
        points=puntos,
    )


__all__ = ["frecuencia_publica", "regla_de", "router"]
