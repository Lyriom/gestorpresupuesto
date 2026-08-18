"""Presupuesto mensual: la barra, el reparto, el arrastre y el cierre (§3.7).

Ningún número se calcula aquí. Todo el cálculo vive en
`app/services/presupuesto.py` —`calcular_barra()`, `reasignar()`,
`calcular_arrastre()`, `reparto_sugerido()`— y este módulo se limita a tres
cosas: leer la base, alimentar al servicio y traducir su salida a los esquemas.
Es lo que garantiza que la barra de la pantalla principal y los informes den
siempre el mismo número.

El gastado sale de `vw_movement_lines`, la vista que unifica transacciones
simples y repartidas e invierte el signo **una sola vez**. Ahí se excluyen las
transferencias (RN-21) y lo marcado como fuera de informes, así que un traspaso
entre cuentas propias no puede aparecer como gasto en la barra.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import DateTime, cast, func, select, text
from sqlalchemy.orm import selectinload

from app.api.deps import (
    Alcance,
    AlcanceEscritura,
    AlcanceHogar,
    PaginacionActual,
    verificar_csrf,
)
from app.api.v1.cuentas import moneda_del_hogar_actual
from app.api.v1.transacciones import contexto_de, respuesta_transaccion, tematica_del_hogar
from app.core.errors import AppError, Conflicto, NoEncontrado, ReglaDeNegocio
from app.models.categoria import Category
from app.models.presupuesto import BudgetAllocation, BudgetPeriod
from app.models.transaccion import Transaction
from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comun import Pagina
from app.schemas.presupuesto import (
    ArrastreRespuesta,
    AsignacionActualizar,
    AsignacionesSustituirCrear,
    AsignacionRespuesta,
    PresupuestoAjustesCrear,
    PresupuestoCopiarCrear,
    PresupuestoDetalleFiltro,
    PresupuestoDistribuirCrear,
    PresupuestoFiltro,
    PresupuestoReasignarCrear,
    PresupuestoRespuesta,
    PresupuestoResumenRespuesta,
)
from app.schemas.transaccion import TipoMovimiento, TransaccionRespuesta
from app.services.presupuesto import (
    CERO,
    EntradaCategoria,
    ErrorPresupuesto,
    Granularidad,
    calcular_arrastre,
    calcular_barra,
    dias_de,
    fin_de,
    granularidad_de,
    inicio_de,
    periodo_anterior,
    periodo_de,
    periodo_siguiente,
    reasignar,
    reparto_sugerido,
    validar_asignacion,
    validar_periodo,
)

# Las rutas llevan su prefijo completo (`/budgets`), así que el agregador
# incluye este router sin `prefix`. `verificar_csrf` va en el router porque no
# hace nada en GET, HEAD ni OPTIONS: así no se puede olvidar en un endpoint.
router = APIRouter(tags=["budgets"], dependencies=[Depends(verificar_csrf)])

#: Tope del recálculo en cascada al reabrir un periodo: diez años, contados en la
#: unidad que toque. Es un cortacircuitos contra un bucle infinito, no una regla de
#: negocio; con un solo número, diez años de meses se quedaban en dos de semanas.
MAXIMO_CASCADA = {Granularidad.MES: 120, Granularidad.SEMANA: 522}

#: Modos de arrastre de `households.default_rollover_mode` (F-26).
SIN_ARRASTRE = "none"
ARRASTRE_SIMPLE = "carry"
ARRASTRE_CON_DEUDA = "carry_negative"


# --------------------------------------------------------------------------- #
# Periodo
# --------------------------------------------------------------------------- #


def periodo_valido(periodo: str) -> str:
    """RN-30: `AAAA-MM`. El patrón lo comprueba el servicio, no una copia local."""
    try:
        return validar_periodo(periodo)
    except ErrorPresupuesto as exc:
        raise AppError(
            str(exc),
            codigo="periodo_invalido",
            estado=status.HTTP_422_UNPROCESSABLE_CONTENT,
        ) from exc


def primer_dia(periodo: str) -> date:
    """El primer día del periodo, validándolo antes para dar un 422 y no un 500."""
    return inicio_de(periodo_valido(periodo))


def rango_de(periodo: str) -> tuple[date, date]:
    """Primer y último día del periodo, ambos inclusive."""
    return primer_dia(periodo), fin_de(periodo)


def periodo_de_fila(fila: BudgetPeriod) -> str:
    """El nombre del periodo de una fila, con la granularidad que guarda ella.

    No se deduce del ajuste del hogar: un periodo semanal sigue siendo semanal
    aunque el hogar haya vuelto a presupuestar por meses.
    """
    return periodo_de(fila.period_start, Granularidad(fila.granularity))


async def _periodo(alcance: AlcanceHogar, periodo: str) -> BudgetPeriod | None:
    return (
        await alcance.sesion.execute(
            select(BudgetPeriod).where(
                BudgetPeriod.household_id == alcance.household_id,
                BudgetPeriod.period_start == primer_dia(periodo),
                # El 1 de junio de 2026 es lunes: sin esto, pedir la semana 23
                # devolvería el mes de junio.
                BudgetPeriod.granularity == granularidad_de(periodo).value,
            )
        )
    ).scalar_one_or_none()


async def _periodo_asegurado(alcance: AlcanceHogar, periodo: str) -> BudgetPeriod:
    """El periodo, creándolo si es la primera vez que se toca."""
    fila = await _periodo(alcance, periodo)
    if fila is not None:
        return fila
    fila = BudgetPeriod(
        household_id=alcance.household_id,
        period_start=primer_dia(periodo),
        granularity=granularidad_de(periodo).value,
    )
    alcance.sesion.add(fila)
    await alcance.sesion.flush()
    return fila


def _exigir_abierto(fila: BudgetPeriod | None) -> None:
    """RN-33: un periodo cerrado rechaza cambios de asignación hasta reabrirlo."""
    if fila is not None and fila.closed_at is not None:
        raise Conflicto(
            "El periodo está cerrado. Reábrelo si quieres cambiar el reparto.",
            codigo="periodo_cerrado",
        )


# --------------------------------------------------------------------------- #
# Lo gastado y lo ingresado, siempre desde la vista de movimientos
# --------------------------------------------------------------------------- #

# Solo temáticas de gasto: a una de ingresos no se le asigna presupuesto (RN-34) y
# sumarla aquí restaría del gastado del mes, porque la vista ya invierte el signo.
_GASTADO = text(
    """
    SELECT m.category_id, COALESCE(SUM(m.spent), 0)::numeric(14,2) AS gastado
      FROM vw_movement_lines m
      JOIN categories c ON c.id = m.category_id
     WHERE m.household_id = :hogar
       AND m.booked_on BETWEEN :desde AND :hasta
       AND m.kind <> 'transfer'
       AND NOT m.excluded_from_reports
       AND c.kind = 'expense'
     GROUP BY m.category_id
    """
)


async def gastado_por_tematica(
    alcance: AlcanceHogar, desde: date, hasta: date
) -> dict[uuid.UUID, Decimal]:
    """Gastado por temática en el rango, splits incluidos y transferencias fuera."""
    filas = await alcance.sesion.execute(
        _GASTADO, {"hogar": alcance.household_id, "desde": desde, "hasta": hasta}
    )
    return {fila.category_id: Decimal(fila.gastado) for fila in filas}


async def ingresos_reales(alcance: AlcanceHogar, desde: date, hasta: date) -> Decimal:
    """Suma de los ingresos del periodo (F-01). Una transferencia no es un ingreso."""
    total = await alcance.sesion.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.household_id == alcance.household_id,
            Transaction.kind == TipoMovimiento.INCOME.value,
            Transaction.booked_on.between(desde, hasta),
            Transaction.excluded_from_reports.is_(False),
        )
    )
    return Decimal(total or 0)


# --------------------------------------------------------------------------- #
# La barra
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class DatosBarra:
    """Lo que hace falta para pintar el periodo, ya leído de la base."""

    periodo: str
    fila: BudgetPeriod | None
    asignaciones: list[BudgetAllocation]
    tematicas: dict[uuid.UUID, Category]
    gastado: dict[uuid.UUID, Decimal]
    ingreso_real: Decimal
    moneda: str

    @property
    def ingreso(self) -> Decimal:
        """RN-35: el 100 % del carril es el previsto si lo hay; si no, el real."""
        if self.fila is not None and self.fila.expected_income is not None:
            return self.fila.expected_income
        return self.ingreso_real


async def _leer_barra(
    alcance: AlcanceHogar, periodo: str, *, incluir_archivadas: bool = False
) -> DatosBarra:
    desde, hasta = rango_de(periodo)
    fila = await _periodo(alcance, periodo)

    asignaciones: list[BudgetAllocation] = []
    if fila is not None:
        asignaciones = list(
            (
                await alcance.sesion.execute(
                    select(BudgetAllocation).where(
                        BudgetAllocation.household_id == alcance.household_id,
                        BudgetAllocation.budget_period_id == fila.id,
                    )
                )
            )
            .scalars()
            .all()
        )

    gastado = await gastado_por_tematica(alcance, desde, hasta)
    ids = {asignacion.category_id for asignacion in asignaciones} | set(gastado)
    tematicas: dict[uuid.UUID, Category] = {}
    if ids:
        filas = await alcance.sesion.scalars(select(Category).where(Category.id.in_(ids)))
        tematicas = {
            categoria.id: categoria
            for categoria in filas
            # Una temática de ingresos no se presupuesta (RN-34) y no entra en la barra.
            if categoria.kind == "expense" and (incluir_archivadas or categoria.archived_at is None)
        }

    return DatosBarra(
        periodo=periodo,
        fila=fila,
        asignaciones=[a for a in asignaciones if a.category_id in tematicas],
        tematicas=tematicas,
        gastado={k: v for k, v in gastado.items() if k in tematicas},
        ingreso_real=await ingresos_reales(alcance, desde, hasta),
        moneda=await moneda_del_hogar_actual(alcance),
    )


def _entradas_de(datos: DatosBarra, profundidad: int | None) -> list[EntradaCategoria]:
    """Traduce lo leído a las entradas que consume `calcular_barra()`."""
    por_tematica = {asignacion.category_id: asignacion for asignacion in datos.asignaciones}
    entradas: list[EntradaCategoria] = []
    for categoria_id, categoria in datos.tematicas.items():
        if profundidad is not None and categoria.depth >= profundidad:
            continue
        asignacion = por_tematica.get(categoria_id)
        entradas.append(
            EntradaCategoria(
                categoria_id=str(categoria_id),
                nombre=categoria.name,
                color=categoria.color_hex,
                icono=categoria.icon,
                categoria_padre_id=str(categoria.parent_id) if categoria.parent_id else None,
                asignado=asignacion.allocated_amount if asignacion else CERO,
                gastado=datos.gastado.get(categoria_id, CERO),
                arrastrado=asignacion.carryover_in if asignacion else CERO,
                permite_arrastre=bool(asignacion and asignacion.rollover_mode != SIN_ARRASTRE),
            )
        )
    return entradas


def _dia_del_periodo(periodo: str, hoy: date) -> tuple[int, int]:
    """Día que se pinta como «hoy» en la barra y días que tiene el periodo.

    Se cuenta desde el arranque del periodo y no por el día del mes: en una semana
    que empieza el 10 de agosto, el día 13 es el cuarto de siete, no el trece de
    siete. Para un mes las dos cuentas coinciden, que es por lo que no se notaba.
    """
    inicio, fin = rango_de(periodo)
    dias = dias_de(periodo)
    if hoy < inicio:
        return 1, dias
    if hoy > fin:
        return dias, dias
    return (hoy - inicio).days + 1, dias


def _a_respuesta_barra(datos: DatosBarra, profundidad: int | None) -> PresupuestoRespuesta:
    entradas = _entradas_de(datos, profundidad)
    barra = calcular_barra(datos.periodo, datos.ingreso, entradas)
    por_tematica = {a.category_id: a for a in datos.asignaciones}

    asignaciones: dict[uuid.UUID, AsignacionRespuesta] = {}
    orden: list[uuid.UUID] = []
    for segmento in barra.segmentos:
        categoria_id = uuid.UUID(segmento.categoria_id)
        categoria = datos.tematicas[categoria_id]
        asignacion = por_tematica.get(categoria_id)
        asignaciones[categoria_id] = AsignacionRespuesta(
            category_id=categoria_id,
            category=CategoriaRefRespuesta(
                id=categoria.id, name=categoria.name, color=categoria.color_hex
            ),
            allocated=segmento.asignado,
            rollover_in=segmento.arrastrado,
            available=segmento.disponible,
            spent=segmento.gastado,
            spent_pct=float(segmento.porcentaje_consumido) / 100,
            overspent=segmento.sobrepaso,
            state=segmento.estado,
            rollover_enabled=bool(asignacion and asignacion.rollover_mode != SIN_ARRASTRE),
            is_locked=bool(asignacion and asignacion.is_locked) or categoria.is_locked,
            note=asignacion.note if asignacion else None,
        )
        orden.append(categoria_id)

    # El árbol se cuelga por `parent_id`; una temática cuya madre no está en la
    # barra (filtrada por profundidad o archivada) se queda en la raíz.
    raiz: list[AsignacionRespuesta] = []
    for categoria_id in orden:
        padre = datos.tematicas[categoria_id].parent_id
        if padre is not None and padre in asignaciones:
            asignaciones[padre].children.append(asignaciones[categoria_id])
        else:
            raiz.append(asignaciones[categoria_id])

    dia, dias = _dia_del_periodo(datos.periodo, date.today())
    fila = datos.fila
    return PresupuestoRespuesta(
        period=datos.periodo,
        currency=datos.moneda,
        is_closed=bool(fila and fila.closed_at),
        closed_at=fila.closed_at if fila else None,
        income_actual=datos.ingreso_real,
        planned_income=fila.expected_income if fila else None,
        income=barra.ingresos,
        allocated_total=barra.total_asignado,
        spent_total=barra.total_gastado,
        unassigned=barra.sin_asignar,
        overallocated=-barra.sin_asignar if barra.sin_asignar < CERO else CERO,
        rollover_in_total=barra.total_arrastrado,
        day_of_period=dia,
        days_in_period=dias,
        allocations=raiz,
        warnings=barra.avisos,
        note=fila.note if fila else None,
    )


async def barra_del_periodo(
    alcance: AlcanceHogar,
    periodo: str,
    *,
    incluir_archivadas: bool = False,
    profundidad: int | None = None,
) -> PresupuestoRespuesta:
    """El payload del `BudgetBar`, tal cual lo consume el frontend."""
    datos = await _leer_barra(alcance, periodo, incluir_archivadas=incluir_archivadas)
    return _a_respuesta_barra(datos, profundidad)


# --------------------------------------------------------------------------- #
# Asignaciones
# --------------------------------------------------------------------------- #


async def _tematica_presupuestable(alcance: AlcanceHogar, categoria_id: uuid.UUID) -> Category:
    """RN-34: ni archivada, ni de ingresos, ni inexistente."""
    categoria = await tematica_del_hogar(alcance, categoria_id, permitir_ingreso=False)
    return categoria


async def _asignacion(
    alcance: AlcanceHogar, fila: BudgetPeriod, categoria_id: uuid.UUID
) -> BudgetAllocation | None:
    return (
        await alcance.sesion.execute(
            select(BudgetAllocation).where(
                BudgetAllocation.household_id == alcance.household_id,
                BudgetAllocation.budget_period_id == fila.id,
                BudgetAllocation.category_id == categoria_id,
            )
        )
    ).scalar_one_or_none()


async def _fijar_asignacion(
    alcance: AlcanceHogar,
    fila: BudgetPeriod,
    categoria_id: uuid.UUID,
    importe: Decimal,
    *,
    arrastre: bool | None = None,
    nota: str | None = None,
    origen: str = "user",
) -> BudgetAllocation:
    """Escribe la asignación de una temática. RN-28: nunca negativa."""
    try:
        valor = validar_asignacion(importe)
    except ErrorPresupuesto as exc:
        raise ReglaDeNegocio(str(exc), codigo="presupuesto_negativo") from exc

    asignacion = await _asignacion(alcance, fila, categoria_id)
    modo = None
    if arrastre is not None:
        modo = ARRASTRE_SIMPLE if arrastre else SIN_ARRASTRE
    if asignacion is None:
        asignacion = BudgetAllocation(
            household_id=alcance.household_id,
            budget_period_id=fila.id,
            category_id=categoria_id,
            allocated_amount=valor,
            rollover_mode=modo or SIN_ARRASTRE,
            note=nota,
            source=origen,
        )
        alcance.sesion.add(asignacion)
    else:
        asignacion.allocated_amount = valor
        if modo is not None:
            asignacion.rollover_mode = modo
        if nota is not None:
            asignacion.note = nota
        asignacion.source = origen
    await alcance.sesion.flush()
    return asignacion


# --------------------------------------------------------------------------- #
# Arrastre (F-26, RN-32)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class SalidaArrastre:
    """Lo que una temática deja al mes siguiente."""

    categoria_id: uuid.UUID
    asignado: Decimal
    gastado: Decimal
    arrastrado_previo: Decimal
    arrastre: Decimal
    modo: str


async def _arrastres_de(alcance: AlcanceHogar, periodo: str) -> list[SalidaArrastre]:
    """Aplica `calcular_arrastre()` a cada temática del periodo."""
    fila = await _periodo(alcance, periodo)
    if fila is None:
        return []
    desde, hasta = rango_de(periodo)
    gastado = await gastado_por_tematica(alcance, desde, hasta)
    asignaciones = list(
        (
            await alcance.sesion.execute(
                select(BudgetAllocation).where(
                    BudgetAllocation.household_id == alcance.household_id,
                    BudgetAllocation.budget_period_id == fila.id,
                )
            )
        )
        .scalars()
        .all()
    )
    salidas: list[SalidaArrastre] = []
    for asignacion in asignaciones:
        gasto = gastado.get(asignacion.category_id, CERO)
        salidas.append(
            SalidaArrastre(
                categoria_id=asignacion.category_id,
                asignado=asignacion.allocated_amount,
                gastado=gasto,
                arrastrado_previo=asignacion.carryover_in,
                arrastre=calcular_arrastre(
                    asignacion.allocated_amount,
                    gasto,
                    asignacion.carryover_in,
                    permite_arrastre=asignacion.rollover_mode != SIN_ARRASTRE,
                    arrastrar_deuda=asignacion.rollover_mode == ARRASTRE_CON_DEUDA,
                ),
                modo=asignacion.rollover_mode,
            )
        )
    return salidas


async def _escribir_arrastre(alcance: AlcanceHogar, periodo: str, *, aplicar: bool) -> None:
    """Vuelca (o pone a cero) el arrastre que `periodo` deja en el siguiente."""
    salidas = await _arrastres_de(alcance, periodo)
    if not salidas:
        return
    hay_arrastre = aplicar and any(salida.arrastre != CERO for salida in salidas)
    nombre_siguiente = periodo_siguiente(periodo)
    siguiente = await _periodo(alcance, nombre_siguiente)
    if siguiente is None:
        if not hay_arrastre:
            return
        siguiente = await _periodo_asegurado(alcance, nombre_siguiente)
    for salida in salidas:
        entrante = salida.arrastre if aplicar else CERO
        asignacion = await _asignacion(alcance, siguiente, salida.categoria_id)
        if asignacion is None:
            if entrante == CERO:
                continue
            alcance.sesion.add(
                BudgetAllocation(
                    household_id=alcance.household_id,
                    budget_period_id=siguiente.id,
                    category_id=salida.categoria_id,
                    allocated_amount=CERO,
                    carryover_in=entrante,
                    rollover_mode=salida.modo,
                    source="rollover",
                )
            )
        else:
            asignacion.carryover_in = entrante
    await alcance.sesion.flush()


async def _recalcular_cascada(alcance: AlcanceHogar, desde: str) -> None:
    """Recalcula el arrastre de `desde` hacia adelante (RN-33, al reabrir)."""
    actual = desde
    for _ in range(MAXIMO_CASCADA[granularidad_de(desde)]):
        fila = await _periodo(alcance, actual)
        if fila is None:
            return
        await _escribir_arrastre(alcance, actual, aplicar=fila.closed_at is not None)
        actual = periodo_siguiente(actual)


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.get("/budgets", summary="Periodos con presupuesto, para el selector de mes")
async def listar_periodos(
    alcance: Alcance,
    filtro: Annotated[PresupuestoFiltro, Query()],
) -> Pagina[PresupuestoResumenRespuesta]:
    consulta = select(BudgetPeriod).where(BudgetPeriod.household_id == alcance.household_id)
    if filtro.period_from:
        consulta = consulta.where(BudgetPeriod.period_start >= primer_dia(filtro.period_from))
    if filtro.period_to:
        # Hasta el **final** del periodo pedido, no hasta su primer día: si no, pedir
        # «hasta 2026-08» dejaría fuera todas las semanas de agosto menos la primera.
        hasta = fin_de(periodo_valido(filtro.period_to))
        consulta = consulta.where(BudgetPeriod.period_start <= hasta)

    total = int(
        await alcance.sesion.scalar(
            select(func.count()).select_from(consulta.order_by(None).subquery())
        )
        or 0
    )
    descendente = ("period", True) in filtro.orden or not filtro.orden
    consulta = consulta.order_by(
        BudgetPeriod.period_start.desc() if descendente else BudgetPeriod.period_start.asc()
    )
    filas = list(
        (await alcance.sesion.execute(consulta.offset(filtro.desplazamiento).limit(filtro.size)))
        .scalars()
        .all()
    )
    if not filas:
        return Pagina.crear([], page=filtro.page, size=filtro.size, total=total)

    # Tres agregados para toda la página, no tres por mes.
    asignado = dict(
        (
            await alcance.sesion.execute(
                select(
                    BudgetAllocation.budget_period_id,
                    func.coalesce(func.sum(BudgetAllocation.allocated_amount), 0),
                )
                .where(BudgetAllocation.budget_period_id.in_([f.id for f in filas]))
                .group_by(BudgetAllocation.budget_period_id)
            )
        ).all()
    )
    inicio = min(f.period_start for f in filas)
    fin = max(fin_de(periodo_de_fila(f)) for f in filas)

    # El gasto y el ingreso se agrupan por el arranque del periodo al que cae cada
    # movimiento. `date_trunc` sirve para las dos granularidades sin enumerar casos:
    # da el día 1 del mes o el lunes de la semana, que es justo lo que guarda
    # `period_start`. Una consulta por granularidad presente en la página, que es una
    # sola salvo justo después de cambiar el ajuste del hogar.
    #
    # Antes se usaba la columna `period_month` de la vista, que es siempre el mes del
    # movimiento: con periodos semanales todas las semanas de agosto habrían recibido
    # el gasto de agosto entero.
    gastado_por_periodo: dict[tuple[str, date], Decimal] = {}
    ingreso_por_periodo: dict[tuple[str, date], Decimal] = {}
    for granularidad in sorted({f.granularity for f in filas}):
        gastos = await alcance.sesion.execute(
            text(
                """
                SELECT date_trunc(:unidad, m.booked_on::timestamp)::date AS inicio,
                       COALESCE(SUM(m.spent), 0)::numeric(14,2) AS gastado
                  FROM vw_movement_lines m
                  JOIN categories c ON c.id = m.category_id
                 WHERE m.household_id = :hogar AND m.booked_on BETWEEN :desde AND :hasta
                   AND m.kind <> 'transfer' AND NOT m.excluded_from_reports
                   AND c.kind = 'expense'
                 GROUP BY 1
                """
            ),
            {
                "hogar": alcance.household_id,
                "desde": inicio,
                "hasta": fin,
                "unidad": granularidad,
            },
        )
        for fila_gasto in gastos:
            gastado_por_periodo[(granularidad, fila_gasto.inicio)] = Decimal(fila_gasto.gastado)

        ingresos = await alcance.sesion.execute(
            select(
                func.date_trunc(granularidad, cast(Transaction.booked_on, DateTime)).label(
                    "inicio"
                ),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            )
            .where(
                Transaction.household_id == alcance.household_id,
                Transaction.kind == TipoMovimiento.INCOME.value,
                Transaction.booked_on.between(inicio, fin),
                Transaction.excluded_from_reports.is_(False),
            )
            .group_by(text("inicio"))
        )
        for fila_ingreso in ingresos:
            ingreso_por_periodo[(granularidad, fila_ingreso.inicio.date())] = Decimal(
                fila_ingreso.total
            )

    items = [
        PresupuestoResumenRespuesta(
            period=periodo_de_fila(fila),
            income=(
                fila.expected_income
                if fila.expected_income is not None
                else ingreso_por_periodo.get((fila.granularity, fila.period_start), CERO)
            ),
            allocated_total=Decimal(asignado.get(fila.id, 0)),
            spent_total=gastado_por_periodo.get((fila.granularity, fila.period_start), CERO),
            is_closed=fila.closed_at is not None,
        )
        for fila in filas
    ]
    return Pagina.crear(items, page=filtro.page, size=filtro.size, total=total)


@router.get("/budgets/{periodo}", summary="El payload completo del BudgetBar")
async def obtener_presupuesto(
    alcance: Alcance,
    periodo: str,
    filtro: Annotated[PresupuestoDetalleFiltro, Query()],
) -> PresupuestoRespuesta:
    """Ingresos, asignado, gastado, arrastre y disponible por temática."""
    return await barra_del_periodo(
        alcance,
        periodo_valido(periodo),
        incluir_archivadas=filtro.include_archived,
        profundidad=filtro.depth,
    )


@router.put("/budgets/{periodo}", summary="Ingreso previsto, arrastre por defecto y notas")
async def ajustar_presupuesto(
    alcance: AlcanceEscritura, periodo: str, datos: PresupuestoAjustesCrear
) -> PresupuestoRespuesta:
    periodo = periodo_valido(periodo)
    fila = await _periodo(alcance, periodo)
    _exigir_abierto(fila)
    fila = await _periodo_asegurado(alcance, periodo)

    campos = datos.model_dump(exclude_unset=True)
    if "planned_income" in campos:
        fila.expected_income = datos.planned_income
        fila.income_source = "derived" if datos.planned_income is None else "manual"
    if "note" in campos:
        fila.note = datos.note
    if datos.rollover_default is not None:
        # El valor por defecto se aplica a las asignaciones del periodo que no lo
        # tengan decidido: es lo que el usuario espera al mover el interruptor.
        modo = ARRASTRE_SIMPLE if datos.rollover_default else SIN_ARRASTRE
        for asignacion in await _asignaciones_del_periodo(alcance, fila):
            asignacion.rollover_mode = modo
    await alcance.sesion.commit()
    return await barra_del_periodo(alcance, periodo)


async def _asignaciones_del_periodo(
    alcance: AlcanceHogar, fila: BudgetPeriod
) -> list[BudgetAllocation]:
    return list(
        (
            await alcance.sesion.execute(
                select(BudgetAllocation).where(
                    BudgetAllocation.household_id == alcance.household_id,
                    BudgetAllocation.budget_period_id == fila.id,
                )
            )
        )
        .scalars()
        .all()
    )


@router.get("/budgets/{periodo}/allocations", summary="Asignaciones por temática")
async def listar_asignaciones(alcance: Alcance, periodo: str) -> list[AsignacionRespuesta]:
    barra = await barra_del_periodo(alcance, periodo_valido(periodo))
    return barra.allocations


@router.put("/budgets/{periodo}/allocations", summary="Sustituye el reparto completo")
async def sustituir_asignaciones(
    alcance: AlcanceEscritura, periodo: str, datos: AsignacionesSustituirCrear
) -> PresupuestoRespuesta:
    """Idempotente. Ninguna asignación negativa (RN-28)."""
    periodo = periodo_valido(periodo)
    existente = await _periodo(alcance, periodo)
    _exigir_abierto(existente)
    fila = await _periodo_asegurado(alcance, periodo)

    enviadas: set[uuid.UUID] = set()
    for asignacion in datos.allocations:
        await _tematica_presupuestable(alcance, asignacion.category_id)
        await _fijar_asignacion(
            alcance,
            fila,
            asignacion.category_id,
            asignacion.amount,
            arrastre=asignacion.rollover_enabled,
            nota=asignacion.note,
        )
        enviadas.add(asignacion.category_id)

    if datos.remove_missing:
        for otra in await _asignaciones_del_periodo(alcance, fila):
            if otra.category_id not in enviadas and not otra.is_locked:
                otra.allocated_amount = CERO
    await alcance.sesion.commit()
    return await barra_del_periodo(alcance, periodo)


@router.patch(
    "/budgets/{periodo}/allocations/{categoria_id}",
    summary="Cambia la asignación de una temática",
)
async def editar_asignacion(
    alcance: AlcanceEscritura,
    periodo: str,
    categoria_id: uuid.UUID,
    datos: AsignacionActualizar,
) -> AsignacionRespuesta:
    periodo = periodo_valido(periodo)
    existente = await _periodo(alcance, periodo)
    _exigir_abierto(existente)
    await _tematica_presupuestable(alcance, categoria_id)
    fila = await _periodo_asegurado(alcance, periodo)

    actual = await _asignacion(alcance, fila, categoria_id)
    campos = datos.model_dump(exclude_unset=True)
    importe = datos.amount if "amount" in campos else (actual.allocated_amount if actual else CERO)
    await _fijar_asignacion(
        alcance,
        fila,
        categoria_id,
        importe if importe is not None else CERO,
        arrastre=datos.rollover_enabled,
        nota=datos.note if "note" in campos else None,
    )
    await alcance.sesion.commit()

    barra = await barra_del_periodo(alcance, periodo)
    for asignacion in _aplanar(barra.allocations):
        if asignacion.category_id == categoria_id:
            return asignacion
    raise NoEncontrado("La asignación no existe.")


def _aplanar(asignaciones: list[AsignacionRespuesta]) -> list[AsignacionRespuesta]:
    plano: list[AsignacionRespuesta] = []
    for asignacion in asignaciones:
        plano.append(asignacion)
        plano.extend(_aplanar(asignacion.children))
    return plano


@router.post("/budgets/{periodo}/reassign", summary="Mueve presupuesto entre dos temáticas")
async def reasignar_presupuesto(
    alcance: AlcanceEscritura, periodo: str, datos: PresupuestoReasignarCrear
) -> PresupuestoRespuesta:
    """El arrastre de la barra: suma cero y sin dejar el origen bajo lo gastado (RN-29)."""
    periodo = periodo_valido(periodo)
    existente = await _periodo(alcance, periodo)
    _exigir_abierto(existente)
    if existente is None:
        raise NoEncontrado("Este mes no tiene presupuesto que reasignar.")

    origen = await _asignacion(alcance, existente, datos.from_category_id)
    if origen is None:
        raise NoEncontrado("La temática de origen no tiene presupuesto en este mes.")
    await _tematica_presupuestable(alcance, datos.to_category_id)
    destino = await _asignacion(alcance, existente, datos.to_category_id)
    if (origen.is_locked) or (destino is not None and destino.is_locked):
        raise ReglaDeNegocio(
            "Una de las dos temáticas está bloqueada y no se puede reasignar arrastrando."
        )

    desde, hasta = rango_de(periodo)
    gastado = await gastado_por_tematica(alcance, desde, hasta)
    try:
        movimiento = reasignar(
            str(datos.from_category_id),
            origen.allocated_amount,
            str(datos.to_category_id),
            destino.allocated_amount if destino else CERO,
            datos.amount,
            gastado_origen=gastado.get(datos.from_category_id, CERO),
        )
    except ErrorPresupuesto as exc:
        raise ReglaDeNegocio(str(exc), codigo="presupuesto_negativo") from exc

    origen.allocated_amount = movimiento.asignado_origen
    await _fijar_asignacion(alcance, existente, datos.to_category_id, movimiento.asignado_destino)
    await alcance.sesion.commit()
    return await barra_del_periodo(alcance, periodo)


@router.post("/budgets/{periodo}/copy-from", summary="Copia el reparto de otro periodo")
async def copiar_presupuesto(
    alcance: AlcanceEscritura, periodo: str, datos: PresupuestoCopiarCrear
) -> PresupuestoRespuesta:
    periodo = periodo_valido(periodo)
    origen_periodo = periodo_valido(datos.source_period)
    if origen_periodo == periodo:
        raise ReglaDeNegocio("El periodo de origen y el de destino son el mismo.")
    existente = await _periodo(alcance, periodo)
    _exigir_abierto(existente)

    fuente = await _periodo(alcance, origen_periodo)
    if fuente is None:
        raise NoEncontrado("El periodo de origen no tiene presupuesto.")
    asignaciones_origen = await _asignaciones_del_periodo(alcance, fuente)
    if not asignaciones_origen:
        raise NoEncontrado("El periodo de origen no tiene ninguna asignación.")

    destino = await _periodo_asegurado(alcance, periodo)
    factor = Decimal(1)
    if datos.strategy == "proportional":
        desde_o, hasta_o = rango_de(origen_periodo)
        desde_d, hasta_d = rango_de(periodo)
        ingreso_origen = (
            fuente.expected_income
            if fuente.expected_income is not None
            else await ingresos_reales(alcance, desde_o, hasta_o)
        )
        ingreso_destino = (
            destino.expected_income
            if destino.expected_income is not None
            else await ingresos_reales(alcance, desde_d, hasta_d)
        )
        if ingreso_origen > CERO:
            factor = ingreso_destino / ingreso_origen

    for asignacion in asignaciones_origen:
        categoria = await alcance.sesion.get(Category, asignacion.category_id)
        if categoria is None or categoria.archived_at is not None:
            continue
        actual = await _asignacion(alcance, destino, asignacion.category_id)
        # `only_missing` es el comportamiento por defecto: lo que ya tiene reparto
        # no se pisa salvo que se pida `overwrite` explícitamente.
        ya_repartida = actual is not None and actual.allocated_amount > CERO
        if ya_repartida and not datos.overwrite:
            continue
        await _fijar_asignacion(
            alcance,
            destino,
            asignacion.category_id,
            asignacion.allocated_amount * factor,
            arrastre=asignacion.rollover_mode != SIN_ARRASTRE,
            origen="template",
        )
    await alcance.sesion.commit()
    return await barra_del_periodo(alcance, periodo)


@router.post("/budgets/{periodo}/distribute", summary="Reparte lo que queda sin asignar")
async def distribuir_presupuesto(
    alcance: AlcanceEscritura, periodo: str, datos: PresupuestoDistribuirCrear
) -> PresupuestoRespuesta:
    """El reparto lo propone `reparto_sugerido()`; aquí solo se elige el peso."""
    periodo = periodo_valido(periodo)
    existente = await _periodo(alcance, periodo)
    _exigir_abierto(existente)
    fila = await _periodo_asegurado(alcance, periodo)

    barra = await barra_del_periodo(alcance, periodo)
    objetivo = datos.amount if datos.amount is not None else barra.unassigned
    if objetivo <= CERO:
        raise ReglaDeNegocio("No queda nada por asignar en este mes.")

    candidatas = list(datos.category_ids)
    if not candidatas:
        candidatas = [
            asignacion.category_id
            for asignacion in _aplanar(barra.allocations)
            if not asignacion.is_locked
        ]
    if not candidatas:
        raise ReglaDeNegocio("No hay temáticas a las que repartir.")
    for categoria_id in candidatas:
        await _tematica_presupuestable(alcance, categoria_id)

    pesos = await _pesos_de_reparto(alcance, periodo, datos.strategy, candidatas, objetivo)
    propuesta = reparto_sugerido(objetivo, pesos)

    # `reparto_sugerido()` solo corrige el redondeo cuando tiene que escalar; si
    # los pesos ya sumaban el objetivo, el céntimo suelto se ajusta aquí.
    desviacion = objetivo - sum(propuesta.values(), CERO)
    if desviacion != CERO and propuesta:
        mayor = max(propuesta, key=lambda clave: propuesta[clave])
        propuesta[mayor] = propuesta[mayor] + desviacion

    actuales = {
        a.category_id: a.allocated_amount for a in await _asignaciones_del_periodo(alcance, fila)
    }
    for clave, importe in propuesta.items():
        categoria_id = uuid.UUID(clave)
        await _fijar_asignacion(
            alcance, fila, categoria_id, actuales.get(categoria_id, CERO) + importe
        )
    await alcance.sesion.commit()
    return await barra_del_periodo(alcance, periodo)


async def _pesos_de_reparto(
    alcance: AlcanceHogar,
    periodo: str,
    estrategia: str,
    candidatas: list[uuid.UUID],
    objetivo: Decimal,
) -> dict[str, Decimal]:
    """Peso de cada temática según la estrategia pedida."""
    if estrategia == "equal":
        # Peso idéntico: `reparto_sugerido()` lo escala al objetivo y cuadra el
        # redondeo en la temática de más peso.
        parte = objetivo / len(candidatas)
        return {str(categoria_id): parte for categoria_id in candidatas}

    if estrategia == "last_period_share":
        anterior = periodo_anterior(periodo)
        desde, hasta = rango_de(anterior)
    else:  # average_3m
        anterior = periodo_anterior(periodo)
        desde = primer_dia(periodo_anterior(periodo_anterior(anterior)))
        hasta = rango_de(anterior)[1]

    gastado = await gastado_por_tematica(alcance, desde, hasta)
    pesos = {
        str(categoria_id): max(gastado.get(categoria_id, CERO), CERO) for categoria_id in candidatas
    }
    total = sum(pesos.values(), CERO)
    if total <= CERO:
        parte = objetivo / len(candidatas)
        return {str(categoria_id): parte for categoria_id in candidatas}
    if total < objetivo:
        # `reparto_sugerido()` nunca propone más de lo que hay, así que cuando el
        # gasto histórico se queda corto se escala **manteniendo la proporción**
        # antes de llamarlo: lo que se reparte es el hueco de este mes.
        escala = objetivo / total
        pesos = {clave: valor * escala for clave, valor in pesos.items()}
    return pesos


@router.get("/budgets/{periodo}/rollover", summary="Arrastre entrante y de dónde viene")
async def listar_arrastre(alcance: Alcance, periodo: str) -> list[ArrastreRespuesta]:
    """F-26: `carry_in(p) = allocated(p−1) + carry_in(p−1) − spent(p−1)` (RN-32)."""
    periodo = periodo_valido(periodo)
    anterior = periodo_anterior(periodo)
    salidas = await _arrastres_de(alcance, anterior)
    if not salidas:
        return []
    tematicas = {
        categoria.id: categoria
        for categoria in await alcance.sesion.scalars(
            select(Category).where(Category.id.in_([s.categoria_id for s in salidas]))
        )
    }
    respuesta: list[ArrastreRespuesta] = []
    for salida in salidas:
        categoria = tematicas.get(salida.categoria_id)
        if categoria is None or salida.modo == SIN_ARRASTRE:
            continue
        respuesta.append(
            ArrastreRespuesta(
                category_id=salida.categoria_id,
                category=CategoriaRefRespuesta(
                    id=categoria.id, name=categoria.name, color=categoria.color_hex
                ),
                previous_period=anterior,
                previous_allocated=salida.asignado,
                previous_spent=salida.gastado,
                carried_in=salida.arrastre,
                carried_negative=salida.arrastre < CERO,
            )
        )
    return respuesta


@router.post("/budgets/{periodo}/close", summary="Cierra el periodo y consolida el arrastre")
async def cerrar_periodo(alcance: AlcanceEscritura, periodo: str) -> PresupuestoRespuesta:
    """RN-33: idempotente. Cerrarlo dos veces no duplica nada."""
    periodo = periodo_valido(periodo)
    hoy = date.today()
    # Se compara el arranque del periodo con **hoy**, no con el día 1 del mes en
    # curso: para un mes es lo mismo —solo rechaza los que empiezan más adelante—,
    # pero la semana que empezó el lunes pasado arranca un día 10 y con la
    # comparación vieja parecía del futuro.
    if inicio_de(periodo) > hoy:
        raise ReglaDeNegocio("No se puede cerrar un periodo que aún no ha empezado.")

    fila = await _periodo_asegurado(alcance, periodo)
    if fila.closed_at is not None:
        return await barra_del_periodo(alcance, periodo)

    fila.closed_at = datetime.now(UTC)
    fila.closed_by_id = alcance.usuario.id
    await alcance.sesion.flush()
    await _escribir_arrastre(alcance, periodo, aplicar=True)
    fila.rollover_applied_at = datetime.now(UTC)
    await alcance.sesion.commit()
    return await barra_del_periodo(alcance, periodo)


@router.post("/budgets/{periodo}/reopen", summary="Reabre el periodo y recalcula en cascada")
async def reabrir_periodo(alcance: AlcanceEscritura, periodo: str) -> PresupuestoRespuesta:
    periodo = periodo_valido(periodo)
    fila = await _periodo(alcance, periodo)
    if fila is None:
        raise NoEncontrado("Este mes no tiene presupuesto.")
    if fila.closed_at is None:
        return await barra_del_periodo(alcance, periodo)

    fila.rollover_applied_at = None
    fila.closed_at = None
    fila.closed_by_id = None
    await alcance.sesion.flush()
    await _recalcular_cascada(alcance, periodo)
    await alcance.sesion.commit()
    return await barra_del_periodo(alcance, periodo)


@router.get("/budgets/{periodo}/incomes", summary="Ingresos del mes que alimentan la barra")
async def listar_ingresos(
    alcance: Alcance, periodo: str, paginacion: PaginacionActual
) -> Pagina[TransaccionRespuesta]:
    """F-01. Una transferencia entrante no es un ingreso (RN-21) y no sale aquí."""
    desde, hasta = rango_de(periodo_valido(periodo))
    consulta = (
        select(Transaction)
        .where(
            Transaction.household_id == alcance.household_id,
            Transaction.kind == TipoMovimiento.INCOME.value,
            Transaction.booked_on.between(desde, hasta),
            Transaction.excluded_from_reports.is_(False),
        )
        .options(selectinload(Transaction.splits))
        .order_by(Transaction.booked_on.desc(), Transaction.id.desc())
    )
    total = int(
        await alcance.sesion.scalar(
            select(func.count()).select_from(consulta.order_by(None).subquery())
        )
        or 0
    )
    filas = list(
        (await alcance.sesion.execute(consulta.offset(paginacion.offset).limit(paginacion.limit)))
        .unique()
        .scalars()
    )
    incluir = frozenset({"account", "category", "payee"})
    contexto = await contexto_de(alcance, filas, incluir)
    return Pagina.crear(
        [respuesta_transaccion(fila, contexto, incluir) for fila in filas],
        page=paginacion.page,
        size=paginacion.size,
        total=total,
    )


__all__ = [
    "barra_del_periodo",
    "gastado_por_tematica",
    "ingresos_reales",
    "periodo_de",
    "periodo_valido",
    "rango_de",
    "router",
]
