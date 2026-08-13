"""Pruebas de la fusión de temáticas (F-04) y de su reversión.

Son las aserciones del contrato de `modelo-datos.md` §4.1 convertidas en código:

* los importes totales del hogar **no cambian** en ningún periodo;
* las asignaciones de presupuesto del mismo mes **se suman**;
* el origen queda como lápida, no se borra;
* deshacer devuelve el hogar al estado exacto anterior.

Todo va contra PostgreSQL real, porque la mitad del algoritmo son disparadores,
índices parciales y `refresh_category_paths()`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import test_api_auth as utillaje
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from test_api_auth import PREFIJO, cabeceras, hogar_de, registrar, usuario_de

from app.models.alerta import Alert
from app.models.comercio import Payee
from app.models.objetivo import Goal
from app.models.presupuesto import BudgetAllocation, BudgetPeriod
from app.models.producto import Product
from app.models.recurrente import RecurringRule
from app.models.regla import CategorizationRule
from app.models.sistema import SavedView
from app.models.transaccion import Transaction, TransactionSplit

# Las fixtures del módulo base se reexportan por asignación y no por `import`:
# pytest las descubre igual, y así el analizador no confunde el nombre importado
# con el parámetro homónimo de cada prueba.
cliente = utillaje.cliente
navegadores = utillaje.navegadores
sesion_bd = utillaje.sesion_bd
limitador_limpio = utillaje.limitador_limpio

ENERO = date(2026, 1, 1)
FEBRERO = date(2026, 2, 1)
MARZO = date(2026, 3, 1)


# --------------------------------------------------------------------------- #
# Escenario
# --------------------------------------------------------------------------- #


async def _tematica(cliente_http: AsyncClient, nombre: str, madre: str | None = None) -> dict:
    cuerpo: dict = {"name": nombre}
    if madre:
        cuerpo["parent_id"] = madre
    respuesta = await cliente_http.post(
        f"{PREFIJO}/categories", headers=cabeceras(cliente_http), json=cuerpo
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


async def _periodo(sesion: AsyncSession, hogar: uuid.UUID, mes: date) -> BudgetPeriod:
    periodo = BudgetPeriod(household_id=hogar, period_month=mes)
    sesion.add(periodo)
    await sesion.flush()
    return periodo


async def _asignar(
    sesion: AsyncSession,
    hogar: uuid.UUID,
    periodo: BudgetPeriod,
    tematica: str,
    importe: str,
    *,
    arrastre: str = "0.00",
    modo: str = "none",
    nota: str | None = None,
    bloqueada: bool = False,
) -> BudgetAllocation:
    asignacion = BudgetAllocation(
        household_id=hogar,
        budget_period_id=periodo.id,
        category_id=uuid.UUID(tematica),
        allocated_amount=Decimal(importe),
        carryover_in=Decimal(arrastre),
        rollover_mode=modo,
        note=nota,
        is_locked=bloqueada,
    )
    sesion.add(asignacion)
    await sesion.flush()
    return asignacion


async def _movimiento(
    sesion: AsyncSession,
    hogar: uuid.UUID,
    cuenta: str,
    tematica: str,
    importe: str,
    fecha: date,
) -> Transaction:
    movimiento = Transaction(
        household_id=hogar,
        account_id=uuid.UUID(cuenta),
        kind="expense" if Decimal(importe) < 0 else "income",
        booked_on=fecha,
        amount=Decimal(importe),
        category_id=uuid.UUID(tematica),
        description="Movimiento",
    )
    sesion.add(movimiento)
    await sesion.flush()
    return movimiento


async def _repartida(
    sesion: AsyncSession,
    hogar: uuid.UUID,
    cuenta: str,
    reparto: list[tuple[str, str]],
    fecha: date,
) -> Transaction:
    """Transacción con splits.

    Se inserta primero con temática y sin repartos porque
    `ck_transactions_split_invariant` exige una cosa o la otra; el disparador
    `trg_transaction_splits_totals` pone `category_id` a NULL al llegar el primer
    reparto y mantiene `split_count` y `split_total`.
    """
    total = sum(Decimal(importe) for _, importe in reparto)
    movimiento = Transaction(
        household_id=hogar,
        account_id=uuid.UUID(cuenta),
        kind="expense",
        booked_on=fecha,
        amount=total,
        category_id=uuid.UUID(reparto[0][0]),
        description="Compra repartida",
    )
    sesion.add(movimiento)
    await sesion.flush()
    for numero, (tematica, importe) in enumerate(reparto, start=1):
        sesion.add(
            TransactionSplit(
                household_id=hogar,
                transaction_id=movimiento.id,
                category_id=uuid.UUID(tematica),
                amount=Decimal(importe),
                line_number=numero,
                notes=f"Línea {numero}",
            )
        )
    await sesion.flush()
    return movimiento


@pytest.fixture
async def escenario(cliente: AsyncClient, sesion_bd: AsyncSession) -> dict[str, Any]:
    """Hogar con dos temáticas hermanas y todo lo que la fusión debe reasignar."""
    correo = await registrar(cliente, nombre="Ana")
    hogar = await hogar_de(sesion_bd, correo)
    usuario = await usuario_de(sesion_bd, correo)

    cuenta = (
        await cliente.post(
            f"{PREFIJO}/accounts",
            headers=cabeceras(cliente),
            json={"name": "Nómina", "type": "checking", "initial_balance": "2000.00"},
        )
    ).json()

    origen = await _tematica(cliente, "Compra semanal")
    destino = await _tematica(cliente, "Supermercado")
    hija_origen = await _tematica(cliente, "Fruta y verdura", origen["id"])
    otra_hija = await _tematica(cliente, "Bebidas", origen["id"])

    # Transacciones simples en las dos temáticas.
    await _movimiento(sesion_bd, hogar, cuenta["id"], origen["id"], "-45.50", ENERO)
    await _movimiento(sesion_bd, hogar, cuenta["id"], origen["id"], "-30.00", FEBRERO)
    await _movimiento(sesion_bd, hogar, cuenta["id"], destino["id"], "-12.20", ENERO)
    await _movimiento(sesion_bd, hogar, cuenta["id"], hija_origen["id"], "-8.00", ENERO)

    # Una transacción con reparto en las dos: al fusionar sus líneas se unen.
    repartida = await _repartida(
        sesion_bd,
        hogar,
        cuenta["id"],
        [(origen["id"], "-60.00"), (destino["id"], "-40.00")],
        ENERO,
    )

    # Presupuesto: colisión en enero, traslado en febrero, ajeno en marzo.
    enero = await _periodo(sesion_bd, hogar, ENERO)
    febrero = await _periodo(sesion_bd, hogar, FEBRERO)
    marzo = await _periodo(sesion_bd, hogar, MARZO)
    await _asignar(
        sesion_bd, hogar, enero, origen["id"], "180.00", arrastre="10.00", nota="Del origen"
    )
    await _asignar(
        sesion_bd,
        hogar,
        enero,
        destino["id"],
        "320.00",
        arrastre="5.00",
        modo="carry",
        nota="Del destino",
    )
    await _asignar(sesion_bd, hogar, febrero, origen["id"], "150.00")
    await _asignar(sesion_bd, hogar, marzo, destino["id"], "90.00")

    # Reglas, recurrentes, objetivos, avisos, catálogo y vistas guardadas.
    sesion_bd.add(
        CategorizationRule(
            household_id=hogar,
            conditions=[{"field": "description", "op": "contains", "value": "mercadona"}],
            text_form="descripción contiene mercadona",
            set_category_id=uuid.UUID(origen["id"]),
        )
    )
    sesion_bd.add(
        RecurringRule(
            household_id=hogar,
            name="Compra online semanal",
            kind="expense",
            category_id=uuid.UUID(origen["id"]),
            expected_amount=Decimal("-55.00"),
            frequency="semanal",
            starts_on=ENERO,
            template_splits=[{"category_id": origen["id"], "amount": "-55.00"}],
        )
    )
    sesion_bd.add(
        Goal(
            household_id=hogar,
            name="Despensa",
            category_id=uuid.UUID(origen["id"]),
            target_amount=Decimal("600.00"),
        )
    )
    sesion_bd.add(
        Alert(
            household_id=hogar,
            type="budget_overspend",
            title="Te has pasado en Compra semanal",
            dedupe_key=f"budget_overspend:{origen['id']}:2026-01",
            category_id=uuid.UUID(origen["id"]),
        )
    )
    sesion_bd.add(
        Product(
            household_id=hogar,
            name="Leche entera 1 L",
            canonical_name="leche entera",
            grouping_key="leche|1l",
            category_id=uuid.UUID(origen["id"]),
        )
    )
    sesion_bd.add(
        Payee(
            household_id=hogar,
            name="Mercadona",
            normalized_name="mercadona",
            default_category_id=uuid.UUID(origen["id"]),
        )
    )
    sesion_bd.add(
        SavedView(
            household_id=hogar,
            user_id=usuario,
            entity="transactions",
            name="Compra del mes",
            filters={"category_id": origen["id"], "period": "2026-01"},
        )
    )
    await sesion_bd.commit()

    return {
        "correo": correo,
        "hogar": hogar,
        "usuario": usuario,
        "cuenta": cuenta,
        "origen": origen,
        "destino": destino,
        "hija_origen": hija_origen,
        "otra_hija": otra_hija,
        # Solo el identificador: la fusión caduca los objetos del ORM que comparten
        # sesión, y leer un atributo caducado desde la prueba no se puede esperar.
        "repartida": repartida.id,
    }


async def fusionar(
    cliente_http: AsyncClient, origenes: list[str], destino: str, **extra: object
) -> dict:
    respuesta = await cliente_http.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente_http),
        json={"source_ids": origenes, "target_id": destino, **extra},
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# --------------------------------------------------------------------------- #
# Fotos del estado, para comparar antes y después
# --------------------------------------------------------------------------- #

VOLCADOS: dict[str, str] = {
    "categories": (
        "SELECT id, parent_id, name, kind, archived_at, merged_into_id, color_slot, "
        "       is_locked, sort_order, depth, path_ids, sort_key "
        "  FROM categories WHERE household_id = :hogar ORDER BY id"
    ),
    "transactions": (
        "SELECT id, category_id, amount, split_count, split_total "
        "  FROM transactions WHERE household_id = :hogar ORDER BY id"
    ),
    "transaction_splits": (
        "SELECT id, transaction_id, category_id, amount, line_number, notes "
        "  FROM transaction_splits WHERE household_id = :hogar ORDER BY id"
    ),
    "budget_allocations": (
        "SELECT id, budget_period_id, category_id, allocated_amount, carryover_in, "
        "       rollover_mode, is_locked, note, source "
        "  FROM budget_allocations WHERE household_id = :hogar ORDER BY id"
    ),
    "categorization_rules": (
        "SELECT id, set_category_id, is_active FROM categorization_rules "
        " WHERE household_id = :hogar ORDER BY id"
    ),
    "recurring_rules": (
        "SELECT id, category_id, template_splits FROM recurring_rules "
        " WHERE household_id = :hogar ORDER BY id"
    ),
    "goals": "SELECT id, category_id FROM goals WHERE household_id = :hogar ORDER BY id",
    "products": "SELECT id, category_id FROM products WHERE household_id = :hogar ORDER BY id",
    "payees": (
        "SELECT id, default_category_id FROM payees WHERE household_id = :hogar ORDER BY id"
    ),
    "alerts": "SELECT id, category_id FROM alerts WHERE household_id = :hogar ORDER BY id",
    "saved_views": ("SELECT id, filters FROM saved_views WHERE household_id = :hogar ORDER BY id"),
}


async def volcado(sesion: AsyncSession, hogar: uuid.UUID) -> dict[str, list[tuple]]:
    """Estado completo de lo que la fusión puede tocar, sin sellos de tiempo."""
    foto: dict[str, list[tuple]] = {}
    for tabla, consulta in VOLCADOS.items():
        filas = await sesion.execute(text(consulta), {"hogar": hogar})
        foto[tabla] = [tuple(fila) for fila in filas]
    return foto


async def gasto_por_mes(sesion: AsyncSession, hogar: uuid.UUID) -> dict[date, Decimal]:
    filas = await sesion.execute(
        text(
            "SELECT period_month, sum(spent) AS gastado FROM vw_movement_lines "
            " WHERE household_id = :hogar AND kind <> 'transfer' "
            " GROUP BY period_month ORDER BY period_month"
        ),
        {"hogar": hogar},
    )
    return {fila.period_month: Decimal(str(fila.gastado)) for fila in filas}


async def asignado_por_mes(sesion: AsyncSession, hogar: uuid.UUID) -> dict[date, Decimal]:
    filas = await sesion.execute(
        text(
            "SELECT p.period_month, sum(a.allocated_amount) AS total "
            "  FROM budget_allocations a JOIN budget_periods p ON p.id = a.budget_period_id "
            " WHERE a.household_id = :hogar GROUP BY p.period_month ORDER BY p.period_month"
        ),
        {"hogar": hogar},
    )
    return {fila.period_month: Decimal(str(fila.total)) for fila in filas}


async def saldos(sesion: AsyncSession, hogar: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    filas = await sesion.execute(
        text(
            "SELECT account_id, working_balance FROM vw_account_balances "
            " WHERE household_id = :hogar ORDER BY account_id"
        ),
        {"hogar": hogar},
    )
    return {fila.account_id: Decimal(str(fila.working_balance)) for fila in filas}


# --------------------------------------------------------------------------- #
# Previsualización (§4.4)
# --------------------------------------------------------------------------- #


async def test_previsualizacion_da_cifras_concretas_y_no_escribe_nada(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    antes = await volcado(sesion_bd, escenario["hogar"])

    respuesta = await cliente.post(
        f"{PREFIJO}/categories/merge/preview",
        headers=cabeceras(cliente),
        json={"source_ids": [escenario["origen"]["id"]], "target_id": escenario["destino"]["id"]},
    )
    assert respuesta.status_code == 200, respuesta.text
    previa = respuesta.json()

    assert previa["target"]["name"] == "Supermercado"
    assert [o["name"] for o in previa["sources"]] == ["Compra semanal"]
    assert previa["transactions"] == 2
    assert previa["splits"] == 1
    assert previa["rules"] == 1
    assert previa["recurring"] == 1
    assert previa["goals"] == 1
    assert previa["products"] == 1
    assert previa["payees"] == 1
    assert previa["children_moved"] == 2
    assert previa["budget_periods"] == 2
    # 180 + 320 + 150 + 90: lo que quedará asignado al destino tras la fusión.
    assert previa["allocations_merged"] == "740.00"
    assert any("los importes se suman" in aviso for aviso in previa["conflicts"])
    assert any("reparto en las dos temáticas" in aviso for aviso in previa["conflicts"])

    sesion_bd.expire_all()
    assert await volcado(sesion_bd, escenario["hogar"]) == antes


# --------------------------------------------------------------------------- #
# Ejecución
# --------------------------------------------------------------------------- #


async def test_fusion_reasigna_todo_y_deja_lapida(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    origen, destino = escenario["origen"], escenario["destino"]
    resultado = await fusionar(cliente, [origen["id"]], destino["id"], force=True)

    assert resultado["merge_id"]
    assert resultado["undo_available_until"] > resultado["performed_at"]

    sesion_bd.expire_all()
    despues = await volcado(sesion_bd, escenario["hogar"])

    # El origen es una lápida: archivada, apuntando al destino y sin ranura.
    lapida = next(f for f in despues["categories"] if str(f[0]) == origen["id"])
    assert lapida[4] is not None  # archived_at
    assert str(lapida[5]) == destino["id"]  # merged_into_id
    assert lapida[6] is None  # color_slot liberada
    # Conserva su madre para que la miga de pan histórica siga leyéndose.
    assert lapida[1] is None

    # Y desaparece del árbol y de los selectores.
    arbol = (await cliente.get(f"{PREFIJO}/categories/tree")).json()
    assert [n["name"] for n in arbol] == ["Supermercado"]
    assert [h["name"] for h in arbol[0]["children"]] == ["Fruta y verdura", "Bebidas"]

    # Todo lo que apuntaba al origen apunta ahora al destino.
    uso = (await cliente.get(f"{PREFIJO}/categories/{destino['id']}/usage")).json()
    assert uso["transactions"] == 3
    assert uso["rules"] == 1
    assert uso["recurring"] == 1
    assert uso["goals"] == 1
    assert uso["products"] == 1
    assert uso["payees"] == 1

    # Las referencias dentro de JSONB también: el filtro guardado sigue sirviendo.
    vista = next(f for f in despues["saved_views"])
    assert vista[1]["category_id"] == destino["id"]
    recurrente = next(f for f in despues["recurring_rules"])
    assert recurrente[2][0]["category_id"] == destino["id"]


async def test_fusion_suma_los_presupuestos_del_mismo_periodo(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    """§4.5: sumar es la única resolución que deja el «disponible» como estaba."""
    hogar, origen, destino = escenario["hogar"], escenario["origen"], escenario["destino"]
    asignado_antes = await asignado_por_mes(sesion_bd, hogar)
    assert asignado_antes == {
        ENERO: Decimal("500.00"),
        FEBRERO: Decimal("150.00"),
        MARZO: Decimal("90.00"),
    }

    await fusionar(cliente, [origen["id"]], destino["id"], force=True)
    sesion_bd.expire_all()

    # Σ asignado por periodo: idéntica. Si bajara, aparecería dinero sin asignar
    # que el usuario nunca liberó.
    assert await asignado_por_mes(sesion_bd, hogar) == asignado_antes

    filas = (
        await sesion_bd.execute(
            text(
                "SELECT p.period_month, a.category_id, a.allocated_amount, a.carryover_in, "
                "       a.rollover_mode, a.is_locked, a.note, a.source "
                "  FROM budget_allocations a "
                "  JOIN budget_periods p ON p.id = a.budget_period_id "
                " WHERE a.household_id = :hogar ORDER BY p.period_month"
            ),
            {"hogar": hogar},
        )
    ).all()
    por_mes = {fila.period_month: fila for fila in filas}

    # Enero: una sola asignación, con los dos importes sumados.
    assert len([f for f in filas if f.period_month == ENERO]) == 1
    enero = por_mes[ENERO]
    assert str(enero.category_id) == destino["id"]
    assert enero.allocated_amount == Decimal("500.00")
    assert enero.carryover_in == Decimal("15.00")
    # El modo de arrastre que sobrevive es el del destino.
    assert enero.rollover_mode == "carry"
    # Las notas de las dos personas se conservan, concatenadas.
    assert enero.note == "Del destino · Del origen"
    assert enero.source == "merge"

    # Febrero no colisionaba: la asignación se traslada tal cual.
    assert por_mes[FEBRERO].allocated_amount == Decimal("150.00")
    assert str(por_mes[FEBRERO].category_id) == destino["id"]
    assert por_mes[FEBRERO].source == "user"

    # Marzo era solo del destino: intacto.
    assert por_mes[MARZO].allocated_amount == Decimal("90.00")


async def test_los_totales_del_hogar_no_cambian(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    """§4.1, punto 3: ni el gasto de ningún mes ni el saldo de ninguna cuenta."""
    hogar = escenario["hogar"]
    gasto_antes = await gasto_por_mes(sesion_bd, hogar)
    saldos_antes = await saldos(sesion_bd, hogar)
    assert gasto_antes[ENERO] == Decimal("165.70")

    await fusionar(cliente, [escenario["origen"]["id"]], escenario["destino"]["id"], force=True)
    sesion_bd.expire_all()

    assert await gasto_por_mes(sesion_bd, hogar) == gasto_antes
    assert await saldos(sesion_bd, hogar) == saldos_antes


async def test_el_colapso_de_splits_conserva_el_importe(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    repartida = escenario["repartida"]
    await fusionar(cliente, [escenario["origen"]["id"]], escenario["destino"]["id"], force=True)
    sesion_bd.expire_all()

    filas = (
        await sesion_bd.execute(
            text(
                "SELECT s.id, s.category_id, s.amount, s.notes, t.amount AS total, "
                "       t.split_count, t.split_total "
                "  FROM transaction_splits s JOIN transactions t ON t.id = s.transaction_id "
                " WHERE s.transaction_id = :movimiento ORDER BY s.line_number"
            ),
            {"movimiento": repartida},
        )
    ).all()

    # Dos líneas con la misma temática se han unido en una sola.
    assert len(filas) == 1
    superviviente = filas[0]
    assert str(superviviente.category_id) == escenario["destino"]["id"]
    assert superviviente.amount == Decimal("-100.00")
    # `split_total = amount` sigue cumpliéndose: hay menos filas, no menos dinero.
    assert superviviente.split_total == superviviente.total == Decimal("-100.00")
    assert superviviente.split_count == 1
    # Y no se pierde texto escrito por una persona.
    assert "Línea 1" in superviviente.notes and "Línea 2" in superviviente.notes


async def test_las_hijas_homonimas_se_fusionan_tambien(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    """§4.6: la colisión de nombre no revienta el índice único, se resuelve."""
    origen, destino = escenario["origen"], escenario["destino"]
    # El destino recibe una hija con el mismo nombre que una del origen.
    gemela = await _tematica(cliente, "Fruta y verdura", destino["id"])

    previa = (
        await cliente.post(
            f"{PREFIJO}/categories/merge/preview",
            headers=cabeceras(cliente),
            json={"source_ids": [origen["id"]], "target_id": destino["id"]},
        )
    ).json()
    assert any("existe en las dos temáticas" in aviso for aviso in previa["conflicts"])

    await fusionar(cliente, [origen["id"]], destino["id"], force=True)
    sesion_bd.expire_all()

    arbol = (await cliente.get(f"{PREFIJO}/categories/tree")).json()
    assert [n["name"] for n in arbol] == ["Supermercado"]
    # Una sola «Fruta y verdura», la del destino: la del origen se ha fusionado en
    # ella y su transacción de 8 € ha viajado con ella.
    hijas = [h["name"] for h in arbol[0]["children"]]
    assert hijas.count("Fruta y verdura") == 1
    assert sorted(hijas) == ["Bebidas", "Fruta y verdura"]
    uso = (await cliente.get(f"{PREFIJO}/categories/{gemela['id']}/usage")).json()
    assert uso["transactions"] == 1

    # La fusión hija cuelga de la madre: el historial muestra una sola operación.
    historial = (await cliente.get(f"{PREFIJO}/categories/merges")).json()
    assert historial["total"] == 1


async def test_fusion_multiple_en_una_sola_operacion(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    tercera = await _tematica(cliente, "Ultramarinos")
    await _movimiento(
        sesion_bd, escenario["hogar"], escenario["cuenta"]["id"], tercera["id"], "-5.00", ENERO
    )
    await sesion_bd.commit()

    resultado = await fusionar(
        cliente,
        [escenario["origen"]["id"], tercera["id"]],
        escenario["destino"]["id"],
        force=True,
    )
    assert sorted(o["name"] for o in resultado["sources"]) == [
        "Compra semanal",
        "Ultramarinos",
    ]
    assert resultado["transactions"] == 3

    historial = (await cliente.get(f"{PREFIJO}/categories/merges")).json()
    assert historial["total"] == 1
    assert sorted(o["name"] for o in historial["items"][0]["sources"]) == [
        "Compra semanal",
        "Ultramarinos",
    ]


# --------------------------------------------------------------------------- #
# Validaciones (§4.3, RN-17 a RN-20)
# --------------------------------------------------------------------------- #


async def test_no_se_puede_fusionar_con_un_descendiente(
    cliente: AsyncClient, escenario: dict[str, Any]
) -> None:
    """RN-18: destruiría la jerarquía. Se comprueba con `path_ids`."""
    madre, hija = escenario["origen"], escenario["hija_origen"]

    previa = await cliente.post(
        f"{PREFIJO}/categories/merge/preview",
        headers=cabeceras(cliente),
        json={"source_ids": [madre["id"]], "target_id": hija["id"]},
    )
    assert previa.status_code == 422
    assert previa.json()["error"]["codigo"] == "fusion_invalida"
    assert "subtemática" in previa.json()["error"]["mensaje"]

    ejecutada = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [madre["id"]], "target_id": hija["id"]},
    )
    assert ejecutada.status_code == 422
    assert ejecutada.json()["error"]["codigo"] == "fusion_invalida"

    # Ni siquiera con una nieta: la comprobación mira toda la rama.
    nieta = await _tematica(cliente, "Manzanas", hija["id"])
    profunda = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [madre["id"]], "target_id": nieta["id"]},
    )
    assert profunda.status_code == 422
    assert profunda.json()["error"]["codigo"] == "fusion_invalida"

    # Al revés sí vale: fusionar la hija en su madre es legítimo.
    correcta = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [nieta["id"]], "target_id": madre["id"], "force": True},
    )
    assert correcta.status_code == 200, correcta.text


async def test_no_se_puede_fusionar_hacia_una_lapida_ni_repetir(
    cliente: AsyncClient, escenario: dict[str, Any]
) -> None:
    origen, destino = escenario["origen"], escenario["destino"]
    otra = await _tematica(cliente, "Otra tienda")
    await fusionar(cliente, [origen["id"]], destino["id"], force=True)

    hacia_lapida = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [otra["id"]], "target_id": origen["id"]},
    )
    assert hacia_lapida.status_code == 422
    assert hacia_lapida.json()["error"]["codigo"] == "fusion_invalida"

    repetida = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [origen["id"]], "target_id": otra["id"]},
    )
    assert repetida.status_code == 409


async def test_la_tematica_del_sistema_no_se_absorbe(cliente: AsyncClient) -> None:
    await registrar(cliente)
    await cliente.post(
        f"{PREFIJO}/onboarding/seed", headers=cabeceras(cliente), json={"preset": "es_basico"}
    )
    todas = (await cliente.get(f"{PREFIJO}/categories?size=200")).json()["items"]
    sistema = next(c for c in todas if c["is_default"])
    otra = next(c for c in todas if not c["is_default"] and c["kind"] == sistema["kind"])

    respuesta = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [sistema["id"]], "target_id": otra["id"]},
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["codigo"] == "fusion_invalida"


async def test_un_periodo_cerrado_bloquea_salvo_force(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    """RN-20: el informe histórico cambia, pero avisado y a petición del usuario."""
    await sesion_bd.execute(
        text(
            "UPDATE budget_periods SET closed_at = now() "
            " WHERE household_id = :hogar AND period_month = :mes"
        ),
        {"hogar": escenario["hogar"], "mes": ENERO},
    )
    await sesion_bd.commit()

    previa = (
        await cliente.post(
            f"{PREFIJO}/categories/merge/preview",
            headers=cabeceras(cliente),
            json={
                "source_ids": [escenario["origen"]["id"]],
                "target_id": escenario["destino"]["id"],
            },
        )
    ).json()
    assert any("cerrados" in aviso for aviso in previa["conflicts"])

    bloqueada = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [escenario["origen"]["id"]], "target_id": escenario["destino"]["id"]},
    )
    assert bloqueada.status_code == 409
    assert bloqueada.json()["error"]["codigo"] == "periodo_cerrado"
    assert "2026-01" in bloqueada.json()["error"]["mensaje"]

    await fusionar(cliente, [escenario["origen"]["id"]], escenario["destino"]["id"], force=True)


async def test_un_invitado_de_solo_lectura_no_puede_fusionar(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    await sesion_bd.execute(
        text("UPDATE household_members SET role = 'viewer' WHERE household_id = :hogar"),
        {"hogar": escenario["hogar"]},
    )
    await sesion_bd.commit()

    respuesta = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [escenario["origen"]["id"]], "target_id": escenario["destino"]["id"]},
    )
    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["codigo"] == "sin_permiso"


# --------------------------------------------------------------------------- #
# Deshacer (§4.9)
# --------------------------------------------------------------------------- #


async def test_deshacer_devuelve_el_hogar_al_estado_exacto_anterior(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    """La aserción más importante del módulo: estado idéntico, tabla por tabla."""
    hogar = escenario["hogar"]
    antes = await volcado(sesion_bd, hogar)
    gasto_antes = await gasto_por_mes(sesion_bd, hogar)
    asignado_antes = await asignado_por_mes(sesion_bd, hogar)

    resultado = await fusionar(
        cliente, [escenario["origen"]["id"]], escenario["destino"]["id"], force=True
    )
    sesion_bd.expire_all()
    assert await volcado(sesion_bd, hogar) != antes

    deshecha = await cliente.post(
        f"{PREFIJO}/categories/merges/{resultado['merge_id']}/undo",
        headers=cabeceras(cliente),
    )
    assert deshecha.status_code == 200, deshecha.text
    sesion_bd.expire_all()

    despues = await volcado(sesion_bd, hogar)
    for tabla in VOLCADOS:
        assert despues[tabla] == antes[tabla], f"la tabla {tabla} no ha vuelto a su estado"
    assert await gasto_por_mes(sesion_bd, hogar) == gasto_antes
    assert await asignado_por_mes(sesion_bd, hogar) == asignado_antes

    # Y el árbol vuelve a tener las dos temáticas con sus hijas.
    arbol = (await cliente.get(f"{PREFIJO}/categories/tree")).json()
    assert sorted(n["name"] for n in arbol) == ["Compra semanal", "Supermercado"]
    compra = next(n for n in arbol if n["name"] == "Compra semanal")
    assert sorted(h["name"] for h in compra["children"]) == ["Bebidas", "Fruta y verdura"]


async def test_deshacer_una_fusion_con_hijas_homonimas(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    """Deshacer la madre deshace las hijas: son una unidad atómica."""
    hogar = escenario["hogar"]
    await _tematica(cliente, "Fruta y verdura", escenario["destino"]["id"])
    antes = await volcado(sesion_bd, hogar)

    resultado = await fusionar(
        cliente, [escenario["origen"]["id"]], escenario["destino"]["id"], force=True
    )
    deshecha = await cliente.post(
        f"{PREFIJO}/categories/merges/{resultado['merge_id']}/undo",
        headers=cabeceras(cliente),
    )
    assert deshecha.status_code == 200, deshecha.text
    sesion_bd.expire_all()

    despues = await volcado(sesion_bd, hogar)
    for tabla in VOLCADOS:
        assert despues[tabla] == antes[tabla], f"la tabla {tabla} no ha vuelto a su estado"

    # Las dos operaciones, madre e hija, quedan marcadas como revertidas.
    estados = (
        (
            await sesion_bd.execute(
                text("SELECT status FROM merge_operations WHERE household_id = :hogar"),
                {"hogar": hogar},
            )
        )
        .scalars()
        .all()
    )
    assert set(estados) == {"reverted"}


async def test_deshacer_dos_veces_da_conflicto(
    cliente: AsyncClient, escenario: dict[str, Any]
) -> None:
    resultado = await fusionar(
        cliente, [escenario["origen"]["id"]], escenario["destino"]["id"], force=True
    )
    ruta = f"{PREFIJO}/categories/merges/{resultado['merge_id']}/undo"
    assert (await cliente.post(ruta, headers=cabeceras(cliente))).status_code == 200
    repetido = await cliente.post(ruta, headers=cabeceras(cliente))
    assert repetido.status_code == 409
    assert "ya se ha deshecho" in repetido.json()["error"]["mensaje"]


async def test_no_se_deshace_si_el_destino_se_fusiono_despues(
    cliente: AsyncClient, escenario: dict[str, Any]
) -> None:
    origen, destino = escenario["origen"], escenario["destino"]
    final = await _tematica(cliente, "Alimentación")

    primera = await fusionar(cliente, [origen["id"]], destino["id"], force=True)
    await fusionar(cliente, [destino["id"]], final["id"], force=True)

    respuesta = await cliente.post(
        f"{PREFIJO}/categories/merges/{primera['merge_id']}/undo", headers=cabeceras(cliente)
    )
    assert respuesta.status_code == 409
    assert "Deshaz primero" in respuesta.json()["error"]["mensaje"]


async def test_el_plazo_de_treinta_dias_caduca(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    resultado = await fusionar(
        cliente, [escenario["origen"]["id"]], escenario["destino"]["id"], force=True
    )
    await sesion_bd.execute(
        text(
            "UPDATE merge_operations SET undo_deadline = now() - interval '1 day' "
            " WHERE id = :operacion"
        ),
        {"operacion": uuid.UUID(resultado["merge_id"])},
    )
    await sesion_bd.commit()

    historial = (await cliente.get(f"{PREFIJO}/categories/merges")).json()
    assert historial["items"][0]["can_undo"] is False

    respuesta = await cliente.post(
        f"{PREFIJO}/categories/merges/{resultado['merge_id']}/undo", headers=cabeceras(cliente)
    )
    assert respuesta.status_code == 409
    assert "treinta días" in respuesta.json()["error"]["mensaje"]


async def test_el_historial_de_fusiones_cuenta_las_filas(
    cliente: AsyncClient, escenario: dict[str, Any]
) -> None:
    resultado = await fusionar(
        cliente, [escenario["origen"]["id"]], escenario["destino"]["id"], force=True
    )
    historial = (await cliente.get(f"{PREFIJO}/categories/merges")).json()
    assert historial["total"] == 1
    fila = historial["items"][0]
    assert fila["id"] == resultado["merge_id"]
    assert fila["target"]["name"] == "Supermercado"
    assert fila["rows_changed"] > 10
    assert fila["can_undo"] is True
    assert fila["undone_at"] is None


async def test_una_fusion_de_otro_hogar_no_se_puede_deshacer(
    cliente: AsyncClient,
    navegadores: Callable[[], AsyncClient],
    escenario: dict[str, Any],
) -> None:
    """RN-02: la operación de otro hogar no existe para quien no es de ese hogar."""
    resultado = await fusionar(
        cliente, [escenario["origen"]["id"]], escenario["destino"]["id"], force=True
    )

    bruno = navegadores()
    await registrar(bruno, nombre="Bruno")
    assert (await bruno.get(f"{PREFIJO}/categories/merges")).json()["total"] == 0
    respuesta = await bruno.post(
        f"{PREFIJO}/categories/merges/{resultado['merge_id']}/undo", headers=cabeceras(bruno)
    )
    assert respuesta.status_code == 404


async def test_no_se_deshace_si_otra_fusion_posterior_toco_las_mismas_filas(
    cliente: AsyncClient, sesion_bd: AsyncSession, escenario: dict[str, Any]
) -> None:
    """§4.9: nunca se restaura un valor obsoleto, y se dice qué fusión lo cambió."""
    hogar, origen, destino = escenario["hogar"], escenario["origen"], escenario["destino"]
    primera = await fusionar(cliente, [origen["id"]], destino["id"], force=True)

    # Una segunda fusión que vuelve a tocar la asignación de enero del destino.
    tercera = await _tematica(cliente, "Ultramarinos")
    enero = (
        await sesion_bd.execute(
            text(
                "SELECT id FROM budget_periods WHERE household_id = :hogar  AND period_month = :mes"
            ),
            {"hogar": hogar, "mes": ENERO},
        )
    ).scalar_one()
    sesion_bd.add(
        BudgetAllocation(
            household_id=hogar,
            budget_period_id=enero,
            category_id=uuid.UUID(tercera["id"]),
            allocated_amount=Decimal("25.00"),
        )
    )
    await sesion_bd.commit()
    await fusionar(cliente, [tercera["id"]], destino["id"], force=True)

    respuesta = await cliente.post(
        f"{PREFIJO}/categories/merges/{primera['merge_id']}/undo", headers=cabeceras(cliente)
    )
    assert respuesta.status_code == 409
    mensaje = respuesta.json()["error"]["mensaje"]
    assert "Ultramarinos" in mensaje
    assert "Deshaz esa primero" in mensaje
