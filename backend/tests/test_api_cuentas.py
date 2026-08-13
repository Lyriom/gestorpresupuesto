"""Pruebas de cuentas: saldo derivado, patrimonio neto, conciliación y préstamo.

El utillaje (aplicación, sesión atada a una transacción que se descarta, fábrica de
clientes) vive en `test_api_auth.py`; se importa en lugar de duplicarlo porque
`conftest.py` es compartido con el resto de módulos del proyecto.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

import test_api_auth as utillaje
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from test_api_auth import PREFIJO, cabeceras, hogar_de, registrar

from app.models.transaccion import Transaction

# Las fixtures del módulo base se reexportan por asignación y no por `import`:
# pytest las descubre igual, y así el analizador no confunde el nombre importado
# con el parámetro homónimo de cada prueba.
cliente = utillaje.cliente
navegadores = utillaje.navegadores
sesion_bd = utillaje.sesion_bd
limitador_limpio = utillaje.limitador_limpio

HOY = date.today()


async def crear_cuenta(
    cliente_http: AsyncClient, nombre: str = "Cuenta corriente", **extra: object
) -> dict:
    cuerpo = {"name": nombre, "type": "checking", "initial_balance": "100.00", **extra}
    respuesta = await cliente_http.post(
        f"{PREFIJO}/accounts", headers=cabeceras(cliente_http), json=cuerpo
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


async def crear_tematica(cliente_http: AsyncClient, nombre: str = "Alimentación") -> dict:
    respuesta = await cliente_http.post(
        f"{PREFIJO}/categories", headers=cabeceras(cliente_http), json={"name": nombre}
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


async def apuntar(
    sesion: AsyncSession,
    hogar: uuid.UUID,
    cuenta: str,
    tematica: str,
    importe: str,
    *,
    fecha: date | None = None,
    tipo: str = "expense",
    estado: str = "cleared",
) -> Transaction:
    """Inserta un movimiento directamente: `/transactions` es de otro lote."""
    movimiento = Transaction(
        household_id=hogar,
        account_id=uuid.UUID(cuenta),
        kind=tipo,
        booked_on=fecha or HOY,
        amount=Decimal(importe),
        category_id=uuid.UUID(tematica),
        description="Movimiento de prueba",
        status=estado,
    )
    sesion.add(movimiento)
    await sesion.commit()
    return movimiento


# --------------------------------------------------------------------------- #
# Alta, listado y tipos
# --------------------------------------------------------------------------- #


async def test_alta_de_cada_tipo_de_cuenta(cliente: AsyncClient) -> None:
    await registrar(cliente)
    for tipo in ("checking", "savings", "cash", "investment"):
        cuenta = await crear_cuenta(cliente, f"Cuenta {tipo}", type=tipo)
        assert cuenta["type"] == tipo
        assert cuenta["is_liability"] is False

    tarjeta = await crear_cuenta(
        cliente, "Visa", type="credit_card", initial_balance="-250.00", credit_limit="1000.00"
    )
    assert tarjeta["is_liability"] is True
    # Límite menos dispuesto: 1000 − 250.
    assert tarjeta["available_balance"] == "750.00"

    # `debt` en el contrato se guarda como `loan`, y vuelve como `debt`.
    deuda = await crear_cuenta(cliente, "Préstamo coche", type="debt", initial_balance="-8000.00")
    assert deuda["type"] == "debt"
    assert deuda["is_liability"] is True

    listado = (await cliente.get(f"{PREFIJO}/accounts")).json()
    assert listado["total"] == 6
    assert listado["items"][0]["initial_balance"].endswith(".00")


async def test_nombre_de_cuenta_repetido_da_conflicto(cliente: AsyncClient) -> None:
    await registrar(cliente)
    await crear_cuenta(cliente, "Nómina")
    repetida = await cliente.post(
        f"{PREFIJO}/accounts",
        headers=cabeceras(cliente),
        json={"name": "nómina", "type": "savings"},
    )
    assert repetida.status_code == 409
    assert repetida.json()["error"]["codigo"] == "nombre_duplicado"


async def test_el_saldo_no_es_un_campo_editable(cliente: AsyncClient) -> None:
    """RN-08: el saldo es derivado; enviarlo es un error del cliente, no algo a ignorar."""
    await registrar(cliente)
    cuenta = await crear_cuenta(cliente)
    respuesta = await cliente.patch(
        f"{PREFIJO}/accounts/{cuenta['id']}",
        headers=cabeceras(cliente),
        json={"current_balance": "999.00"},
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["codigo"] == "datos_invalidos"


async def test_cuota_mensual_solo_en_cuentas_de_deuda(cliente: AsyncClient) -> None:
    await registrar(cliente)
    respuesta = await cliente.post(
        f"{PREFIJO}/accounts",
        headers=cabeceras(cliente),
        json={"name": "Ahorro", "type": "savings", "monthly_payment": "50.00"},
    )
    assert respuesta.status_code == 422


# --------------------------------------------------------------------------- #
# Saldo derivado y patrimonio neto
# --------------------------------------------------------------------------- #


async def test_saldo_derivado_de_los_movimientos(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    cuenta = await crear_cuenta(cliente, initial_balance="1000.00")
    tematica = await crear_tematica(cliente)

    await apuntar(sesion_bd, hogar, cuenta["id"], tematica["id"], "-45.50")
    await apuntar(sesion_bd, hogar, cuenta["id"], tematica["id"], "-12.30")
    await apuntar(sesion_bd, hogar, cuenta["id"], tematica["id"], "200.00", tipo="income")

    detalle = (await cliente.get(f"{PREFIJO}/accounts/{cuenta['id']}")).json()
    assert detalle["current_balance"] == "1142.20"
    assert detalle["transactions_count"] == 3
    assert detalle["last_transaction_on"] == HOY.isoformat()


async def test_saldo_a_una_fecha_separa_lo_conciliado(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    cuenta = await crear_cuenta(cliente, initial_balance="500.00")
    tematica = await crear_tematica(cliente)

    ayer = HOY - timedelta(days=1)
    await apuntar(
        sesion_bd, hogar, cuenta["id"], tematica["id"], "-100.00", fecha=ayer, estado="reconciled"
    )
    await apuntar(sesion_bd, hogar, cuenta["id"], tematica["id"], "-25.00", estado="pending")

    hasta_ayer = (
        await cliente.get(f"{PREFIJO}/accounts/{cuenta['id']}/balance?as_of={ayer}")
    ).json()
    assert hasta_ayer["balance"] == "400.00"
    assert hasta_ayer["reconciled_balance"] == "400.00"
    assert hasta_ayer["unreconciled_amount"] == "0.00"

    hoy = (await cliente.get(f"{PREFIJO}/accounts/{cuenta['id']}/balance")).json()
    assert hoy["balance"] == "375.00"
    assert hoy["unreconciled_amount"] == "-25.00"


async def test_patrimonio_neto_resta_los_pasivos(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """RN-25: tarjetas y deuda restan; una cuenta excluida no entra en el cálculo."""
    await registrar(cliente)
    await crear_cuenta(cliente, "Nómina", initial_balance="3000.00")
    await crear_cuenta(cliente, "Visa", type="credit_card", initial_balance="-400.00")
    await crear_cuenta(cliente, "Hipoteca", type="debt", initial_balance="-95000.00")
    await crear_cuenta(
        cliente,
        "Cuenta de la comunidad",
        initial_balance="2000.00",
        is_excluded_from_net_worth=True,
    )

    resumen = (await cliente.get(f"{PREFIJO}/accounts/summary")).json()
    assert resumen["assets"] == "3000.00"
    assert resumen["liabilities"] == "95400.00"
    assert resumen["net_worth"] == "-92400.00"
    tipos = {fila["type"]: fila for fila in resumen["by_type"]}
    assert tipos["checking"]["accounts"] == 2
    assert tipos["debt"]["total"] == "-95000.00"


# --------------------------------------------------------------------------- #
# Archivado y borrado
# --------------------------------------------------------------------------- #


async def test_cuenta_con_movimientos_no_se_borra(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """RN-09: se archiva, para no perder el histórico."""
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    cuenta = await crear_cuenta(cliente)
    tematica = await crear_tematica(cliente)
    await apuntar(sesion_bd, hogar, cuenta["id"], tematica["id"], "-10.00")

    borrado = await cliente.delete(f"{PREFIJO}/accounts/{cuenta['id']}", headers=cabeceras(cliente))
    assert borrado.status_code == 409

    archivada = await cliente.post(
        f"{PREFIJO}/accounts/{cuenta['id']}/archive", headers=cabeceras(cliente)
    )
    assert archivada.status_code == 200
    assert archivada.json()["is_archived"] is True
    # Fuera de los selectores, pero con su saldo intacto.
    assert archivada.json()["current_balance"] == "90.00"
    assert (await cliente.get(f"{PREFIJO}/accounts")).json()["total"] == 0

    recuperada = await cliente.post(
        f"{PREFIJO}/accounts/{cuenta['id']}/unarchive", headers=cabeceras(cliente)
    )
    assert recuperada.json()["is_archived"] is False


async def test_cuenta_sin_movimientos_se_borra(cliente: AsyncClient) -> None:
    await registrar(cliente)
    cuenta = await crear_cuenta(cliente)
    borrado = await cliente.delete(f"{PREFIJO}/accounts/{cuenta['id']}", headers=cabeceras(cliente))
    assert borrado.status_code == 204
    assert (await cliente.get(f"{PREFIJO}/accounts/{cuenta['id']}")).status_code == 404


# --------------------------------------------------------------------------- #
# Conciliación (F-32, RN-10)
# --------------------------------------------------------------------------- #


async def test_conciliar_crea_un_ajuste_con_rastro(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    cuenta = await crear_cuenta(cliente, initial_balance="1000.00")
    tematica = await crear_tematica(cliente)
    await apuntar(sesion_bd, hogar, cuenta["id"], tematica["id"], "-100.00")

    respuesta = await cliente.post(
        f"{PREFIJO}/accounts/{cuenta['id']}/reconcile",
        headers=cabeceras(cliente),
        json={
            "statement_balance": "880.00",
            "statement_date": HOY.isoformat(),
            "create_adjustment": True,
            "adjustment_category_id": tematica["id"],
            "note": "Comisión no anotada",
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["computed_balance"] == "900.00"
    assert cuerpo["difference"] == "-20.00"
    assert cuerpo["adjustment_transaction_id"] is not None

    # El saldo no se ha «editado»: ahora cuadra porque existe el ajuste.
    detalle = (await cliente.get(f"{PREFIJO}/accounts/{cuenta['id']}")).json()
    assert detalle["current_balance"] == "880.00"
    assert detalle["reconciled_through"] == HOY.isoformat()

    historial = (await cliente.get(f"{PREFIJO}/accounts/{cuenta['id']}/reconciliations")).json()
    assert historial["total"] == 1
    assert historial["items"][0]["difference"] == "-20.00"


async def test_conciliar_cuadrado_no_crea_ajuste(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    cuenta = await crear_cuenta(cliente, initial_balance="1000.00")
    tematica = await crear_tematica(cliente)
    await apuntar(sesion_bd, hogar, cuenta["id"], tematica["id"], "-100.00")

    respuesta = await cliente.post(
        f"{PREFIJO}/accounts/{cuenta['id']}/reconcile",
        headers=cabeceras(cliente),
        json={"statement_balance": "900.00", "statement_date": HOY.isoformat()},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["difference"] == "0.00"
    assert respuesta.json()["adjustment_transaction_id"] is None


# --------------------------------------------------------------------------- #
# Condiciones del préstamo (F-41)
# --------------------------------------------------------------------------- #


async def test_condiciones_y_cuadro_de_amortizacion(cliente: AsyncClient) -> None:
    await registrar(cliente)
    cuenta = await crear_cuenta(
        cliente,
        "Hipoteca",
        type="debt",
        initial_balance="-120000.00",
        opened_on="2026-01-01",
        interest_rate=3.5,
        monthly_payment="600.00",
        ends_on="2056-01-01",
    )
    assert cuenta["interest_rate"] == "3.5000"
    assert cuenta["monthly_payment"] == "600.00"
    assert cuenta["ends_on"] == "2056-01-01"

    cuadro = (await cliente.get(f"{PREFIJO}/accounts/{cuenta['id']}/amortization?months=3")).json()
    assert cuadro["months"] == 3
    assert cuadro["principal"] == "120000.00"
    primera = cuadro["rows"][0]
    # 120.000 × 3,5 % / 12 = 350,00 de intereses el primer mes.
    assert primera["interest"] == "350.00"
    assert primera["principal"] == "250.00"
    assert primera["remaining"] == "119750.00"
    assert primera["due_on"] == "2026-01-01"
    assert Decimal(cuadro["total_interest"]) > Decimal("1000")


async def test_amortizacion_solo_para_cuentas_de_deuda(cliente: AsyncClient) -> None:
    await registrar(cliente)
    cuenta = await crear_cuenta(cliente)
    respuesta = await cliente.get(f"{PREFIJO}/accounts/{cuenta['id']}/amortization")
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["codigo"] == "regla_de_negocio"


async def test_condiciones_se_pueden_anyadir_despues(cliente: AsyncClient) -> None:
    await registrar(cliente)
    cuenta = await crear_cuenta(
        cliente, "Préstamo", type="debt", initial_balance="-6000.00", opened_on="2026-02-01"
    )
    assert cuenta["interest_rate"] is None

    editada = await cliente.patch(
        f"{PREFIJO}/accounts/{cuenta['id']}",
        headers=cabeceras(cliente),
        json={"interest_rate": 0, "monthly_payment": "500.00"},
    )
    assert editada.status_code == 200, editada.text
    cuadro = (await cliente.get(f"{PREFIJO}/accounts/{cuenta['id']}/amortization")).json()
    # Sin interés, doce cuotas de 500 amortizan los 6.000 exactos.
    assert cuadro["months"] == 12
    assert cuadro["total_interest"] == "0.00"
    assert cuadro["rows"][-1]["remaining"] == "0.00"


# --------------------------------------------------------------------------- #
# Aislamiento entre hogares (RN-01, RN-02)
# --------------------------------------------------------------------------- #


async def test_un_hogar_no_ve_ni_toca_las_cuentas_de_otro(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient], sesion_bd: AsyncSession
) -> None:
    correo_ana = await registrar(cliente, nombre="Ana")
    ana = await crear_cuenta(cliente, "Cuenta de Ana", initial_balance="5000.00")
    hogar_ana = await hogar_de(sesion_bd, correo_ana)
    tematica_ana = await crear_tematica(cliente, "Ocio de Ana")
    await apuntar(sesion_bd, hogar_ana, ana["id"], tematica_ana["id"], "-40.00")

    bruno = navegadores()
    await registrar(bruno, nombre="Bruno")
    await crear_cuenta(bruno, "Cuenta de Bruno", initial_balance="7.00")

    # El listado de Bruno solo tiene lo suyo.
    listado = (await bruno.get(f"{PREFIJO}/accounts")).json()
    assert [c["name"] for c in listado["items"]] == ["Cuenta de Bruno"]
    assert listado["total"] == 1

    # Y el patrimonio de Bruno no incluye los 5.000 de Ana.
    assert (await bruno.get(f"{PREFIJO}/accounts/summary")).json()["assets"] == "7.00"

    # Leer, editar, archivar y borrar la cuenta ajena: 404, nunca 403 (RN-02).
    ruta = f"{PREFIJO}/accounts/{ana['id']}"
    assert (await bruno.get(ruta)).status_code == 404
    assert (await bruno.get(f"{ruta}/balance")).status_code == 404
    assert (await bruno.get(f"{ruta}/reconciliations")).status_code == 404
    assert (
        await bruno.patch(ruta, headers=cabeceras(bruno), json={"name": "Mía"})
    ).status_code == 404
    assert (await bruno.post(f"{ruta}/archive", headers=cabeceras(bruno))).status_code == 404
    assert (await bruno.delete(ruta, headers=cabeceras(bruno))).status_code == 404
    assert (
        await bruno.post(
            f"{ruta}/reconcile",
            headers=cabeceras(bruno),
            json={"statement_balance": "0.00", "statement_date": HOY.isoformat()},
        )
    ).status_code == 404

    # Nada de lo intentado ha cambiado la cuenta de Ana.
    assert (await cliente.get(ruta)).json()["name"] == "Cuenta de Ana"
    assert (await cliente.get(ruta)).json()["is_archived"] is False


async def test_pedir_un_hogar_ajeno_por_parametro_da_403(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient], sesion_bd: AsyncSession
) -> None:
    """El `household_id` de la consulta se comprueba contra la pertenencia."""
    correo_ana = await registrar(cliente, nombre="Ana")
    hogar_ana = await hogar_de(sesion_bd, correo_ana)

    bruno = navegadores()
    await registrar(bruno, nombre="Bruno")
    respuesta = await bruno.get(f"{PREFIJO}/accounts?household_id={hogar_ana}")
    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["codigo"] == "sin_permiso"
