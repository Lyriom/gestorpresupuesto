"""Pruebas del presupuesto por semanas.

Quien cobra cada semana no reparte el dinero del mes, reparte el de la paga. Un
periodo puede ser entonces una semana ISO (`2026-W33`) y no solo un mes, y lo que
se comprueba aquí es que la semana no es una etiqueta: que el gasto que entra en la
barra es el de **esos siete días** y no el del mes, que el sobrante pasa de una
semana a la siguiente y que el informe compara cada semana contra su propio gasto.

Es lo que más fácil se rompe: casi todas las consultas de gasto agrupaban por la
columna `period_month` de `vw_movement_lines`, que es siempre el mes del movimiento.
Con ella, las cinco semanas de agosto reciben el gasto de agosto entero y todas
salen sobrepasadas.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import ajustes, auth, informes
from app.services.presupuesto import Granularidad, inicio_de, periodo_de
from tests.test_api_presupuestos import asignar, ingresar
from tests.test_api_transacciones import (  # noqa: F401 - fixtures compartidas
    HOY,
    RUTA,
    Entorno,
    alta_gasto,
    cliente_de,
    codigo_de,
    crear_hogar,
    crear_tematica,
    entorno,
    esquema,
    motor,
    sesion,
)

__all__ = ["cliente_de", "entorno", "esquema", "motor", "sesion"]

#: El cliente del andamio compartido no monta ajustes, informes ni «yo», y aquí hacen
#: falta los tres: el ajuste del hogar decide la granularidad, el informe tiene que
#: dar una fila por semana y «yo» es de donde la SPA saca el periodo de hoy.
EXTRA = (ajustes, informes, auth)


@pytest_asyncio.fixture
async def cliente(sesion: AsyncSession, entorno: Entorno) -> AsyncIterator[AsyncClient]:
    async with cliente_de(sesion, entorno.usuario, extra=EXTRA) as cliente:
        yield cliente


#: Una semana entera y elegida a mano, no «la de hoy»: así el lunes y el domingo son
#: fechas fijas y las aserciones no cambian de significado según el día que se
#: ejecuten las pruebas.
SEMANA = "2026-W33"
LUNES = date(2026, 8, 10)
DOMINGO = date(2026, 8, 16)
SEMANA_SIGUIENTE = "2026-W34"
LUNES_SIGUIENTE = date(2026, 8, 17)


async def barra(cliente: AsyncClient, periodo: str) -> dict[str, Any]:
    respuesta = await cliente.get(f"{RUTA}/budgets/{periodo}")
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


class TestLaSemanaComoPeriodo:
    async def test_la_semana_va_de_lunes_a_domingo(self):
        assert inicio_de(SEMANA) == LUNES
        assert periodo_de(DOMINGO, Granularidad.SEMANA) == SEMANA
        assert periodo_de(LUNES_SIGUIENTE, Granularidad.SEMANA) == SEMANA_SIGUIENTE

    async def test_una_semana_se_presupuesta_igual_que_un_mes(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        await ingresar(cliente, entorno, "700.00", LUNES)
        await asignar(cliente, SEMANA, [(entorno.alimentacion.id, "120.00")])
        await alta_gasto(cliente, entorno, importe="45.00", fecha=LUNES)

        datos = await barra(cliente, SEMANA)
        assert datos["period"] == SEMANA
        assert datos["allocated_total"] == "120.00"
        assert datos["spent_total"] == "45.00"
        assert datos["days_in_period"] == 7

    async def test_el_gasto_de_otra_semana_no_entra(self, cliente: AsyncClient, entorno: Entorno):
        """El caso que rompía todo: agrupar por mes mete los dos gastos en las dos.

        Los dos son de agosto, así que cualquier consulta que agrupe por el mes del
        movimiento devuelve 45 + 80 en las dos semanas.
        """
        await asignar(cliente, SEMANA, [(entorno.alimentacion.id, "120.00")])
        await asignar(cliente, SEMANA_SIGUIENTE, [(entorno.alimentacion.id, "120.00")])
        await alta_gasto(cliente, entorno, importe="45.00", fecha=LUNES)
        await alta_gasto(cliente, entorno, importe="80.00", fecha=LUNES_SIGUIENTE)

        assert (await barra(cliente, SEMANA))["spent_total"] == "45.00"
        assert (await barra(cliente, SEMANA_SIGUIENTE))["spent_total"] == "80.00"

    async def test_el_domingo_es_de_la_semana_y_el_lunes_ya_no(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        """Los bordes, que es donde un error de un día no se ve pero descuadra."""
        await asignar(cliente, SEMANA, [(entorno.alimentacion.id, "100.00")])
        await alta_gasto(cliente, entorno, importe="10.00", fecha=LUNES - timedelta(days=1))
        await alta_gasto(cliente, entorno, importe="20.00", fecha=DOMINGO)
        await alta_gasto(cliente, entorno, importe="30.00", fecha=LUNES_SIGUIENTE)

        assert (await barra(cliente, SEMANA))["spent_total"] == "20.00"

    async def test_el_dia_se_cuenta_dentro_de_la_semana(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        """En la semana del 10 al 16, el día 13 es el cuarto de siete, no el trece."""
        from app.api.v1.presupuestos import _dia_del_periodo

        assert _dia_del_periodo(SEMANA, date(2026, 8, 13)) == (4, 7)
        assert _dia_del_periodo(SEMANA, LUNES) == (1, 7)
        assert _dia_del_periodo(SEMANA, DOMINGO) == (7, 7)
        # Fuera del periodo se pega a los extremos, como en los meses.
        assert _dia_del_periodo(SEMANA, LUNES - timedelta(days=1)) == (1, 7)
        assert _dia_del_periodo(SEMANA, LUNES_SIGUIENTE) == (7, 7)


class TestElArrastreEntreSemanas:
    async def test_el_sobrante_de_una_semana_pasa_a_la_siguiente(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        """Así se ahorra para el alquiler cobrando por semanas: 100 cada semana con
        arrastre, y a la cuarta hay 400 disponibles sin haber presupuestado 400."""
        await asignar(cliente, SEMANA, [(entorno.alimentacion.id, "100.00")], arrastre=True)
        await alta_gasto(cliente, entorno, importe="30.00", fecha=LUNES)

        cierre = await cliente.post(f"{RUTA}/budgets/{SEMANA}/close")
        assert cierre.status_code == 200, cierre.text

        siguiente = await barra(cliente, SEMANA_SIGUIENTE)
        plano = {a["category_id"]: a for a in siguiente["allocations"]}
        assert plano[str(entorno.alimentacion.id)]["rollover_in"] == "70.00"

    async def test_el_periodo_siguiente_de_una_semana_es_la_semana_de_al_lado(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        """No el mes siguiente: el arrastre tiene que caer en 2026-W34."""
        await asignar(cliente, SEMANA, [(entorno.alimentacion.id, "50.00")], arrastre=True)
        await cliente.post(f"{RUTA}/budgets/{SEMANA}/close")

        listado = await cliente.get(f"{RUTA}/budgets")
        assert listado.status_code == 200, listado.text
        periodos = {fila["period"] for fila in listado.json()["items"]}
        assert SEMANA_SIGUIENTE in periodos
        assert "2026-09" not in periodos


class TestElListadoYLosInformes:
    async def test_el_listado_da_a_cada_semana_su_gasto(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        await asignar(cliente, SEMANA, [(entorno.alimentacion.id, "120.00")])
        await asignar(cliente, SEMANA_SIGUIENTE, [(entorno.alimentacion.id, "120.00")])
        await alta_gasto(cliente, entorno, importe="45.00", fecha=LUNES)
        await alta_gasto(cliente, entorno, importe="80.00", fecha=LUNES_SIGUIENTE)

        respuesta = await cliente.get(f"{RUTA}/budgets")
        assert respuesta.status_code == 200, respuesta.text
        por_periodo = {fila["period"]: fila for fila in respuesta.json()["items"]}
        assert por_periodo[SEMANA]["spent_total"] == "45.00"
        assert por_periodo[SEMANA_SIGUIENTE]["spent_total"] == "80.00"

    async def test_presupuesto_vs_real_da_una_fila_por_semana(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        """La ventana que se pide es agosto y las filas que salen son semanales."""
        await asignar(cliente, SEMANA, [(entorno.alimentacion.id, "120.00")])
        await asignar(cliente, SEMANA_SIGUIENTE, [(entorno.alimentacion.id, "120.00")])
        await alta_gasto(cliente, entorno, importe="45.00", fecha=LUNES)
        await alta_gasto(cliente, entorno, importe="80.00", fecha=LUNES_SIGUIENTE)

        respuesta = await cliente.get(
            f"{RUTA}/reports/budget-vs-actual", params={"period": "2026-08"}
        )
        assert respuesta.status_code == 200, respuesta.text
        filas = {fila["period"]: fila for fila in respuesta.json()["rows"]}
        assert filas[SEMANA]["spent"] == "45.00"
        assert filas[SEMANA_SIGUIENTE]["spent"] == "80.00"
        assert not filas[SEMANA]["is_overspent"]

    async def test_un_informe_no_acepta_una_semana(self, cliente: AsyncClient, entorno: Entorno):
        """Una serie mensual a la que se le pide una semana no puede contestar nada
        sensato, así que contesta 422 en vez de devolver el mes disimulando."""
        respuesta = await cliente.get(
            f"{RUTA}/reports/monthly-comparison", params={"period": SEMANA}
        )
        assert respuesta.status_code == 422, respuesta.text


class TestElAjusteDelHogar:
    async def test_el_hogar_empieza_en_meses_y_se_puede_pasar_a_semanas(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        ajustes = await cliente.get(f"{RUTA}/settings")
        assert ajustes.status_code == 200, ajustes.text
        assert ajustes.json()["budget_granularity"] == "month"

        cambio = await cliente.patch(f"{RUTA}/settings", json={"budget_granularity": "week"})
        assert cambio.status_code == 200, cambio.text
        assert cambio.json()["budget_granularity"] == "week"

        # Y «yo» pasa a decir la semana de hoy, que es lo que la SPA pide al arrancar.
        yo = await cliente.get(f"{RUTA}/auth/me")
        assert yo.status_code == 200, yo.text
        assert yo.json()["budget_granularity"] == "week"
        assert yo.json()["current_period"] == periodo_de(HOY, Granularidad.SEMANA)

    async def test_cambiar_el_ajuste_no_reinterpreta_lo_ya_guardado(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        """Un mes presupuestado sigue siendo un mes después de pasar a semanas."""
        mes = "2026-08"
        await asignar(cliente, mes, [(entorno.alimentacion.id, "400.00")])
        await cliente.patch(f"{RUTA}/settings", json={"budget_granularity": "week"})

        datos = await barra(cliente, mes)
        assert datos["allocated_total"] == "400.00"
        assert datos["days_in_period"] == 31

        listado = await cliente.get(f"{RUTA}/budgets")
        assert mes in {fila["period"] for fila in listado.json()["items"]}


class TestLoQueNoPuedeGuardarse:
    async def test_una_semana_que_no_existe_se_rechaza(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        """2025 tiene 52 semanas ISO; 2026, 53."""
        malo = await cliente.get(f"{RUTA}/budgets/2025-W53")
        assert malo.status_code == 422, malo.text
        bueno = await cliente.get(f"{RUTA}/budgets/2026-W53")
        assert bueno.status_code == 200, bueno.text

    async def test_el_mes_y_la_semana_que_arrancan_el_mismo_dia_no_se_confunden(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        """El 1 de junio de 2026 es lunes: junio y la semana 23 empiezan juntos."""
        await asignar(cliente, "2026-06", [(entorno.alimentacion.id, "400.00")])
        await asignar(cliente, "2026-W23", [(entorno.alimentacion.id, "100.00")])

        assert (await barra(cliente, "2026-06"))["allocated_total"] == "400.00"
        assert (await barra(cliente, "2026-W23"))["allocated_total"] == "100.00"

    async def test_la_moneda_de_la_barra_es_la_del_hogar(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        """Estaba escrita «EUR» a mano en la respuesta."""
        await cliente.patch(f"{RUTA}/settings", json={"currency": "USD"})
        assert (await barra(cliente, SEMANA))["currency"] == "USD"


class TestElRepartoSemanalCuadra:
    async def test_cuatro_semanas_de_cien_no_son_un_mes_de_cuatrocientos(
        self, cliente: AsyncClient, entorno: Entorno
    ):
        """Cada semana lleva su cuenta y ninguna se contagia de las demás."""
        semanas = ["2026-W33", "2026-W34", "2026-W35", "2026-W36"]
        gastos = ["90.00", "110.00", "60.00", "100.00"]
        for semana, gasto in zip(semanas, gastos, strict=True):
            await asignar(cliente, semana, [(entorno.alimentacion.id, "100.00")])
            await alta_gasto(cliente, entorno, importe=gasto, fecha=inicio_de(semana))

        total = Decimal("0.00")
        for semana, gasto in zip(semanas, gastos, strict=True):
            datos = await barra(cliente, semana)
            assert datos["spent_total"] == gasto
            total += Decimal(datos["spent_total"])
        assert total == Decimal("360.00")
