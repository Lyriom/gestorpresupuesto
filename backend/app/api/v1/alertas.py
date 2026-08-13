"""Alertas y resumen periódico: §3.16 y §5.14 del contrato.

Toda alerta es accionable y financiera (RN-73) y **idempotente por causa**
(RN-71): la clave lógica va en `alerts.dedupe_key`, así que recalcular no duplica
y una causa que desaparece cierra su aviso sola.

Nota de contrato: el vocabulario de tipos del modelo (`alerts.type`) y el del
esquema público (`TipoAlerta`) no coinciden literalmente —`unusual_expense`
frente a `unusual_spending`, `recurring_due` frente a `upcoming_charge`…—, así
que la traducción vive en `TIPO_PUBLICO` / `TIPO_INTERNO` y en un solo sitio.
"""

from __future__ import annotations

import uuid as uuidlib
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, verificar_csrf
from app.api.v1.informes import (
    Rango,
    _arbol,
    _asignado,
    _por_categoria,
    _por_comercio,
    _ref_categoria,
    fin_de,
    gastos_inusuales,
    inicio_de,
    periodo_de,
)
from app.api.v1.productos import ahora, ref_comercio, ref_producto
from app.core.errors import NoEncontrado
from app.models.alerta import Alert
from app.models.comercio import Payee
from app.models.factura import Invoice
from app.models.hogar import Household
from app.models.producto import Product, ProductPrice
from app.schemas.alerta import (
    AlertaDescartarCrear,
    AlertaFiltro,
    AlertaLeerTodasCrear,
    AlertaRecalcularCrear,
    AlertaRespuesta,
    ContadorAlertasRespuesta,
    DigestComercioRespuesta,
    DigestFiltro,
    DigestPrecioRespuesta,
    DigestRespuesta,
    DigestTematicaRespuesta,
    Severidad,
    TipoAlerta,
)
from app.schemas.comun import Pagina, ResultadoLoteRespuesta
from app.services.formato import CENTIMO, cuantizar, euros, porcentaje

router = APIRouter(dependencies=[Depends(verificar_csrf)])

CERO = Decimal("0.00")

#: Tipo del modelo → tipo del contrato.
TIPO_PUBLICO: dict[str, TipoAlerta] = {
    "budget_overspend": TipoAlerta.BUDGET_OVERSPENT,
    "budget_near_limit": TipoAlerta.BUDGET_NEAR_LIMIT,
    "product_price_increase": TipoAlerta.PRODUCT_PRICE_INCREASE,
    "recurring_price_increase": TipoAlerta.RECURRING_PRICE_INCREASE,
    "recurring_due": TipoAlerta.UPCOMING_CHARGE,
    "unusual_expense": TipoAlerta.UNUSUAL_SPENDING,
    "invoice_needs_review": TipoAlerta.INVOICE_LOW_CONFIDENCE,
    "invoice_duplicate": TipoAlerta.DUPLICATE_SUSPECTED,
    "import_duplicate": TipoAlerta.DUPLICATE_SUSPECTED,
    "goal_at_risk": TipoAlerta.GOAL_AT_RISK,
    "reconciliation_mismatch": TipoAlerta.ACCOUNT_UNRECONCILED,
    # No tiene equivalente en el contrato: se publica como cargo próximo, que es
    # la acción que el usuario tiene que tomar.
    "low_balance_forecast": TipoAlerta.UPCOMING_CHARGE,
}

#: Tipo del contrato → tipos del modelo (varios cuando el contrato agrupa).
TIPO_INTERNO: dict[TipoAlerta, tuple[str, ...]] = {
    TipoAlerta.BUDGET_OVERSPENT: ("budget_overspend",),
    TipoAlerta.BUDGET_NEAR_LIMIT: ("budget_near_limit",),
    TipoAlerta.PRODUCT_PRICE_INCREASE: ("product_price_increase",),
    TipoAlerta.RECURRING_PRICE_INCREASE: ("recurring_price_increase",),
    TipoAlerta.UNUSUAL_SPENDING: ("unusual_expense",),
    TipoAlerta.UPCOMING_CHARGE: ("recurring_due", "low_balance_forecast"),
    TipoAlerta.DUPLICATE_SUSPECTED: ("invoice_duplicate", "import_duplicate"),
    TipoAlerta.INVOICE_LOW_CONFIDENCE: ("invoice_needs_review",),
    TipoAlerta.GOAL_AT_RISK: ("goal_at_risk",),
    TipoAlerta.ACCOUNT_UNRECONCILED: ("reconciliation_mismatch",),
}


