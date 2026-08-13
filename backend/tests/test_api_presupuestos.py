"""Pruebas de la API de presupuestos: la barra, el reparto, el arrastre y el cierre.

La comprobación central es que **la barra devuelve exactamente los mismos números
que `app/services/presupuesto.py`**: si la API y el servicio pudieran divergir,
la pantalla principal y los informes contarían historias distintas.

El montaje (base de datos, hogar, cliente HTTP) se importa de
`test_api_transacciones.py`, que es donde vive.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.presupuesto import (
    EntradaCategoria,
    EstadoSegmento,
    calcular_barra,
    periodo_anterior,
)
from tests.test_api_transacciones import (  # noqa: F401 - fixtures compartidas
    HOY,
    PERIODO,
    RUTA,
    Entorno,
    alta_gasto,
    cliente,
    cliente_de,
    codigo_de,
    crear_hogar,
    crear_tematica,
    entorno,
    esquema,
    motor,
    sesion,
)

# Las fixtures importadas tienen que vivir en el espacio de nombres de este
# módulo para que pytest las resuelva; se reexportan para dejarlo explícito.
__all__ = ["cliente", "cliente_de", "entorno", "esquema", "motor", "sesion"]

ANTERIOR = periodo_anterior(PERIODO)


def primer_dia(periodo: str) -> date:
    anyo, mes = (int(parte) for parte in periodo.split("-"))
    return date(anyo, mes, 1)


def aplanar(asignaciones: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """El árbol de asignaciones indexado por temática, para poder comparar."""
    plano: dict[str, dict[str, Any]] = {}
    for asignacion in asignaciones:
        plano[asignacion["category_id"]] = asignacion
        plano.update(aplanar(asignacion["children"]))
    return plano


async def ingresar(cliente: AsyncClient, entorno: Entorno, importe: str, cuando: date) -> None:
    respuesta = await cliente.post(
        f"{RUTA}/transactions",
        json={
            "kind": "income",
            "account_id": str(entorno.corriente.id),
            "date": cuando.isoformat(),
            "amount": importe,
            "category_id": str(entorno.nomina.id),
        },
    )
    assert respuesta.status_code == 201, respuesta.text


async def asignar(
    cliente: AsyncClient,
    periodo: str,
    reparto: list[tuple[uuid.UUID, str]],
    *,
    arrastre: bool = False,
) -> dict[str, Any]:
    respuesta = await cliente.put(
        f"{RUTA}/budgets/{periodo}/allocations",
        json={
            "allocations": [
                {
                    "category_id": str(categoria_id),
                    "amount": importe,
                    "rollover_enabled": arrastre,
                }
                for categoria_id, importe in reparto
            ]
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


# --------------------------------------------------------------------------- #
# El payload de la barra
# --------------------------------------------------------------------------- #


async def test_la_barra_devuelve_los_mismos_numeros_que_el_servicio(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """La API no calcula: alimenta a `calcular_barra()` y traduce su salida."""
    await ingresar(cliente, entorno, "2000.00", HOY)
    await asignar(
        cliente,
        PERIODO,
        [(entorno.alimentacion.id, "500.00"), (entorno.ocio.id, "300.00")],
    )
    await alta_gasto(cliente, entorno, importe="120.00", tematica=entorno.alimentacion.id)
    await alta_gasto(cliente, entorno, importe="40.00", tematica=entorno.supermercado.id)
    await alta_gasto(cliente, entorno, importe="330.00", tematica=entorno.ocio.id)

    esperada = calcular_barra(
        PERIODO,
        Decimal("2000.00"),
        [
            EntradaCategoria(
                categoria_id=str(entorno.alimentacion.id),
                nombre="Alimentación",
                asignado=Decimal("500.00"),
                gastado=Decimal("120.00"),
            ),
            EntradaCategoria(
                categoria_id=str(entorno.supermercado.id),
                nombre="Supermercado",
                asignado=Decimal("0.00"),
                gastado=Decimal("40.00"),
            ),
            EntradaCategoria(
                categoria_id=str(entorno.ocio.id),
                nombre="Ocio",
                asignado=Decimal("300.00"),
                gastado=Decimal("330.00"),
            ),
        ],
    )

    barra = (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()
    assert barra["period"] == PERIODO
    assert Decimal(barra["income"]) == esperada.ingresos
    assert Decimal(barra["allocated_total"]) == esperada.total_asignado
    assert Decimal(barra["spent_total"]) == esperada.total_gastado
    assert Decimal(barra["unassigned"]) == esperada.sin_asignar
    assert Decimal(barra["rollover_in_total"]) == esperada.total_arrastrado
    assert barra["warnings"] == esperada.avisos

    plano = aplanar(barra["allocations"])
    assert len(plano) == len(esperada.segmentos)
    for segmento in esperada.segmentos:
        fila = plano[segmento.categoria_id]
        assert Decimal(fila["allocated"]) == segmento.asignado
        assert Decimal(fila["spent"]) == segmento.gastado
        assert Decimal(fila["available"]) == segmento.disponible
        assert Decimal(fila["overspent"]) == segmento.sobrepaso
        assert fila["state"] == segmento.estado.value
        assert fila["spent_pct"] == float(segmento.porcentaje_consumido) / 100

    # Y el aviso de sobrepaso es el que compone el servicio, palabra por palabra.
    assert any("Ocio" in aviso for aviso in barra["warnings"])
    assert plano[str(entorno.ocio.id)]["state"] == EstadoSegmento.SOBREPASADO.value


async def test_la_barra_anida_las_tematicas_hijas(cliente: AsyncClient, entorno: Entorno) -> None:
    await asignar(
        cliente,
        PERIODO,
        [(entorno.alimentacion.id, "100.00"), (entorno.supermercado.id, "40.00")],
    )
    barra = (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()
    raices = {asignacion["category_id"] for asignacion in barra["allocations"]}
    assert str(entorno.alimentacion.id) in raices
    assert str(entorno.supermercado.id) not in raices
    madre = next(
        item for item in barra["allocations"] if item["category_id"] == str(entorno.alimentacion.id)
    )
    assert [hija["category_id"] for hija in madre["children"]] == [str(entorno.supermercado.id)]


async def test_rn35_el_ingreso_previsto_manda_sobre_el_real(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await ingresar(cliente, entorno, "1200.00", HOY)
    respuesta = await cliente.put(f"{RUTA}/budgets/{PERIODO}", json={"planned_income": "1800.00"})
    assert respuesta.status_code == 200, respuesta.text
    barra = respuesta.json()
    assert barra["income_actual"] == "1200.00"
    assert barra["planned_income"] == "1800.00"
    assert barra["income"] == "1800.00"


async def test_rn21_una_transferencia_no_es_gasto_en_la_barra(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """El gastado sale de `vw_movement_lines`, que ya excluye `kind = 'transfer'`."""
    await ingresar(cliente, entorno, "1000.00", HOY)
    await asignar(cliente, PERIODO, [(entorno.alimentacion.id, "300.00")])
    await alta_gasto(cliente, entorno, importe="80.00", tematica=entorno.alimentacion.id)

    antes = (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()
    traspaso = await cliente.post(
        f"{RUTA}/transfers",
        json={
            "from_account_id": str(entorno.corriente.id),
            "to_account_id": str(entorno.ahorro.id),
            "date": HOY.isoformat(),
            "amount": "400.00",
        },
    )
    assert traspaso.status_code == 201, traspaso.text
    despues = (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()

    assert antes["spent_total"] == despues["spent_total"] == "80.00"
    assert antes["income_actual"] == despues["income_actual"] == "1000.00"
    assert aplanar(despues["allocations"])[str(entorno.alimentacion.id)]["spent"] == "80.00"


async def test_un_gasto_repartido_aporta_su_split_a_cada_tematica(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """RN-31: nunca el total duplicado en las dos temáticas."""
    datos = await alta_gasto(cliente, entorno, importe="60.00")
    await cliente.put(
        f"{RUTA}/transactions/{datos['id']}/splits",
        json={
            "splits": [
                {"category_id": str(entorno.supermercado.id), "amount": "20.00"},
                {"category_id": str(entorno.ocio.id), "amount": "40.00"},
            ]
        },
    )
    barra = (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()
    plano = aplanar(barra["allocations"])
    assert barra["spent_total"] == "60.00"
    assert plano[str(entorno.supermercado.id)]["spent"] == "20.00"
    assert plano[str(entorno.ocio.id)]["spent"] == "40.00"


async def test_el_periodo_tiene_que_ser_aaaa_mm(cliente: AsyncClient) -> None:
    # «2026/08» no se prueba aquí: la barra inclinada parte la ruta y ni llega al
    # endpoint, así que responde 404 y no 422.
    for malo in ("2026-8", "08-2026", "2026-13"):
        respuesta = await cliente.get(f"{RUTA}/budgets/{malo}")
        assert respuesta.status_code == 422, malo
        assert codigo_de(respuesta) == "periodo_invalido", malo


# --------------------------------------------------------------------------- #
# Asignar y reasignar
# --------------------------------------------------------------------------- #


async def test_rn28_una_asignacion_negativa_se_rechaza(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    respuesta = await cliente.put(
        f"{RUTA}/budgets/{PERIODO}/allocations",
        json={"allocations": [{"category_id": str(entorno.ocio.id), "amount": "-10.00"}]},
    )
    assert respuesta.status_code == 422
    detalle = respuesta.json()["error"]
    assert detalle["codigo"] in ("presupuesto_negativo", "datos_invalidos")


async def test_asignar_una_sola_tematica_es_un_patch(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    respuesta = await cliente.patch(
        f"{RUTA}/budgets/{PERIODO}/allocations/{entorno.ocio.id}",
        json={"amount": "120.00", "rollover_enabled": True},
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["allocated"] == "120.00"
    assert respuesta.json()["rollover_enabled"] is True


async def test_rn34_no_se_presupuesta_una_tematica_de_ingresos(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    respuesta = await cliente.patch(
        f"{RUTA}/budgets/{PERIODO}/allocations/{entorno.nomina.id}",
        json={"amount": "100.00"},
    )
    assert respuesta.status_code == 422


async def test_rn29_reasignar_es_de_suma_cero(cliente: AsyncClient, entorno: Entorno) -> None:
    await asignar(
        cliente,
        PERIODO,
        [(entorno.alimentacion.id, "300.00"), (entorno.ocio.id, "100.00")],
    )
    respuesta = await cliente.post(
        f"{RUTA}/budgets/{PERIODO}/reassign",
        json={
            "from_category_id": str(entorno.alimentacion.id),
            "to_category_id": str(entorno.ocio.id),
            "amount": "50.00",
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    barra = respuesta.json()
    plano = aplanar(barra["allocations"])
    assert plano[str(entorno.alimentacion.id)]["allocated"] == "250.00"
    assert plano[str(entorno.ocio.id)]["allocated"] == "150.00"
    assert barra["allocated_total"] == "400.00"


async def test_rn29_reasignar_no_deja_una_tematica_por_debajo_de_lo_gastado(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """Dejarla por debajo la pondría en sobrepaso artificial: lo impide el servicio."""
    await asignar(
        cliente,
        PERIODO,
        [(entorno.alimentacion.id, "300.00"), (entorno.ocio.id, "100.00")],
    )
    await alta_gasto(cliente, entorno, importe="280.00", tematica=entorno.alimentacion.id)

    respuesta = await cliente.post(
        f"{RUTA}/budgets/{PERIODO}/reassign",
        json={
            "from_category_id": str(entorno.alimentacion.id),
            "to_category_id": str(entorno.ocio.id),
            "amount": "100.00",
        },
    )
    assert respuesta.status_code == 422, respuesta.text
    assert codigo_de(respuesta) == "presupuesto_negativo"
    assert "20.00" in respuesta.json()["error"]["mensaje"]

    # Justo lo disponible sí se puede mover.
    valida = await cliente.post(
        f"{RUTA}/budgets/{PERIODO}/reassign",
        json={
            "from_category_id": str(entorno.alimentacion.id),
            "to_category_id": str(entorno.ocio.id),
            "amount": "20.00",
        },
    )
    assert valida.status_code == 200, valida.text
    plano = aplanar(valida.json()["allocations"])
    assert plano[str(entorno.alimentacion.id)]["allocated"] == "280.00"


async def test_reasignar_a_la_misma_tematica_no_tiene_sentido(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    respuesta = await cliente.post(
        f"{RUTA}/budgets/{PERIODO}/reassign",
        json={
            "from_category_id": str(entorno.ocio.id),
            "to_category_id": str(entorno.ocio.id),
            "amount": "10.00",
        },
    )
    assert respuesta.status_code == 422


# --------------------------------------------------------------------------- #
# Copiar y repartir
# --------------------------------------------------------------------------- #


async def test_copiar_del_mes_anterior(cliente: AsyncClient, entorno: Entorno) -> None:
    await asignar(
        cliente,
        ANTERIOR,
        [(entorno.alimentacion.id, "400.00"), (entorno.ocio.id, "120.00")],
    )
    respuesta = await cliente.post(
        f"{RUTA}/budgets/{PERIODO}/copy-from", json={"source_period": ANTERIOR}
    )
    assert respuesta.status_code == 200, respuesta.text
    plano = aplanar(respuesta.json()["allocations"])
    assert plano[str(entorno.alimentacion.id)]["allocated"] == "400.00"
    assert plano[str(entorno.ocio.id)]["allocated"] == "120.00"


async def test_copiar_no_pisa_lo_ya_repartido_salvo_que_se_pida(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await asignar(cliente, ANTERIOR, [(entorno.ocio.id, "120.00")])
    await asignar(cliente, PERIODO, [(entorno.ocio.id, "50.00")])

    sin_pisar = await cliente.post(
        f"{RUTA}/budgets/{PERIODO}/copy-from", json={"source_period": ANTERIOR}
    )
    assert aplanar(sin_pisar.json()["allocations"])[str(entorno.ocio.id)]["allocated"] == "50.00"

    pisando = await cliente.post(
        f"{RUTA}/budgets/{PERIODO}/copy-from",
        json={"source_period": ANTERIOR, "overwrite": True},
    )
    assert aplanar(pisando.json()["allocations"])[str(entorno.ocio.id)]["allocated"] == "120.00"


async def test_repartir_lo_no_asignado_a_partes_iguales(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """El reparto lo propone `reparto_sugerido()`, y la suma cuadra al céntimo."""
    await ingresar(cliente, entorno, "300.00", HOY)
    respuesta = await cliente.post(
        f"{RUTA}/budgets/{PERIODO}/distribute",
        json={
            "strategy": "equal",
            "category_ids": [str(entorno.alimentacion.id), str(entorno.ocio.id)],
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    barra = respuesta.json()
    plano = aplanar(barra["allocations"])
    assert plano[str(entorno.alimentacion.id)]["allocated"] == "150.00"
    assert plano[str(entorno.ocio.id)]["allocated"] == "150.00"
    assert barra["allocated_total"] == "300.00"
    assert barra["unassigned"] == "0.00"


async def test_repartir_segun_el_mes_anterior(cliente: AsyncClient, entorno: Entorno) -> None:
    ayer = primer_dia(ANTERIOR)
    await alta_gasto(
        cliente, entorno, importe="300.00", tematica=entorno.alimentacion.id, fecha=ayer
    )
    await alta_gasto(cliente, entorno, importe="100.00", tematica=entorno.ocio.id, fecha=ayer)
    await ingresar(cliente, entorno, "800.00", HOY)

    respuesta = await cliente.post(
        f"{RUTA}/budgets/{PERIODO}/distribute",
        json={
            "strategy": "last_period_share",
            "category_ids": [str(entorno.alimentacion.id), str(entorno.ocio.id)],
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    plano = aplanar(respuesta.json()["allocations"])
    # 800 € repartidos en la proporción 300:100 del mes pasado.
    assert plano[str(entorno.alimentacion.id)]["allocated"] == "600.00"
    assert plano[str(entorno.ocio.id)]["allocated"] == "200.00"


async def test_no_se_reparte_lo_que_no_hay(cliente: AsyncClient, entorno: Entorno) -> None:
    respuesta = await cliente.post(
        f"{RUTA}/budgets/{PERIODO}/distribute", json={"strategy": "equal"}
    )
    assert respuesta.status_code == 422


# --------------------------------------------------------------------------- #
# Arrastre, cierre y reapertura
# --------------------------------------------------------------------------- #


async def test_f26_el_arrastre_entra_en_el_mes_siguiente(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """RN-32: `carry_in(p) = allocated(p−1) + carry_in(p−1) − spent(p−1)`."""
    await asignar(cliente, ANTERIOR, [(entorno.alimentacion.id, "200.00")], arrastre=True)
    await alta_gasto(
        cliente,
        entorno,
        importe="50.00",
        tematica=entorno.alimentacion.id,
        fecha=primer_dia(ANTERIOR),
    )

    previsto = await cliente.get(f"{RUTA}/budgets/{PERIODO}/rollover")
    assert previsto.status_code == 200, previsto.text
    fila = previsto.json()[0]
    assert fila["previous_period"] == ANTERIOR
    assert fila["carried_in"] == "150.00"
    assert fila["carried_negative"] is False

    cierre = await cliente.post(f"{RUTA}/budgets/{ANTERIOR}/close")
    assert cierre.status_code == 200, cierre.text
    assert cierre.json()["is_closed"] is True

    barra = (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()
    plano = aplanar(barra["allocations"])
    assert plano[str(entorno.alimentacion.id)]["rollover_in"] == "150.00"
    assert barra["rollover_in_total"] == "150.00"
    # Disponible = asignado + arrastrado − gastado.
    assert plano[str(entorno.alimentacion.id)]["available"] == "150.00"


async def test_sin_arrastre_el_sobrante_se_pierde(cliente: AsyncClient, entorno: Entorno) -> None:
    await asignar(cliente, ANTERIOR, [(entorno.ocio.id, "80.00")], arrastre=False)
    await cliente.post(f"{RUTA}/budgets/{ANTERIOR}/close")
    barra = (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()
    assert barra["rollover_in_total"] == "0.00"
    assert (await cliente.get(f"{RUTA}/budgets/{PERIODO}/rollover")).json() == []


async def test_rn33_cerrar_es_idempotente(cliente: AsyncClient, entorno: Entorno) -> None:
    await asignar(cliente, ANTERIOR, [(entorno.alimentacion.id, "200.00")], arrastre=True)
    primera = await cliente.post(f"{RUTA}/budgets/{ANTERIOR}/close")
    segunda = await cliente.post(f"{RUTA}/budgets/{ANTERIOR}/close")
    assert primera.status_code == segunda.status_code == 200
    barra = (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()
    # El arrastre se ha consolidado una sola vez, no dos.
    assert barra["rollover_in_total"] == "200.00"


async def test_rn33_un_periodo_cerrado_rechaza_cambios(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await asignar(cliente, ANTERIOR, [(entorno.ocio.id, "50.00")])
    await cliente.post(f"{RUTA}/budgets/{ANTERIOR}/close")

    respuesta = await cliente.patch(
        f"{RUTA}/budgets/{ANTERIOR}/allocations/{entorno.ocio.id}", json={"amount": "70.00"}
    )
    assert respuesta.status_code == 409
    assert codigo_de(respuesta) == "periodo_cerrado"

    reasignacion = await cliente.post(
        f"{RUTA}/budgets/{ANTERIOR}/reassign",
        json={
            "from_category_id": str(entorno.ocio.id),
            "to_category_id": str(entorno.alimentacion.id),
            "amount": "10.00",
        },
    )
    assert reasignacion.status_code == 409


async def test_reabrir_deshace_el_arrastre_en_cascada(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await asignar(cliente, ANTERIOR, [(entorno.alimentacion.id, "200.00")], arrastre=True)
    await cliente.post(f"{RUTA}/budgets/{ANTERIOR}/close")
    assert (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()["rollover_in_total"] == "200.00"

    reapertura = await cliente.post(f"{RUTA}/budgets/{ANTERIOR}/reopen")
    assert reapertura.status_code == 200, reapertura.text
    assert reapertura.json()["is_closed"] is False
    assert (await cliente.get(f"{RUTA}/budgets/{PERIODO}")).json()["rollover_in_total"] == "0.00"

    # Y vuelve a admitir cambios.
    otra = await cliente.patch(
        f"{RUTA}/budgets/{ANTERIOR}/allocations/{entorno.alimentacion.id}",
        json={"amount": "250.00"},
    )
    assert otra.status_code == 200


async def test_no_se_cierra_un_periodo_futuro(cliente: AsyncClient) -> None:
    futuro = f"{HOY.year + 1:04d}-01"
    respuesta = await cliente.post(f"{RUTA}/budgets/{futuro}/close")
    assert respuesta.status_code == 422


# --------------------------------------------------------------------------- #
# Selector de mes e ingresos
# --------------------------------------------------------------------------- #


async def test_el_selector_de_mes_trae_los_totales(cliente: AsyncClient, entorno: Entorno) -> None:
    await asignar(cliente, PERIODO, [(entorno.ocio.id, "90.00")])
    await alta_gasto(cliente, entorno, importe="30.00", tematica=entorno.ocio.id)
    await ingresar(cliente, entorno, "700.00", HOY)

    listado = (await cliente.get(f"{RUTA}/budgets")).json()
    assert listado["total"] >= 1
    fila = next(item for item in listado["items"] if item["period"] == PERIODO)
    assert fila["allocated_total"] == "90.00"
    assert fila["spent_total"] == "30.00"
    assert fila["income"] == "700.00"
    assert fila["is_closed"] is False


async def test_los_ingresos_del_mes_se_listan(cliente: AsyncClient, entorno: Entorno) -> None:
    await ingresar(cliente, entorno, "1500.00", HOY)
    await alta_gasto(cliente, entorno, importe="20.00")
    listado = (await cliente.get(f"{RUTA}/budgets/{PERIODO}/incomes")).json()
    assert listado["total"] == 1
    assert listado["items"][0]["amount"] == "1500.00"


# --------------------------------------------------------------------------- #
# Aislamiento entre hogares
# --------------------------------------------------------------------------- #


async def test_la_barra_de_un_hogar_no_ve_el_dinero_del_otro(
    sesion: AsyncSession, entorno: Entorno
) -> None:
    """RN-01: cada consulta filtra por el hogar de la sesión, agregados incluidos."""
    from app.models.cuenta import Account

    otro_hogar, otro_usuario = await crear_hogar(sesion, f"{uuid.uuid4().hex[:10]}@vecino.es")
    otra_cuenta = Account(
        household_id=otro_hogar.id, name="Vecino", type="checking", account_class="asset"
    )
    sesion.add(otra_cuenta)
    await sesion.commit()
    otra_tematica = await crear_tematica(sesion, otro_hogar, "Alimentación")

    async with cliente_de(sesion, otro_usuario) as vecino:
        alta = await vecino.post(
            f"{RUTA}/transactions",
            json={
                "account_id": str(otra_cuenta.id),
                "date": HOY.isoformat(),
                "amount": "999.00",
                "category_id": str(otra_tematica.id),
            },
        )
        assert alta.status_code == 201, alta.text
        await vecino.put(
            f"{RUTA}/budgets/{PERIODO}/allocations",
            json={"allocations": [{"category_id": str(otra_tematica.id), "amount": "999.00"}]},
        )

    async with cliente_de(sesion, entorno.usuario) as propio:
        await propio.put(
            f"{RUTA}/budgets/{PERIODO}/allocations",
            json={"allocations": [{"category_id": str(entorno.ocio.id), "amount": "10.00"}]},
        )
        barra = (await propio.get(f"{RUTA}/budgets/{PERIODO}")).json()

    assert barra["spent_total"] == "0.00"
    assert barra["allocated_total"] == "10.00"
    assert str(otra_tematica.id) not in aplanar(barra["allocations"])

    async with cliente_de(sesion, otro_usuario) as vecino:
        suya = (await vecino.get(f"{RUTA}/budgets/{PERIODO}")).json()
    assert suya["spent_total"] == "999.00"
    assert suya["allocated_total"] == "999.00"
