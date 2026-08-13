"""Transferencias entre cuentas propias (§3.6, F-09).

Una transferencia **no es un gasto ni un ingreso** (RN-21). Se modela con dos
patas de `kind = 'transfer'` que comparten `transfer_group_id`, fecha, moneda e
importe absoluto y que suman cero: así el saldo de cada cuenta sale de una única
suma y cualquier agregado que excluya `kind = 'transfer'` —el gastado del
presupuesto, los ingresos del mes, el informe por temática, el ranking de
comercios— la ignora sin más trabajo.

La comisión sí es un gasto real: se registra como una transacción de gasto
aparte, con su propia temática, en la cuenta de origen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import delete, func, or_, select

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, verificar_csrf
from app.api.v1.transacciones import (
    contar,
    cuenta_del_hogar,
    ref_cuenta,
    tematica_del_hogar,
)
from app.core.config import settings
from app.core.errors import NoEncontrado, ReglaDeNegocio
from app.models.cuenta import Account
from app.models.transaccion import Transaction
from app.schemas.comun import Pagina
from app.schemas.transaccion import (
    TipoMovimiento,
    TransferenciaActualizar,
    TransferenciaCrear,
    TransferenciaFiltro,
    TransferenciaRespuesta,
)

# Las rutas llevan su prefijo completo (`/transfers`), así que el agregador
# incluye este router sin `prefix`. `verificar_csrf` va en el router porque no
# hace nada en GET, HEAD ni OPTIONS: así no se puede olvidar en un endpoint.
router = APIRouter(tags=["transfers"], dependencies=[Depends(verificar_csrf)])

#: La comisión es un gasto, no una pata, así que no puede llevar
#: `transfer_group_id` (lo prohíbe `ck_transactions_group_only_transfer`). El
#: enlace con su transferencia se guarda en `external_id` con este prefijo, que es
#: la única columna libre que la restricción deja usar.
PREFIJO_COMISION = "transfer-fee:"


def _clave_comision(grupo: uuid.UUID) -> str:
    return f"{PREFIJO_COMISION}{grupo}"


@dataclass(slots=True)
class Transferencia:
    """Las dos patas —y la comisión, si la hubo— ya emparejadas."""

    grupo: uuid.UUID
    salida: Transaction
    entrada: Transaction
    comision: Transaction | None = None


async def _patas_del_grupo(alcance: AlcanceHogar, grupo: uuid.UUID) -> Transferencia:
    filas = list(
        (
            await alcance.sesion.execute(
                select(Transaction).where(
                    Transaction.household_id == alcance.household_id,
                    Transaction.transfer_group_id == grupo,
                )
            )
        )
        .scalars()
        .all()
    )
    salidas = [fila for fila in filas if fila.amount < 0]
    entradas = [fila for fila in filas if fila.amount > 0]
    if len(salidas) != 1 or len(entradas) != 1:
        # RN-24: una pata huérfana es un error de integridad, no un estado que la
        # API pueda alcanzar; se responde 404 en vez de devolver media verdad.
        raise NoEncontrado("La transferencia no existe.")
    comision = (
        await alcance.sesion.execute(
            select(Transaction).where(
                Transaction.household_id == alcance.household_id,
                Transaction.external_id == _clave_comision(grupo),
            )
        )
    ).scalar_one_or_none()
    return Transferencia(grupo=grupo, salida=salidas[0], entrada=entradas[0], comision=comision)


async def _cuentas_de(alcance: AlcanceHogar, ids: set[uuid.UUID]) -> dict[uuid.UUID, Account]:
    if not ids:
        return {}
    filas = await alcance.sesion.scalars(select(Account).where(Account.id.in_(ids)))
    return {cuenta.id: cuenta for cuenta in filas}


def _respuesta(
    transferencia: Transferencia, cuentas: dict[uuid.UUID, Account]
) -> TransferenciaRespuesta:
    salida, entrada = transferencia.salida, transferencia.entrada
    return TransferenciaRespuesta(
        transfer_group_id=transferencia.grupo,
        date=salida.booked_on,
        amount=abs(salida.amount),
        currency=salida.currency,
        fee=abs(transferencia.comision.amount) if transferencia.comision else None,
        from_account=ref_cuenta(cuentas.get(salida.account_id)),  # type: ignore[arg-type]
        to_account=ref_cuenta(cuentas.get(entrada.account_id)),  # type: ignore[arg-type]
        description=salida.description or None,
        note=salida.notes,
        goal_id=salida.goal_id or entrada.goal_id,
        out_transaction_id=salida.id,
        in_transaction_id=entrada.id,
        fee_transaction_id=transferencia.comision.id if transferencia.comision else None,
        created_at=salida.created_at,
    )


async def respuesta_transferencia(
    alcance: AlcanceHogar, grupo: uuid.UUID
) -> TransferenciaRespuesta:
    """La transferencia como un solo objeto, releída de la base."""
    transferencia = await _patas_del_grupo(alcance, grupo)
    cuentas = await _cuentas_de(
        alcance, {transferencia.salida.account_id, transferencia.entrada.account_id}
    )
    return _respuesta(transferencia, cuentas)


async def crear_patas(
    alcance: AlcanceHogar,
    *,
    origen: Account,
    destino: Account,
    fecha: date,
    importe: Decimal,
    moneda: str,
    descripcion: str | None = None,
    nota: str | None = None,
    objetivo_id: uuid.UUID | None = None,
    comision: Decimal | None = None,
    comision_categoria_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Crea las dos patas (y la comisión) y devuelve su `transfer_group_id`.

    La usan también los fondos objetivo, cuya aportación con cuenta **es** una
    transferencia real (RN-53), y los recurrentes de tipo traspaso.
    """
    if origen.id == destino.id:
        raise ReglaDeNegocio(
            "La cuenta de origen y la de destino no pueden ser la misma.",
            codigo="transferencia_invalida",
        )
    if importe <= 0:
        raise ReglaDeNegocio(
            "El importe de una transferencia es siempre positivo.",
            codigo="transferencia_invalida",
        )

    grupo = uuid.uuid4()
    texto = (descripcion or f"Traspaso {origen.name} → {destino.name}").strip()
    comun = {
        "household_id": alcance.household_id,
        "kind": TipoMovimiento.TRANSFER.value,
        "booked_on": fecha,
        "currency": moneda,
        "transfer_group_id": grupo,
        "description": texto,
        "notes": nota,
        "category_id": None,
        "goal_id": objetivo_id,
        "created_by_id": alcance.usuario.id,
    }
    alcance.sesion.add_all(
        [
            Transaction(account_id=origen.id, amount=-importe, **comun),
            Transaction(account_id=destino.id, amount=importe, **comun),
        ]
    )

    if comision:
        if comision_categoria_id is None:
            raise ReglaDeNegocio(
                "Indica la temática de la comisión.", codigo="transferencia_invalida"
            )
        categoria = await tematica_del_hogar(alcance, comision_categoria_id)
        if categoria.kind != "expense":
            raise ReglaDeNegocio(
                "La comisión es un gasto: elige una temática de gastos.",
                codigo="transferencia_invalida",
            )
        alcance.sesion.add(
            Transaction(
                household_id=alcance.household_id,
                account_id=origen.id,
                kind=TipoMovimiento.EXPENSE.value,
                booked_on=fecha,
                amount=-comision,
                currency=moneda,
                category_id=categoria.id,
                description=f"Comisión de traspaso · {texto}",
                external_id=_clave_comision(grupo),
                categorized_by="user",
                created_by_id=alcance.usuario.id,
            )
        )

    await alcance.sesion.flush()
    return grupo