def _tipos_internos(tipos: list[TipoAlerta]) -> list[str]:
    internos: list[str] = []
    for tipo in tipos:
        valor = TIPO_INTERNO.get(tipo, ())
        internos.extend([valor] if isinstance(valor, str) else list(valor))
    return internos


# --------------------------------------------------------------------------- #
# Respuestas
# --------------------------------------------------------------------------- #


def _sujeto(aviso: Alert) -> dict[str, uuidlib.UUID | None]:
    """Reparte `subject_table`/`subject_id` en el campo que toca del contrato."""
    campos: dict[str, uuidlib.UUID | None] = {
        "transaction_id": None,
        "product_id": None,
        "recurring_id": None,
        "invoice_id": None,
        "goal_id": None,
        "account_id": None,
    }
    correspondencia = {
        "transactions": "transaction_id",
        "products": "product_id",
        "recurring_rules": "recurring_id",
        "invoices": "invoice_id",
        "goals": "goal_id",
        "accounts": "account_id",
    }
    clave = correspondencia.get(aviso.subject_table or "")
    if clave:
        campos[clave] = aviso.subject_id
    return campos


def respuesta_alerta(aviso: Alert) -> AlertaRespuesta:
    carga = aviso.payload or {}
    silencio = (aviso.delivery or {}).get("muted_until")
    importe = carga.get("amount")
    cambio = carga.get("change_pct")
    if cambio is None and carga.get("products"):
        cambio = max(producto.get("change_pct", 0) for producto in carga["products"])
    return AlertaRespuesta(
        id=aviso.id,
        type=TIPO_PUBLICO.get(aviso.type, TipoAlerta.UNUSUAL_SPENDING),
        severity=Severidad(aviso.severity),
        title=aviso.title,
        message=aviso.body or aviso.title,
        period=periodo_de(aviso.period_month) if aviso.period_month else None,
        amount=Decimal(str(importe)) if importe is not None else None,
        change_pct=float(cambio) if cambio is not None else None,
        is_read=aviso.read_at is not None,
        is_dismissed=aviso.dismissed_at is not None,
        muted_until=datetime.fromisoformat(silencio) if silencio else None,
        created_at=aviso.triggered_at,
        resolved_at=aviso.resolved_at,
        category_id=aviso.category_id,
        **_sujeto(aviso),
    )


async def _alerta_o_404(alcance: AlcanceHogar, alert_id: uuidlib.UUID) -> Alert:
    aviso = (
        await alcance.sesion.execute(
            select(Alert).where(Alert.household_id == alcance.household_id, Alert.id == alert_id)
        )
    ).scalar_one_or_none()
    if aviso is None:
        raise NoEncontrado("Ese aviso no existe.")
    return aviso


# --------------------------------------------------------------------------- #
# Bandeja
# --------------------------------------------------------------------------- #


