"""Cuentas, saldos derivados, patrimonio neto y conciliación: §3.3 del contrato.

El saldo **nunca** se guarda (RN-08): sale de `vw_account_balances`, que es la
única definición de «saldo» del sistema. Por eso los endpoints de esta sección no
tienen ni una suma escrita a mano: si hubiera dos, un día darían números distintos.

Dos nombres no coinciden entre el contrato y el esquema de base de datos, y aquí
se traducen en un solo sitio:

* el tipo de cuenta que la API llama `debt` se almacena como `loan`;
* `accounts` no tiene columna de color libre, solo `color_slot`, así que el color
  hexadecimal se resuelve contra la paleta categórica de 12 del sistema de diseño.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import Row, func, select, text

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, PaginacionActual, verificar_csrf
from app.core.config import settings
from app.core.errors import Conflicto, NoEncontrado, ReglaDeNegocio
from app.models.categoria import Category
from app.models.cuenta import Account, LoanTerms, Reconciliation
from app.models.recurrente import RecurringOccurrence, RecurringRule
from app.models.transaccion import Transaction
from app.schemas.comun import Pagina
from app.schemas.cuenta import (
    AmortizacionRespuesta,
    ConciliacionRespuesta,
    ConciliarCrear,
    ConciliarRespuesta,
    CuentaActualizar,
    CuentaCrear,
    CuentaFiltro,
    CuentaRespuesta,
    CuentaSaldoRespuesta,
    CuotaAmortizacionRespuesta,
    ResumenCuentasRespuesta,
    TipoCuenta,
    TotalPorTipoRespuesta,
)

router = APIRouter(tags=["accounts"])

CERO = Decimal("0.00")

#: Paleta categórica de 12 del sistema de diseño (§2.4, juego oscuro). El orden es
#: parte de la validación de accesibilidad: no se reordena.
PALETA = (
    "#568ef9",
    "#c2520b",
    "#02a6ad",
    "#ce3344",
    "#3fac4a",
    "#b343ad",
    "#ac9008",
    "#6f5ddf",
    "#20a888",
    "#9d6000",
    "#d36c9d",
    "#026fb9",
)

#: `debt` en el contrato, `loan` en la base de datos.
TIPO_A_BD = {TipoCuenta.DEBT.value: "loan"}
TIPO_A_API = {"loan": TipoCuenta.DEBT.value}

CLASE_POR_TIPO = {
    "checking": "asset",
    "savings": "asset",
    "cash": "asset",
    "investment": "asset",
    "credit_card": "liability",
    "loan": "liability",
}

ICONO_POR_TIPO = {
    "checking": "landmark",
    "savings": "piggy-bank",
    "cash": "banknote",
    "credit_card": "credit-card",
    "investment": "trending-up",
    "loan": "handshake",
}


def _tipo_bd(tipo: TipoCuenta | str) -> str:
    valor = tipo.value if isinstance(tipo, TipoCuenta) else tipo
    return TIPO_A_BD.get(valor, valor)


def _tipo_api(tipo: str) -> TipoCuenta:
    return TipoCuenta(TIPO_A_API.get(tipo, tipo))


def _ranura_de_color(color: str | None) -> int | None:
    """Ranura de la paleta más cercana al hexadecimal pedido.

    `accounts` no guarda color libre. Un color de la propia paleta vuelve intacto;
    cualquier otro se acerca al más parecido en distancia RGB, que para doce hues
    bien separados acierta lo que el usuario esperaba.
    """
    if not color:
        return None
    objetivo = tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))
    distancias = [
        (sum((a - b) ** 2 for a, b in zip(objetivo, _rgb(hexa), strict=True)), indice)
        for indice, hexa in enumerate(PALETA, start=1)
    ]
    return min(distancias)[1]


def _rgb(hexa: str) -> tuple[int, int, int]:
    return (int(hexa[1:3], 16), int(hexa[3:5], 16), int(hexa[5:7], 16))


def _color_de_ranura(ranura: int | None) -> str | None:
    return PALETA[ranura - 1] if ranura and 1 <= ranura <= len(PALETA) else None


def _dinero(valor: Any) -> Decimal:
    if valor is None:
        return CERO
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Saldos derivados
# --------------------------------------------------------------------------- #

SALDOS = text(
    """
    SELECT account_id, working_balance, reconciled_balance, net_worth_value,
           movement_count, last_booked_on
      FROM vw_account_balances
     WHERE household_id = :hogar
    """
)


async def _saldos_del_hogar(alcance: AlcanceHogar) -> dict[uuid.UUID, Row[Any]]:
    filas = await alcance.sesion.execute(SALDOS, {"hogar": alcance.household_id})
    return {fila.account_id: fila for fila in filas}


async def _condiciones_prestamo(alcance: AlcanceHogar) -> dict[uuid.UUID, LoanTerms]:
    filas = (
        (
            await alcance.sesion.execute(
                select(LoanTerms).where(LoanTerms.household_id == alcance.household_id)
            )
        )
        .scalars()
        .all()
    )
    return {fila.account_id: fila for fila in filas}


def _fin_del_prestamo(condiciones: LoanTerms | None) -> date | None:
    if condiciones is None:
        return None
    inicio = condiciones.first_payment_on
    meses = inicio.month - 1 + condiciones.term_months
    anyo, mes = inicio.year + meses // 12, meses % 12 + 1
    return date(anyo, mes, min(inicio.day, 28))


def _respuesta_cuenta(
    cuenta: Account, saldo: Row[Any] | None, condiciones: LoanTerms | None
) -> CuentaRespuesta:
    trabajo = _dinero(saldo.working_balance if saldo else cuenta.opening_balance)
    disponible: Decimal | None = None
    if cuenta.type == "credit_card" and cuenta.credit_limit is not None:
        # El saldo de una tarjeta usada es negativo, así que sumarlo resta.
        disponible = _dinero(cuenta.credit_limit) + trabajo
    return CuentaRespuesta(
        id=cuenta.id,
        created_at=cuenta.created_at,
        updated_at=cuenta.updated_at,
        name=cuenta.name,
        type=_tipo_api(cuenta.type),
        currency=cuenta.currency,
        initial_balance=_dinero(cuenta.opening_balance),
        current_balance=trabajo,
        available_balance=disponible,
        is_liability=cuenta.account_class == "liability",
        is_archived=cuenta.archived_at is not None,
        is_excluded_from_net_worth=not cuenta.include_in_net_worth,
        color=_color_de_ranura(cuenta.color_slot),
        icon=cuenta.icon,
        opened_on=cuenta.opened_on,
        last_transaction_on=saldo.last_booked_on if saldo else None,
        transactions_count=(saldo.movement_count if saldo and saldo.movement_count else 0),
        reconciled_through=cuenta.last_reconciled_on,
        credit_limit=_dinero(cuenta.credit_limit) if cuenta.credit_limit is not None else None,
        interest_rate=condiciones.annual_rate if condiciones else None,
        monthly_payment=(
            _dinero(condiciones.payment_amount)
            if condiciones and condiciones.payment_amount is not None
            else None
        ),
        ends_on=_fin_del_prestamo(condiciones),
    )


async def _cuenta_o_404(alcance: AlcanceHogar, cuenta_id: uuid.UUID) -> Account:
    """RN-02: una cuenta de otro hogar responde 404, nunca 403."""
    cuenta = (
        await alcance.sesion.execute(
            select(Account)
            .where(Account.id == cuenta_id, Account.household_id == alcance.household_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if cuenta is None:
        raise NoEncontrado("Esa cuenta no existe.")
    return cuenta


async def _detalle(alcance: AlcanceHogar, cuenta: Account) -> CuentaRespuesta:
    # `updated_at` queda caducado tras cada UPDATE por su `onupdate=func.now()`, y
    # el archivado se escribe con SQL crudo: releer la fila es la forma barata de no
    # devolver nunca un estado anterior al que se acaba de guardar.
    await alcance.sesion.refresh(cuenta)
    saldos = await _saldos_del_hogar(alcance)
    prestamos = await _condiciones_prestamo(alcance)
    return _respuesta_cuenta(cuenta, saldos.get(cuenta.id), prestamos.get(cuenta.id))


# --------------------------------------------------------------------------- #
# Alta y baja
# --------------------------------------------------------------------------- #


async def crear_cuenta_en_hogar(alcance: AlcanceHogar, datos: CuentaCrear) -> Account:
    """Alta de una cuenta. Compartida con la puesta en marcha (`/onboarding/seed`)."""
    sesion = alcance.sesion
    tipo = _tipo_bd(datos.type)
    repetido = await sesion.scalar(
        select(func.count())
        .select_from(Account)
        .where(
            Account.household_id == alcance.household_id,
            func.lower(Account.name) == datos.name.lower(),
            Account.archived_at.is_(None),
        )
    )
    if repetido:
        raise Conflicto("Ya tienes una cuenta con ese nombre.", codigo="nombre_duplicado")

    cuenta = Account(
        household_id=alcance.household_id,
        name=datos.name,
        type=tipo,
        account_class=CLASE_POR_TIPO[tipo],
        currency=datos.currency,
        opening_balance=datos.initial_balance,
        opened_on=datos.opened_on or date.today(),
        credit_limit=datos.credit_limit,
        include_in_net_worth=not datos.is_excluded_from_net_worth,
        color_slot=_ranura_de_color(datos.color),
        icon=datos.icon or ICONO_POR_TIPO[tipo],
    )
    sesion.add(cuenta)
    await sesion.flush()

    condiciones = _condiciones_iniciales(cuenta, datos)
    if condiciones is not None:
        sesion.add(condiciones)
    return cuenta


def _condiciones_iniciales(cuenta: Account, datos: CuentaCrear) -> LoanTerms | None:
    """Crea `loan_terms` solo si hay con qué: capital, plazo e interés (F-41).

    Sin capital pendiente o sin plazo no hay cuadro de amortización posible, y
    `ck_loan_terms_amounts` rechazaría la fila; se deja para un `PATCH` posterior.
    """
    if cuenta.type != "loan":
        return None
    capital = abs(datos.initial_balance)
    if capital <= 0 or datos.interest_rate is None:
        return None
    inicio = datos.opened_on or date.today()
    plazo = _plazo_en_meses(inicio, datos.ends_on, capital, datos.monthly_payment)
    if plazo is None:
        return None
    return LoanTerms(
        household_id=cuenta.household_id,
        account_id=cuenta.id,
        principal=capital,
        annual_rate=datos.interest_rate,
        first_payment_on=inicio,
        term_months=plazo,
        payment_amount=datos.monthly_payment,
        payment_day=min(inicio.day, 28),
    )


def _plazo_en_meses(
    inicio: date, fin: date | None, capital: Decimal, cuota: Decimal | None
) -> int | None:
    if fin is not None:
        meses = (fin.year - inicio.year) * 12 + (fin.month - inicio.month)
        return max(1, min(720, meses))
    if cuota and cuota > 0:
        # Aproximación sin interés: basta para tener un plazo válido de partida.
        return max(1, min(720, int((capital / cuota).to_integral_value(ROUND_HALF_UP))))
    return None


@router.get("/accounts", response_model=Pagina[CuentaRespuesta], summary="Listar cuentas")
async def listar(
    alcance: Alcance,
    paginacion: PaginacionActual,
    filtro: Annotated[CuentaFiltro, Depends()],
) -> Pagina[CuentaRespuesta]:
    """Cuentas del hogar con su saldo actual ya calculado."""
    condiciones = [Account.household_id == alcance.household_id]
    if filtro.type:
        condiciones.append(Account.type.in_([_tipo_bd(t) for t in filtro.type]))
    if filtro.is_archived is True:
        condiciones.append(Account.archived_at.is_not(None))
    elif filtro.is_archived is False or filtro.is_archived is None:
        condiciones.append(Account.archived_at.is_(None))
    if filtro.q:
        condiciones.append(Account.name.ilike(f"%{filtro.q}%"))

    total = await alcance.sesion.scalar(
        select(func.count()).select_from(Account).where(*condiciones)
    )
    cuentas = (
        (
            await alcance.sesion.execute(
                select(Account)
                .where(*condiciones)
                .order_by(Account.sort_order, func.lower(Account.name), Account.id)
                .offset(paginacion.offset)
                .limit(paginacion.limit)
            )
        )
        .scalars()
        .all()
    )
    saldos = await _saldos_del_hogar(alcance)
    prestamos = await _condiciones_prestamo(alcance)
    return Pagina.crear(
        [_respuesta_cuenta(c, saldos.get(c.id), prestamos.get(c.id)) for c in cuentas],
        page=paginacion.page,
        size=paginacion.size,
        total=total or 0,
    )


@router.post(
    "/accounts",
    response_model=CuentaRespuesta,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verificar_csrf)],
    summary="Crear cuenta",
)
async def crear(
    datos: CuentaCrear, alcance: AlcanceEscritura, respuesta: Response
) -> CuentaRespuesta:
    cuenta = await crear_cuenta_en_hogar(alcance, datos)
    await alcance.sesion.commit()
    respuesta.headers["Location"] = f"{settings.api_prefix}/accounts/{cuenta.id}"
    return await _detalle(alcance, cuenta)


@router.get("/accounts/summary", response_model=ResumenCuentasRespuesta, summary="Patrimonio neto")
async def resumen(
    alcance: Alcance,
    as_of: Annotated[date | None, Query(description="Fecha de corte; hoy por defecto.")] = None,
) -> ResumenCuentasRespuesta:
    """Activos, pasivos y patrimonio neto actuales (F-11, RN-25).

    Los pasivos (`credit_card`, `loan`) se guardan con saldo negativo, así que su
    aportación al patrimonio se resta invirtiendo el signo una sola vez, aquí.
    """
    corte = as_of or date.today()
    cuentas = (
        (
            await alcance.sesion.execute(
                select(Account).where(
                    Account.household_id == alcance.household_id,
                    Account.archived_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    saldos = await _saldos_del_hogar(alcance)

    activos = CERO
    pasivos = CERO
    por_tipo: dict[str, list[Decimal]] = {}
    for cuenta in cuentas:
        fila = saldos.get(cuenta.id)
        valor = _dinero(fila.net_worth_value if fila else cuenta.opening_balance)
        acumulado = por_tipo.setdefault(cuenta.type, [CERO, Decimal(0)])
        acumulado[0] += valor
        acumulado[1] += 1
        if not cuenta.include_in_net_worth:
            continue
        if cuenta.account_class == "liability":
            pasivos += -valor
        else:
            activos += valor

    return ResumenCuentasRespuesta(
        as_of=corte,
        currency=settings.default_currency,
        assets=activos,
        liabilities=pasivos,
        net_worth=activos - pasivos,
        by_type=[
            TotalPorTipoRespuesta(type=_tipo_api(tipo), total=total, accounts=int(cuantas))
            for tipo, (total, cuantas) in sorted(por_tipo.items())
        ],
    )


@router.get("/accounts/{cuenta_id}", response_model=CuentaRespuesta, summary="Detalle de cuenta")
async def detalle(cuenta_id: uuid.UUID, alcance: Alcance) -> CuentaRespuesta:
    return await _detalle(alcance, await _cuenta_o_404(alcance, cuenta_id))


@router.patch(
    "/accounts/{cuenta_id}",
    response_model=CuentaRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Editar cuenta",
)
async def editar(
    cuenta_id: uuid.UUID, datos: CuentaActualizar, alcance: AlcanceEscritura
) -> CuentaRespuesta:
    """RN-07: el `type` no se puede cambiar, y el esquema ni lo acepta."""
    cuenta = await _cuenta_o_404(alcance, cuenta_id)
    cambios = datos.model_dump(exclude_unset=True)

    if "name" in cambios and cambios["name"] and cambios["name"].lower() != cuenta.name.lower():
        repetido = await alcance.sesion.scalar(
            select(func.count())
            .select_from(Account)
            .where(
                Account.household_id == alcance.household_id,
                func.lower(Account.name) == cambios["name"].lower(),
                Account.archived_at.is_(None),
                Account.id != cuenta.id,
            )
        )
        if repetido:
            raise Conflicto("Ya tienes una cuenta con ese nombre.", codigo="nombre_duplicado")
        cuenta.name = cambios["name"]

    if "currency" in cambios and cambios["currency"]:
        cuenta.currency = cambios["currency"]
    if "opened_on" in cambios and cambios["opened_on"]:
        cuenta.opened_on = cambios["opened_on"]
    if "color" in cambios:
        cuenta.color_slot = _ranura_de_color(cambios["color"])
    if "icon" in cambios:
        cuenta.icon = cambios["icon"] or ICONO_POR_TIPO[cuenta.type]
    if (
        "is_excluded_from_net_worth" in cambios
        and cambios["is_excluded_from_net_worth"] is not None
    ):
        cuenta.include_in_net_worth = not cambios["is_excluded_from_net_worth"]
    if "credit_limit" in cambios:
        if cambios["credit_limit"] is not None and cuenta.type not in ("credit_card", "loan"):
            raise ReglaDeNegocio(
                "El límite de crédito solo se aplica a tarjetas y cuentas de deuda."
            )
        cuenta.credit_limit = cambios["credit_limit"]
    if "note" in cambios:
        cuenta.notes = cambios["note"]

    await _editar_condiciones(alcance, cuenta, cambios)
    await alcance.sesion.commit()
    return await _detalle(alcance, cuenta)


async def _editar_condiciones(
    alcance: AlcanceHogar, cuenta: Account, cambios: dict[str, Any]
) -> None:
    """Interés, cuota y fin del préstamo. Solo para cuentas de deuda (F-41)."""
    campos = {"interest_rate", "monthly_payment", "ends_on"} & cambios.keys()
    if not campos:
        return
    if cuenta.type != "loan":
        raise ReglaDeNegocio(
            "El interés, la cuota y la fecha de fin solo se aplican a cuentas de deuda."
        )
    condiciones = (
        await alcance.sesion.execute(
            select(LoanTerms).where(LoanTerms.account_id == cuenta.id).limit(1)
        )
    ).scalar_one_or_none()
    if condiciones is None:
        capital = abs(_dinero(cuenta.opening_balance))
        if capital <= 0 or cambios.get("interest_rate") is None:
            raise ReglaDeNegocio(
                "Para guardar las condiciones del préstamo hace falta capital pendiente "
                "y tipo de interés."
            )
        plazo = _plazo_en_meses(
            cuenta.opened_on, cambios.get("ends_on"), capital, cambios.get("monthly_payment")
        )
        if plazo is None:
            raise ReglaDeNegocio(
                "Indica la fecha de fin o la cuota mensual para calcular el plazo."
            )
        condiciones = LoanTerms(
            household_id=cuenta.household_id,
            account_id=cuenta.id,
            principal=capital,
            annual_rate=cambios["interest_rate"],
            first_payment_on=cuenta.opened_on,
            term_months=plazo,
            payment_amount=cambios.get("monthly_payment"),
            payment_day=min(cuenta.opened_on.day, 28),
        )
        alcance.sesion.add(condiciones)
        return

    if cambios.get("interest_rate") is not None:
        condiciones.annual_rate = cambios["interest_rate"]
    if "monthly_payment" in cambios:
        condiciones.payment_amount = cambios["monthly_payment"]
    if cambios.get("ends_on"):
        plazo = _plazo_en_meses(condiciones.first_payment_on, cambios["ends_on"], CERO, None)
        if plazo is not None:
            condiciones.term_months = plazo


@router.delete(
    "/accounts/{cuenta_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verificar_csrf)],
    summary="Borrar cuenta sin movimientos",
)
async def borrar(cuenta_id: uuid.UUID, alcance: AlcanceEscritura) -> None:
    """RN-09: con movimientos no se borra, se archiva."""
    cuenta = await _cuenta_o_404(alcance, cuenta_id)
    movimientos = await alcance.sesion.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.account_id == cuenta.id)
    )
    if movimientos:
        raise Conflicto(
            "Esta cuenta tiene movimientos: archívala en lugar de borrarla para no "
            "perder el histórico."
        )
    await alcance.sesion.delete(cuenta)
    await alcance.sesion.commit()


@router.post(
    "/accounts/{cuenta_id}/archive",
    response_model=CuentaRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Archivar cuenta",
)
async def archivar(cuenta_id: uuid.UUID, alcance: AlcanceEscritura) -> CuentaRespuesta:
    cuenta = await _cuenta_o_404(alcance, cuenta_id)
    if cuenta.archived_at is None:
        cuenta.archived_at = datetime.now(UTC)
        await alcance.sesion.commit()
    return await _detalle(alcance, cuenta)


@router.post(
    "/accounts/{cuenta_id}/unarchive",
    response_model=CuentaRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Desarchivar cuenta",
)
async def desarchivar(cuenta_id: uuid.UUID, alcance: AlcanceEscritura) -> CuentaRespuesta:
    cuenta = await _cuenta_o_404(alcance, cuenta_id)
    if cuenta.archived_at is not None:
        repetido = await alcance.sesion.scalar(
            select(func.count())
            .select_from(Account)
            .where(
                Account.household_id == alcance.household_id,
                func.lower(Account.name) == cuenta.name.lower(),
                Account.archived_at.is_(None),
            )
        )
        if repetido:
            raise Conflicto(
                "Ya tienes una cuenta activa con ese nombre. Renómbrala antes de recuperar esta.",
                codigo="nombre_duplicado",
            )
        cuenta.archived_at = None
        await alcance.sesion.commit()
    return await _detalle(alcance, cuenta)


# --------------------------------------------------------------------------- #
# Saldo a una fecha
# --------------------------------------------------------------------------- #


async def _saldo_a_fecha(
    alcance: AlcanceHogar, cuenta: Account, corte: date
) -> tuple[Decimal, Decimal]:
    fila = (
        await alcance.sesion.execute(
            select(
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
                func.coalesce(
                    func.sum(Transaction.amount).filter(Transaction.status == "reconciled"), 0
                ).label("conciliado"),
            ).where(Transaction.account_id == cuenta.id, Transaction.booked_on <= corte)
        )
    ).one()
    apertura = _dinero(cuenta.opening_balance)
    return apertura + _dinero(fila.total), apertura + _dinero(fila.conciliado)


@router.get(
    "/accounts/{cuenta_id}/balance",
    response_model=CuentaSaldoRespuesta,
    summary="Saldo a una fecha",
)
async def saldo(
    cuenta_id: uuid.UUID,
    alcance: Alcance,
    as_of: Annotated[date | None, Query()] = None,
) -> CuentaSaldoRespuesta:
    """Saldo derivado a una fecha, con el desglose de pendientes (RN-08)."""
    cuenta = await _cuenta_o_404(alcance, cuenta_id)
    corte = as_of or date.today()
    total, conciliado = await _saldo_a_fecha(alcance, cuenta, corte)
    # Los vencimientos son de **esta** cuenta: la cuenta no vive en la ocurrencia
    # sino en su regla, así que hace falta el join. Sin él, la proyección de F-47
    # daba el mismo pendiente para todas las cuentas del hogar.
    pendiente = await alcance.sesion.scalar(
        select(func.coalesce(func.sum(RecurringOccurrence.expected_amount), 0))
        .join(RecurringRule, RecurringRule.id == RecurringOccurrence.recurring_rule_id)
        .where(
            RecurringOccurrence.household_id == alcance.household_id,
            RecurringOccurrence.status == "pending",
            RecurringOccurrence.due_on <= corte,
            RecurringRule.account_id == cuenta.id,
        )
    )
    return CuentaSaldoRespuesta(
        account_id=cuenta.id,
        as_of=corte,
        balance=total,
        reconciled_balance=conciliado,
        unreconciled_amount=total - conciliado,
        pending_recurring=_dinero(pendiente),
    )


# --------------------------------------------------------------------------- #
# Conciliación (F-32, RN-10)
# --------------------------------------------------------------------------- #


@router.post(
    "/accounts/{cuenta_id}/reconcile",
    response_model=ConciliarRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Conciliar con el extracto",
)
async def conciliar(
    cuenta_id: uuid.UUID, datos: ConciliarCrear, alcance: AlcanceEscritura
) -> ConciliarRespuesta:
    """No edita saldos: si hay diferencia crea un ajuste con rastro (RN-10)."""
    sesion = alcance.sesion
    cuenta = await _cuenta_o_404(alcance, cuenta_id)
    calculado, _ = await _saldo_a_fecha(alcance, cuenta, datos.statement_date)
    diferencia = _dinero(datos.statement_balance) - calculado

    ajuste: Transaction | None = None
    if diferencia != CERO and datos.create_adjustment:
        ajuste = Transaction(
            household_id=alcance.household_id,
            account_id=cuenta.id,
            # El signo lo lleva el importe; el `kind` expresa la intención (§1.7).
            kind="income" if diferencia > 0 else "expense",
            booked_on=datos.statement_date,
            amount=diferencia,
            currency=cuenta.currency,
            category_id=await _tematica_de_ajuste(alcance, datos.adjustment_category_id),
            description="Ajuste de conciliación",
            notes=datos.note,
            status="reconciled",
            created_by_id=alcance.usuario.id,
        )
        sesion.add(ajuste)
        await sesion.flush()

    conciliacion = Reconciliation(
        household_id=alcance.household_id,
        account_id=cuenta.id,
        statement_on=datos.statement_date,
        statement_balance=datos.statement_balance,
        computed_balance=calculado,
        difference=diferencia,
        # `ck_reconciliations_closed_needs_square`: cerrar descuadrado y sin ajuste
        # es justo el error que la restricción existe para impedir.
        status="closed" if diferencia == CERO or ajuste is not None else "open",
        adjustment_transaction_id=ajuste.id if ajuste else None,
        reconciled_through=datos.statement_date,
        closed_at=datetime.now(UTC) if diferencia == CERO or ajuste is not None else None,
        closed_by_id=alcance.usuario.id,
        note=datos.note,
    )
    sesion.add(conciliacion)
    await sesion.flush()

    if conciliacion.status == "closed":
        # Lo conciliado deja de estar «pendiente de cuadrar»: así el saldo
        # conciliado del siguiente extracto parte del punto correcto.
        await sesion.execute(
            text(
                "UPDATE transactions SET status = 'reconciled', reconciliation_id = :conciliacion "
                " WHERE household_id = :hogar AND account_id = :cuenta "
                "   AND booked_on <= :corte AND status <> 'reconciled'"
            ),
            {
                "conciliacion": conciliacion.id,
                "hogar": alcance.household_id,
                "cuenta": cuenta.id,
                "corte": datos.statement_date,
            },
        )
        cuenta.last_reconciled_on = datos.statement_date

    await sesion.commit()
    return ConciliarRespuesta(
        account_id=cuenta.id,
        statement_balance=datos.statement_balance,
        computed_balance=calculado,
        difference=diferencia,
        adjustment_transaction_id=ajuste.id if ajuste else None,
        reconciled_through=datos.statement_date,
    )


async def _tematica_de_ajuste(alcance: AlcanceHogar, pedida: uuid.UUID | None) -> uuid.UUID | None:
    """Temática del ajuste: la indicada o «Sin clasificar», que siempre existe."""
    if pedida is not None:
        existe = await alcance.sesion.scalar(
            select(func.count())
            .select_from(Category)
            .where(Category.id == pedida, Category.household_id == alcance.household_id)
        )
        if not existe:
            raise NoEncontrado("Esa temática no existe.")
        return pedida
    return (
        await alcance.sesion.execute(
            select(Category.id)
            .where(
                Category.household_id == alcance.household_id,
                Category.is_system.is_(True),
                Category.kind == "expense",
            )
            .limit(1)
        )
    ).scalar_one_or_none()


@router.get(
    "/accounts/{cuenta_id}/reconciliations",
    response_model=Pagina[ConciliacionRespuesta],
    summary="Historial de conciliaciones",
)
async def historial_conciliaciones(
    cuenta_id: uuid.UUID, alcance: Alcance, paginacion: PaginacionActual
) -> Pagina[ConciliacionRespuesta]:
    cuenta = await _cuenta_o_404(alcance, cuenta_id)
    total = await alcance.sesion.scalar(
        select(func.count())
        .select_from(Reconciliation)
        .where(Reconciliation.account_id == cuenta.id)
    )
    filas = (
        (
            await alcance.sesion.execute(
                select(Reconciliation)
                .where(Reconciliation.account_id == cuenta.id)
                .order_by(Reconciliation.statement_on.desc(), Reconciliation.id.desc())
                .offset(paginacion.offset)
                .limit(paginacion.limit)
            )
        )
        .scalars()
        .all()
    )
    return Pagina.crear(
        [
            ConciliacionRespuesta(
                id=fila.id,
                created_at=fila.created_at,
                updated_at=fila.updated_at,
                account_id=fila.account_id,
                statement_date=fila.statement_on,
                statement_balance=fila.statement_balance,
                computed_balance=fila.computed_balance,
                difference=fila.difference,
                adjustment_transaction_id=fila.adjustment_transaction_id,
                note=fila.note,
            )
            for fila in filas
        ],
        page=paginacion.page,
        size=paginacion.size,
        total=total or 0,
    )


# --------------------------------------------------------------------------- #
# Amortización (F-41)
# --------------------------------------------------------------------------- #


def _cuota_francesa(capital: Decimal, tipo_mensual: Decimal, meses: int) -> Decimal:
    """Cuota constante del sistema francés. Con interés cero es un reparto lineal."""
    if tipo_mensual == 0:
        return _dinero(capital / meses)
    factor = (1 + tipo_mensual) ** meses
    return _dinero(capital * tipo_mensual * factor / (factor - 1))


@router.get(
    "/accounts/{cuenta_id}/amortization",
    response_model=AmortizacionRespuesta,
    summary="Cuadro de amortización",
)
async def amortizacion(
    cuenta_id: uuid.UUID,
    alcance: Alcance,
    months: Annotated[int | None, Query(ge=1, le=720)] = None,
) -> AmortizacionRespuesta:
    """Se calcula, no se guarda: es función pura de las condiciones del préstamo."""
    cuenta = await _cuenta_o_404(alcance, cuenta_id)
    if cuenta.type != "loan":
        raise ReglaDeNegocio("El cuadro de amortización solo existe para cuentas de deuda.")
    condiciones = (
        await alcance.sesion.execute(
            select(LoanTerms).where(LoanTerms.account_id == cuenta.id).limit(1)
        )
    ).scalar_one_or_none()
    if condiciones is None:
        raise ReglaDeNegocio(
            "Esta cuenta de deuda no tiene condiciones de préstamo guardadas: "
            "indica el capital, el interés y el plazo."
        )

    plazo = min(condiciones.term_months, months or condiciones.term_months)
    # El tipo **no** es dinero: `annual_rate` es `Numeric(7,4)` y cuantizarlo a
    # céntimos se comía sus dos últimos decimales (un 2,7550 % pasaba a 2,76 % y el
    # cuadro salía con 88,93 € más de intereses en un préstamo a 20 años).
    tipo_mensual = Decimal(str(condiciones.annual_rate)) / Decimal(1200)
    cuota = (
        _dinero(condiciones.payment_amount)
        if condiciones.payment_amount is not None
        else _cuota_francesa(_dinero(condiciones.principal), tipo_mensual, condiciones.term_months)
    )

    pendiente = _dinero(condiciones.principal)
    intereses = CERO
    filas: list[CuotaAmortizacionRespuesta] = []
    for numero in range(1, plazo + 1):
        interes = _dinero(pendiente * tipo_mensual)
        principal = min(cuota - interes, pendiente)
        if principal <= 0:
            # La cuota no cubre ni los intereses: el préstamo no se amortiza nunca.
            break
        pendiente = _dinero(pendiente - principal)
        intereses += interes
        filas.append(
            CuotaAmortizacionRespuesta(
                number=numero,
                due_on=_vencimiento(condiciones.first_payment_on, numero - 1),
                payment=_dinero(principal + interes),
                principal=principal,
                interest=interes,
                remaining=pendiente,
            )
        )
        if pendiente <= 0:
            break

    return AmortizacionRespuesta(
        account_id=cuenta.id,
        principal=_dinero(condiciones.principal),
        interest_rate=condiciones.annual_rate,
        monthly_payment=cuota,
        months=len(filas),
        total_interest=intereses,
        ends_on=filas[-1].due_on if filas else None,
        rows=filas,
    )


def _vencimiento(primera: date, desplazamiento: int) -> date:
    meses = primera.month - 1 + desplazamiento
    return date(primera.year + meses // 12, meses % 12 + 1, min(primera.day, 28))