@router.get("/transfers", summary="Transferencias agrupadas en un solo objeto")
async def listar_transferencias(
    alcance: Alcance,
    filtro: Annotated[TransferenciaFiltro, Query()],
) -> Pagina[TransferenciaRespuesta]:
    """Equivale a `/transactions?kind=transfer`, pero con las dos patas juntas."""
    grupos = (
        select(
            Transaction.transfer_group_id.label("grupo"),
            func.min(Transaction.booked_on).label("fecha"),
            func.min(Transaction.created_at).label("creado"),
            func.max(func.abs(Transaction.amount)).label("importe"),
        )
        .where(
            Transaction.household_id == alcance.household_id,
            Transaction.kind == TipoMovimiento.TRANSFER.value,
            Transaction.transfer_group_id.is_not(None),
        )
        .group_by(Transaction.transfer_group_id)
    )
    if filtro.date_from:
        grupos = grupos.where(Transaction.booked_on >= filtro.date_from)
    if filtro.date_to:
        grupos = grupos.where(Transaction.booked_on <= filtro.date_to)
    if filtro.account_id:
        grupos = grupos.where(
            Transaction.transfer_group_id.in_(
                select(Transaction.transfer_group_id).where(
                    Transaction.household_id == alcance.household_id,
                    Transaction.account_id.in_(filtro.account_id),
                    Transaction.transfer_group_id.is_not(None),
                )
            )
        )
    if filtro.goal_id:
        grupos = grupos.where(
            Transaction.transfer_group_id.in_(
                select(Transaction.transfer_group_id).where(
                    Transaction.household_id == alcance.household_id,
                    Transaction.goal_id == filtro.goal_id,
                    Transaction.transfer_group_id.is_not(None),
                )
            )
        )

    total = await contar(alcance, grupos)
    columnas = {
        "date": grupos.selected_columns.fecha,
        "amount": grupos.selected_columns.importe,
        "created_at": grupos.selected_columns.creado,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is None:
            continue
        grupos = grupos.order_by(columna.desc() if descendente else columna.asc())
    grupos = grupos.order_by(grupos.selected_columns.grupo.desc())

    filas_grupo = (
        await alcance.sesion.execute(grupos.offset(filtro.desplazamiento).limit(filtro.size))
    ).all()
    identificadores = [fila.grupo for fila in filas_grupo]
    if not identificadores:
        return Pagina.crear([], page=filtro.page, size=filtro.size, total=total)

    patas = list(
        (
            await alcance.sesion.execute(
                select(Transaction).where(
                    Transaction.household_id == alcance.household_id,
                    or_(
                        Transaction.transfer_group_id.in_(identificadores),
                        Transaction.external_id.in_(
                            [_clave_comision(grupo) for grupo in identificadores]
                        ),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    cuentas = await _cuentas_de(alcance, {pata.account_id for pata in patas})

    emparejadas: dict[uuid.UUID, dict[str, Transaction]] = {}
    for pata in patas:
        if pata.kind == TipoMovimiento.TRANSFER.value and pata.transfer_group_id:
            lado = "salida" if pata.amount < 0 else "entrada"
            emparejadas.setdefault(pata.transfer_group_id, {})[lado] = pata
        elif pata.external_id and pata.external_id.startswith(PREFIJO_COMISION):
            grupo = uuid.UUID(pata.external_id.removeprefix(PREFIJO_COMISION))
            emparejadas.setdefault(grupo, {})["comision"] = pata

    items = []
    for grupo in identificadores:
        lados = emparejadas.get(grupo, {})
        if "salida" not in lados or "entrada" not in lados:
            continue
        items.append(
            _respuesta(
                Transferencia(
                    grupo=grupo,
                    salida=lados["salida"],
                    entrada=lados["entrada"],
                    comision=lados.get("comision"),
                ),
                cuentas,
            )
        )
    return Pagina.crear(items, page=filtro.page, size=filtro.size, total=total)


@router.post("/transfers", status_code=status.HTTP_201_CREATED, summary="Crea la transferencia")
async def crear_transferencia(
    alcance: AlcanceEscritura, datos: TransferenciaCrear, respuesta: Response
) -> TransferenciaRespuesta:
    """Dos patas sin temática, que no cuentan como gasto ni como ingreso (RN-21)."""
    origen = await cuenta_del_hogar(alcance, datos.from_account_id)
    destino = await cuenta_del_hogar(alcance, datos.to_account_id)
    grupo = await crear_patas(
        alcance,
        origen=origen,
        destino=destino,
        fecha=datos.date,
        importe=datos.amount,
        moneda=datos.currency,
        descripcion=datos.description,
        nota=datos.note,
        objetivo_id=datos.goal_id,
        comision=datos.fee,
        comision_categoria_id=datos.fee_category_id,
    )
    await alcance.sesion.commit()
    respuesta.headers["Location"] = f"{settings.api_prefix}/transfers/{grupo}"
    return await respuesta_transferencia(alcance, grupo)


@router.get("/transfers/{grupo}", summary="Detalle con sus dos patas")
async def obtener_transferencia(alcance: Alcance, grupo: uuid.UUID) -> TransferenciaRespuesta:
    return await respuesta_transferencia(alcance, grupo)


@router.patch("/transfers/{grupo}", summary="Edita las dos patas a la vez")
async def editar_transferencia(
    alcance: AlcanceEscritura, grupo: uuid.UUID, datos: TransferenciaActualizar
) -> TransferenciaRespuesta:
    """RN-24: las dos patas se modifican siempre juntas, en la misma transacción."""
    transferencia = await _patas_del_grupo(alcance, grupo)
    salida, entrada = transferencia.salida, transferencia.entrada
    campos = datos.model_dump(exclude_unset=True)

    if "from_account_id" in campos and datos.from_account_id:
        salida.account_id = (await cuenta_del_hogar(alcance, datos.from_account_id)).id
    if "to_account_id" in campos and datos.to_account_id:
        entrada.account_id = (await cuenta_del_hogar(alcance, datos.to_account_id)).id
    if salida.account_id == entrada.account_id:
        raise ReglaDeNegocio(
            "La cuenta de origen y la de destino no pueden ser la misma.",
            codigo="transferencia_invalida",
        )
    if "date" in campos and datos.date:
        salida.booked_on = entrada.booked_on = datos.date
    if "amount" in campos and datos.amount is not None:
        salida.amount, entrada.amount = -datos.amount, datos.amount
    if "description" in campos:
        texto = (datos.description or "").strip()
        salida.description = entrada.description = texto
    if "note" in campos:
        salida.notes = entrada.notes = datos.note

    if "fee" in campos or "fee_category_id" in campos:
        comision = transferencia.comision
        importe = datos.fee if "fee" in campos else (abs(comision.amount) if comision else None)
        if not importe:
            if comision is not None:
                await alcance.sesion.delete(comision)
        else:
            categoria_id = datos.fee_category_id or (comision.category_id if comision else None)
            if categoria_id is None:
                raise ReglaDeNegocio(
                    "Indica la temática de la comisión.", codigo="transferencia_invalida"
                )
            categoria = await tematica_del_hogar(alcance, categoria_id)
            if comision is None:
                alcance.sesion.add(
                    Transaction(
                        household_id=alcance.household_id,
                        account_id=salida.account_id,
                        kind=TipoMovimiento.EXPENSE.value,
                        booked_on=salida.booked_on,
                        amount=-importe,
                        currency=salida.currency,
                        category_id=categoria.id,
                        description=f"Comisión de traspaso · {salida.description}",
                        external_id=_clave_comision(grupo),
                        categorized_by="user",
                        created_by_id=alcance.usuario.id,
                    )
                )
            else:
                comision.amount = -importe
                comision.category_id = categoria.id
                comision.booked_on = salida.booked_on
                comision.account_id = salida.account_id

    await alcance.sesion.commit()
    return await respuesta_transferencia(alcance, grupo)


@router.delete(
    "/transfers/{grupo}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra las dos patas",
)
async def borrar_transferencia(alcance: AlcanceEscritura, grupo: uuid.UUID) -> Response:
    """RN-24: nunca queda una pata suelta; la comisión se va con ellas."""
    await alcance.sesion.execute(
        delete(Transaction).where(
            Transaction.household_id == alcance.household_id,
            or_(
                Transaction.transfer_group_id == grupo,
                Transaction.external_id == _clave_comision(grupo),
            ),
        )
    )
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["crear_patas", "respuesta_transferencia", "router"]