@router.get("/alerts", tags=["alerts"], summary="Bandeja de avisos")
async def listar(
    alcance: Alcance, filtro: Annotated[AlertaFiltro, Query()]
) -> Pagina[AlertaRespuesta]:
    consulta = select(Alert).where(Alert.household_id == alcance.household_id)
    if filtro.type:
        consulta = consulta.where(Alert.type.in_(_tipos_internos(filtro.type)))
    if filtro.severity:
        consulta = consulta.where(Alert.severity.in_([s.value for s in filtro.severity]))
    if filtro.is_read is not None:
        consulta = consulta.where(
            Alert.read_at.is_not(None) if filtro.is_read else Alert.read_at.is_(None)
        )
    if filtro.is_dismissed is not None:
        consulta = consulta.where(
            Alert.dismissed_at.is_not(None) if filtro.is_dismissed else Alert.dismissed_at.is_(None)
        )
    if filtro.period:
        consulta = consulta.where(Alert.period_month == inicio_de(filtro.period))
    if filtro.date_from:
        consulta = consulta.where(func.date(Alert.triggered_at) >= filtro.date_from)
    if filtro.date_to:
        consulta = consulta.where(func.date(Alert.triggered_at) <= filtro.date_to)

    total = (
        await alcance.sesion.execute(select(func.count()).select_from(consulta.subquery()))
    ).scalar_one()
    columnas = {
        "created_at": Alert.triggered_at,
        "severity": Alert.severity,
        "type": Alert.type,
        "amount": Alert.triggered_at,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is not None:
            consulta = consulta.order_by(columna.desc() if descendente else columna.asc())
    avisos = list(
        (
            await alcance.sesion.execute(
                consulta.order_by(Alert.id).offset(filtro.desplazamiento).limit(filtro.size)
            )
        ).scalars()
    )
    return Pagina.crear(
        [respuesta_alerta(aviso) for aviso in avisos],
        page=filtro.page,
        size=filtro.size,
        total=total,
    )


@router.get("/alerts/unread-count", tags=["alerts"], summary="Contador del badge")
async def sin_leer(alcance: Alcance) -> ContadorAlertasRespuesta:
    """Un solo `COUNT` agrupado: es lo que pinta la barra lateral."""
    filas = (
        await alcance.sesion.execute(
            select(Alert.severity, func.count(Alert.id))
            .where(
                Alert.household_id == alcance.household_id,
                Alert.read_at.is_(None),
                Alert.status.in_(("new", "read")),
            )
            .group_by(Alert.severity)
        )
    ).all()
    por_severidad = {Severidad(fila[0]): fila[1] for fila in filas}
    return ContadorAlertasRespuesta(unread=sum(por_severidad.values()), by_severity=por_severidad)


@router.get("/alerts/digest", tags=["alerts"], summary="Previsualiza el resumen")
async def digest(alcance: Alcance, filtro: Annotated[DigestFiltro, Query()]) -> DigestRespuesta:
    """F-45. RN-74: se compone con los mismos datos que los informes."""
    hoy = date.today()
    if filtro.range == "week":
        desde = hoy - timedelta(days=hoy.weekday() + 7)
        hasta = desde + timedelta(days=6)
        periodo = filtro.period or periodo_de(hasta)
    else:
        periodo = filtro.period or periodo_de(hoy)
        desde, hasta = inicio_de(periodo), fin_de(periodo)
    rango = Rango(desde, hasta, periodo_de(desde), periodo_de(hasta))

    arbol = await _arbol(alcance)
    importes, _ = await _por_categoria(alcance, rango)
    asignado = await _asignado(alcance, rango)
    comercios_gasto = await _por_comercio(alcance, rango, None)
    comercios = {
        comercio.id: comercio
        for comercio in (
            await alcance.sesion.execute(
                select(Payee).where(Payee.household_id == alcance.household_id)
            )
        ).scalars()
    }

    gasto_total = sum(importes.values(), CERO)
    ingresos = await _ingresos(alcance, rango)
    tematicas = sorted(
        (
            DigestTematicaRespuesta(
                category=_ref_categoria(arbol[category_id]),
                amount=importe,
                allocated=asignado.get(category_id),
            )
            for category_id, importe in importes.items()
            if category_id in arbol
        ),
        key=lambda fila: fila.amount,
        reverse=True,
    )[:5]
    principales = sorted(
        (
            DigestComercioRespuesta(
                payee=ref_comercio(comercios.get(payee_id)) if payee_id else None,
                amount=datos["amount"],
                transactions=datos["transactions"],
            )
            for payee_id, datos in comercios_gasto.items()
        ),
        key=lambda fila: fila.amount,
        reverse=True,
    )[:5]

    subidas = [
        DigestPrecioRespuesta(
            product=ref_producto(producto),
            change_pct=float(observacion.change_pct or 0),
            new_unit_price=cuantizar(observacion.unit_price),
        )
        for observacion, producto in (
            await alcance.sesion.execute(
                select(ProductPrice, Product)
                .join(Product, Product.id == ProductPrice.product_id)
                .where(
                    ProductPrice.household_id == alcance.household_id,
                    ProductPrice.priced_on >= rango.desde,
                    ProductPrice.priced_on <= rango.hasta,
                    ProductPrice.change_pct.is_not(None),
                    ProductPrice.change_pct > 0,
                )
                .order_by(ProductPrice.change_pct.desc())
                .limit(5)
            )
        ).all()
    ]

    sin_revisar = (
        await alcance.sesion.execute(
            select(func.count(Invoice.id)).where(
                Invoice.household_id == alcance.household_id,
                Invoice.status.in_(("pending_review", "failed")),
            )
        )
    ).scalar_one()

    avisos = list(
        (
            await alcance.sesion.execute(
                select(Alert)
                .where(
                    Alert.household_id == alcance.household_id,
                    Alert.status.in_(("new", "read")),
                    func.date(Alert.triggered_at) >= rango.desde,
                )
                .order_by(Alert.triggered_at.desc())
                .limit(20)
            )
        ).scalars()
    )
    asignado_total = sum(asignado.values(), CERO)
    return DigestRespuesta(
        range=filtro.range,
        period=periodo,
        date_from=rango.desde,
        date_to=rango.hasta,
        generated_at=ahora(),
        total_expense=gasto_total,
        total_income=ingresos,
        net=(ingresos - gasto_total),
        savings_rate=(
            float(((ingresos - gasto_total) / ingresos).quantize(Decimal("0.0001")))
            if ingresos
            else None
        ),
        budget_used_pct=(
            float((gasto_total / asignado_total * 100).quantize(CENTIMO))
            if asignado_total
            else None
        ),
        top_categories=tematicas,
        top_payees=principales,
        price_increases=subidas,
        unreviewed_invoices=sin_revisar,
        alerts=[respuesta_alerta(aviso) for aviso in avisos],
    )


async def _ingresos(alcance: AlcanceHogar, rango: Rango) -> Decimal:
    from app.api.v1.informes import _gasto

    base = _gasto(alcance.household_id, rango, tipo="income").subquery()
    total = (
        await alcance.sesion.execute(select(func.coalesce(func.sum(base.c.amount), 0)))
    ).scalar_one()
    return cuantizar(Decimal(total))


@router.get("/alerts/{alert_id}", tags=["alerts"], summary="Detalle del aviso")
async def detalle(alcance: Alcance, alert_id: uuidlib.UUID) -> AlertaRespuesta:
    return respuesta_alerta(await _alerta_o_404(alcance, alert_id))


@router.post("/alerts/{alert_id}/read", tags=["alerts"], summary="Marca como leída")
async def marcar_leida(alcance: AlcanceEscritura, alert_id: uuidlib.UUID) -> AlertaRespuesta:
    aviso = await _alerta_o_404(alcance, alert_id)
    if aviso.read_at is None:
        aviso.read_at = ahora()
        if aviso.status == "new":
            aviso.status = "read"
    await alcance.sesion.commit()
    return respuesta_alerta(aviso)


@router.post("/alerts/read-all", tags=["alerts"], summary="Marca todas como leídas")
async def marcar_todas(
    alcance: AlcanceEscritura, datos: AlertaLeerTodasCrear
) -> ResultadoLoteRespuesta:
    consulta = select(Alert).where(
        Alert.household_id == alcance.household_id, Alert.read_at.is_(None)
    )
    if datos.type:
        consulta = consulta.where(Alert.type.in_(_tipos_internos(datos.type)))
    if datos.period:
        consulta = consulta.where(Alert.period_month == inicio_de(datos.period))
    avisos = list((await alcance.sesion.execute(consulta)).scalars())
    for aviso in avisos:
        aviso.read_at = ahora()
        if aviso.status == "new":
            aviso.status = "read"
    await alcance.sesion.commit()
    return ResultadoLoteRespuesta(affected=len(avisos))


@router.post(
    "/alerts/{alert_id}/dismiss",
    tags=["alerts"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Descarta y silencia la causa",
)
async def descartar(
    alcance: AlcanceEscritura, alert_id: uuidlib.UUID, datos: AlertaDescartarCrear
) -> Response:
    """RN-72: descartar silencia **esa causa** durante `mute_days`."""
    aviso = await _alerta_o_404(alcance, alert_id)
    aviso.status = "dismissed"
    aviso.dismissed_at = ahora()
    aviso.delivery = {
        **(aviso.delivery or {}),
        "muted_until": (ahora() + timedelta(days=datos.mute_days)).isoformat(),
        "muted_cause": aviso.dedupe_key,
    }
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Recálculo (RN-71)
# --------------------------------------------------------------------------- #


@router.post("/alerts/recompute", tags=["alerts"], summary="Recalcula las alertas de un periodo")
async def recalcular(
    alcance: AlcanceEscritura, datos: AlertaRecalcularCrear
) -> ResultadoLoteRespuesta:
    """Idempotente por causa: recalcular no duplica y cierra lo ya resuelto."""
    hogar = await alcance.sesion.get(Household, alcance.household_id)
    assert hogar is not None  # noqa: S101 - el alcance ya lo ha resuelto
    rango = Rango(inicio_de(datos.period), fin_de(datos.period), datos.period, datos.period)
    pedidos = _tipos_internos(datos.type) if datos.type else None

    arbol = await _arbol(alcance)
    asignado = await _asignado(alcance, rango)
    gastado, _ = await _por_categoria(alcance, rango)
    vivas: set[str] = set()
    tocadas = 0

    if pedidos is None or "budget_overspend" in pedidos or "budget_near_limit" in pedidos:
        for category_id, presupuesto in asignado.items():
            if presupuesto <= 0 or category_id not in arbol:
                continue
            gasto = gastado.get(category_id, CERO)
            proporcion = gasto / presupuesto * 100
            if proporcion >= 100:
                tipo, severidad = "budget_overspend", "critical"
                titulo = f"Te has pasado en {arbol[category_id].name}"
                cuerpo = (
                    f"Llevas {euros(gasto)} de los {euros(presupuesto)} presupuestados "
                    f"({porcentaje(gasto / presupuesto)})."
                )
            elif proporcion >= hogar.near_limit_pct:
                tipo, severidad = "budget_near_limit", "warning"
                titulo = f"{arbol[category_id].name} está al límite"
                cuerpo = (
                    f"Llevas {euros(gasto)} de {euros(presupuesto)} "
                    f"({porcentaje(gasto / presupuesto)})."
                )
            else:
                continue
            clave = f"{tipo}:{datos.period}:{category_id}"
            vivas.add(clave)
            tocadas += await _asegurar_alerta(
                alcance,
                clave=clave,
                tipo=tipo,
                severidad=severidad,
                titulo=titulo,
                cuerpo=cuerpo,
                periodo=rango.desde,
                category_id=category_id,
                carga={"amount": str(gasto), "allocated": str(presupuesto)},
            )

    if pedidos is None or "product_price_increase" in pedidos:
        subidas = (
            await alcance.sesion.execute(
                select(ProductPrice, Product)
                .join(Product, Product.id == ProductPrice.product_id)
                .where(
                    ProductPrice.household_id == alcance.household_id,
                    ProductPrice.priced_on >= rango.desde,
                    ProductPrice.priced_on <= rango.hasta,
                    ProductPrice.change_pct.is_not(None),
                    ProductPrice.change_pct >= hogar.price_alert_pct,
                )
            )
        ).all()
        for observacion, producto in subidas:
            clave = f"product_price_increase:{datos.period}:{producto.id}"
            vivas.add(clave)
            cambio = Decimal(observacion.change_pct or 0)
            tocadas += await _asegurar_alerta(
                alcance,
                clave=clave,
                tipo="product_price_increase",
                severidad="warning",
                titulo=f"{producto.name} ha subido de precio",
                cuerpo=(
                    f"Ahora cuesta {euros(observacion.unit_price)} "
                    f"({porcentaje(cambio / 100)} más)."
                ),
                periodo=rango.desde,
                carga={"change_pct": float(cambio), "product_id": str(producto.id)},
                sujeto=("products", producto.id),
            )

    if pedidos is None or "unusual_expense" in pedidos:
        # F-48. El cálculo es el mismo que el del informe de gasto inusual, así que
        # la alerta y el informe no pueden decir cosas distintas.
        for inusual in await gastos_inusuales(alcance, rango, sigma=hogar.unusual_expense_sigma):
            anomalia = inusual.anomalia
            clave = f"unusual_expense:{datos.period}:{inusual.transaction_id}"
            vivas.add(clave)
            tocadas += await _asegurar_alerta(
                alcance,
                clave=clave,
                tipo="unusual_expense",
                # No es crítica: es un gasto que puede ser perfectamente
                # voluntario, y la acción que se le pide al usuario es mirarlo.
                severidad="warning",
                titulo=f"Gasto inusual en {anomalia.referencia.grupo.nombre}",
                cuerpo=anomalia.motivo,
                periodo=rango.desde,
                category_id=inusual.category_id,
                carga={
                    "amount": str(anomalia.importe),
                    "usual_amount": str(anomalia.referencia.mediana),
                    "average_amount": str(anomalia.referencia.media),
                    "z_score": float(anomalia.z),
                    "times_usual": float(anomalia.veces) if anomalia.veces is not None else None,
                    "scope": anomalia.referencia.grupo.ambito.value,
                    "observations": anomalia.referencia.observaciones,
                },
                sujeto=("transactions", inusual.transaction_id),
            )

    # RN-71: si la causa ha desaparecido, la alerta del periodo se cierra sola.
    cerradas = 0
    for aviso in (
        (
            await alcance.sesion.execute(
                select(Alert).where(
                    Alert.household_id == alcance.household_id,
                    Alert.period_month == rango.desde,
                    Alert.status.in_(("new", "read")),
                    or_(
                        Alert.type == "budget_overspend",
                        Alert.type == "budget_near_limit",
                        Alert.type == "product_price_increase",
                        Alert.type == "unusual_expense",
                    ),
                )
            )
        )
        .scalars()
        .all()
    ):
        if aviso.dedupe_key not in vivas and aviso.dedupe_key.count(":") == 2:
            aviso.status = "resolved"
            aviso.resolved_at = ahora()
            cerradas += 1

    await alcance.sesion.commit()
    return ResultadoLoteRespuesta(affected=tocadas, skipped=cerradas)


async def _asegurar_alerta(
    alcance: AlcanceHogar,
    *,
    clave: str,
    tipo: str,
    severidad: str,
    titulo: str,
    cuerpo: str,
    periodo: date,
    category_id: uuidlib.UUID | None = None,
    carga: dict[str, Any] | None = None,
    sujeto: tuple[str, uuidlib.UUID] | None = None,
) -> int:
    """Crea o actualiza la alerta de esa causa. Nunca crea una segunda (RN-71)."""
    existente = (
        await alcance.sesion.execute(
            select(Alert).where(
                Alert.household_id == alcance.household_id, Alert.dedupe_key == clave
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        silencio = (existente.delivery or {}).get("muted_until")
        if silencio and datetime.fromisoformat(silencio) > ahora():
            # Silenciada por el usuario: no se resucita hasta que expire (RN-72).
            return 0
        existente.title = titulo
        existente.body = cuerpo
        existente.severity = severidad
        existente.payload = carga or {}
        if existente.status in ("resolved", "dismissed"):
            existente.status = "new"
            existente.resolved_at = None
            existente.dismissed_at = None
            existente.read_at = None
        existente.triggered_at = ahora()
        return 1
    alcance.sesion.add(
        Alert(
            household_id=alcance.household_id,
            type=tipo,
            severity=severidad,
            status="new",
            title=titulo,
            body=cuerpo,
            dedupe_key=clave,
            subject_table=sujeto[0] if sujeto else None,
            subject_id=sujeto[1] if sujeto else None,
            category_id=category_id,
            period_month=periodo,
            payload=carga or {},
            triggered_at=ahora(),
        )
    )
    return 1
