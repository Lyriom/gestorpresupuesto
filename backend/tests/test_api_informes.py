"""Los informes, sobre datos reales creados confirmando facturas.

No se insertan transacciones a mano: se suben las tres facturas del supermercado
y una de la luz y se confirman por la API, que es el camino que de verdad recorre
el usuario. Así los informes se prueban contra el mismo gasto que produce el
flujo de facturas, incluida la vista `vw_movement_lines`.
"""

from __future__ import annotations

import pytest

from tests import test_api_facturas as andamio
from tests.test_api_facturas import (
    LUZ,
    SUPERMERCADO,
    cliente_para,
    confirmar_factura,
    crear_entorno,
    subir_factura,
    subir_y_confirmar,
)

# Las fixturas del andamio se reexportan para que pytest las resuelva por nombre.
aplicacion = andamio.aplicacion
cliente = andamio.cliente
ejemplos = andamio.ejemplos
entorno = andamio.entorno

#: Los tres tickets del supermercado: 37,48 + 38,14 + 47,79.
GASTO_TOTAL = "123.41"

PERIODOS = {"period_from": "2026-06", "period_to": "2026-08"}


@pytest.fixture
async def cesta(cliente, entorno):
    """Las tres compras del supermercado, ya confirmadas."""
    for nombre in SUPERMERCADO:
        await subir_y_confirmar(cliente, entorno, nombre)
    return entorno


async def informe(cliente, ruta: str, **parametros) -> dict:
    respuesta = await cliente.get(f"/api/v1/reports/{ruta}", params=parametros)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers.get("ETag")
    return respuesta.json()


# --------------------------------------------------------------------------- #
# 1. Gasto por temática (F-18)
# --------------------------------------------------------------------------- #


async def test_gasto_por_tematica(cliente, cesta):
    cuerpo = await informe(cliente, "spending-by-category", **PERIODOS)
    assert cuerpo["total"] == GASTO_TOTAL
    assert cuerpo["uncategorized"] == "0.00"
    assert cuerpo["period_from"] == "2026-06"

    fila = cuerpo["rows"][0]
    # `depth=1` agrupa en la raíz del árbol: «Alimentación», no «Supermercado».
    assert fila["category"]["name"] == "Alimentación"
    assert fila["amount"] == GASTO_TOTAL
    assert fila["share_pct"] == 100.0
    assert fila["transactions"] == 3
    # El subárbol viene desglosado.
    assert fila["children"]
    assert fila["children"][0]["category"]["name"] == "Supermercado"
    assert fila["children"][0]["amount"] == GASTO_TOTAL


async def test_gasto_por_tematica_de_un_solo_periodo(cliente, cesta):
    cuerpo = await informe(cliente, "spending-by-category", period="2026-08")
    assert cuerpo["total"] == "47.79"
    assert cuerpo["period_from"] == cuerpo["period_to"] == "2026-08"


async def test_el_rango_invertido_es_un_error_de_solicitud(cliente, cesta):
    respuesta = await cliente.get(
        "/api/v1/reports/spending-by-category",
        params={"date_from": "2026-08-01", "date_to": "2026-06-01"},
    )
    assert respuesta.status_code == 400
    assert respuesta.json()["error"]["codigo"] == "error_solicitud"


# --------------------------------------------------------------------------- #
# 2. Mes a mes (F-19)
# --------------------------------------------------------------------------- #


async def test_evolucion_mes_a_mes(cliente, cesta):
    cuerpo = await informe(cliente, "monthly-comparison", **PERIODOS)
    assert cuerpo["periods"] == ["2026-06", "2026-07", "2026-08"]
    assert [punto["expense"] for punto in cuerpo["series"]] == ["37.48", "38.14", "47.79"]
    assert cuerpo["average_expense"] == "41.14"
    assert cuerpo["best_period"] == "2026-06"
    assert cuerpo["worst_period"] == "2026-08"
    # El desglose por temática viene indexado por identificador.
    assert len(cuerpo["series"][0]["by_category"]) == 1


# --------------------------------------------------------------------------- #
# 3. Cash flow (F-36)
# --------------------------------------------------------------------------- #


async def test_cash_flow_mensual_y_semanal(cliente, cesta):
    cuerpo = await informe(cliente, "cash-flow", **PERIODOS)
    assert cuerpo["granularity"] == "month"
    assert cuerpo["total_outflow"] == GASTO_TOTAL
    assert cuerpo["total_inflow"] == "0.00"
    assert cuerpo["net"] == "-123.41"
    assert [punto["period"] for punto in cuerpo["points"]] == ["2026-06", "2026-07", "2026-08"]
    assert cuerpo["points"][-1]["cumulative"] == "-123.41"

    semanal = await informe(cliente, "cash-flow", granularity="week", **PERIODOS)
    assert semanal["granularity"] == "week"
    assert len(semanal["points"]) == 3


# --------------------------------------------------------------------------- #
# 4. Top comercios (F-37)
# --------------------------------------------------------------------------- #


async def test_top_comercios(cliente, cesta):
    cuerpo = await informe(cliente, "top-payees", **PERIODOS)
    assert cuerpo["total"] == GASTO_TOTAL
    fila = cuerpo["rows"][0]
    assert "AHORRO" in fila["payee"]["name"].upper()
    assert fila["amount"] == GASTO_TOTAL
    assert fila["transactions"] == 3
    assert fila["average_ticket"] == "41.14"
    assert fila["share_pct"] == 100.0
    assert fila["top_category"]["name"] == "Supermercado"


# --------------------------------------------------------------------------- #
# 5. Patrimonio neto (F-11)
# --------------------------------------------------------------------------- #


async def test_patrimonio_neto(cliente, cesta):
    cuerpo = await informe(cliente, "net-worth", **PERIODOS)
    assert [punto["period"] for punto in cuerpo["points"]] == ["2026-06", "2026-07", "2026-08"]
    # 2.000 € de saldo inicial menos lo gastado hasta cada mes.
    assert cuerpo["points"][0]["assets"] == "1962.52"
    assert cuerpo["points"][-1]["net_worth"] == "1876.59"
    assert cuerpo["points"][-1]["liabilities"] == "0.00"
    assert cuerpo["current"] == "1876.59"
    assert cuerpo["by_account"][0]["account"]["name"] == "Cuenta corriente"
    assert cuerpo["by_account"][0]["is_liability"] is False


# --------------------------------------------------------------------------- #
# 6. Presupuestado frente a real
# --------------------------------------------------------------------------- #


async def test_presupuesto_vs_real_sin_presupuesto_no_inventa_filas(cliente, cesta):
    cuerpo = await informe(cliente, "budget-vs-actual", **PERIODOS)
    assert cuerpo["rows"] == []
    assert cuerpo["allocated_total"] == "0.00"
    assert cuerpo["overspent_categories"] == 0


# --------------------------------------------------------------------------- #
# 7 y 8. Precio de un producto y subidas detectadas (F-15, F-16)
# --------------------------------------------------------------------------- #


async def test_evolucion_del_precio_de_un_producto(cliente, cesta):
    catalogo = (await cliente.get("/api/v1/products", params={"q": "aceite"})).json()
    aceite = catalogo["items"][0]

    cuerpo = await informe(cliente, "product-price", product_id=aceite["id"], **PERIODOS)
    assert cuerpo["product"]["id"] == aceite["id"]
    assert [punto["unit_price"] for punto in cuerpo["points"]] == ["8.95", "9.8", "11.45"]
    assert cuerpo["points"][0]["change_pct"] is None
    assert cuerpo["points"][-1]["change_pct"] == pytest.approx(16.84, abs=0.01)
    # Media móvil de tres puntos: (8,95 + 9,80 + 11,45) / 3.
    assert cuerpo["points"][-1]["moving_average"] == "10.0667"
    assert cuerpo["stats"]["observations"] == 3
    assert cuerpo["stats"]["trend"] == "sube"
    assert len(cuerpo["by_payee"]) == 1
    assert cuerpo["comparison"]["cheapest"]["last_unit_price"] == "11.45"


async def test_subidas_de_precio_ordenadas_por_impacto(cliente, cesta):
    cuerpo = await informe(cliente, "price-increases", min_change_pct=3, **PERIODOS)
    assert cuerpo["rows"]
    # Lo que duele son los euros, no el porcentaje: manda el impacto estimado.
    primera = cuerpo["rows"][0]
    assert "ACEITE" in primera["product"]["name"]
    assert primera["change_pct"] == pytest.approx(16.84, abs=0.01)
    assert primera["previous_unit_price"] == "9.8"
    assert primera["new_unit_price"] == "11.45"
    assert primera["estimated_monthly_impact"] == "3.30"
    assert float(cuerpo["total_estimated_impact"]) > 0

    impactos = [float(fila["estimated_monthly_impact"]) for fila in cuerpo["rows"]]
    assert impactos == sorted(impactos, reverse=True)

    # Con el umbral muy alto no queda ninguna.
    vacio = await informe(cliente, "price-increases", min_change_pct=500, **PERIODOS)
    assert vacio["rows"] == []


# --------------------------------------------------------------------------- #
# 9. Cesta comparada (F-60)
# --------------------------------------------------------------------------- #


async def test_cesta_comparada(cliente, cesta):
    catalogo = (await cliente.get("/api/v1/products", params={"size": 50})).json()
    aceite = next(fila for fila in catalogo["items"] if "ACEITE" in fila["name"])
    leche = next(fila for fila in catalogo["items"] if "LECHE" in fila["name"])

    cuerpo = await informe(cliente, "basket", product_id=[aceite["id"], leche["id"]], months=6)
    assert cuerpo["items"] == 2
    assert cuerpo["cheapest"]["covered_items"] == 2
    assert cuerpo["cheapest"]["coverage_pct"] == 100.0
    assert cuerpo["cheapest"]["is_comparable"] is True
    # Último precio conocido de cada uno: 11,45 + 1,15.
    assert cuerpo["cheapest"]["total"] == "12.60"
    assert cuerpo["missing_by_payee"] == {}


# --------------------------------------------------------------------------- #
# 10 a 12. Suscripciones, saldo proyectado y gasto inusual
# --------------------------------------------------------------------------- #


async def test_suscripciones_sin_recurrentes(cliente, cesta):
    cuerpo = await informe(cliente, "subscriptions")
    assert cuerpo["rows"] == []
    assert cuerpo["monthly_total"] == "0.00"
    assert cuerpo["active"] == 0


async def test_saldo_proyectado(cliente, cesta):
    cuerpo = await informe(cliente, "projected-balance", period="2026-08")
    assert cuerpo["period"] == "2026-08"
    fila = cuerpo["rows"][0]
    assert fila["account"]["name"] == "Cuenta corriente"
    assert fila["current_balance"] == "1876.59"
    assert fila["pending_recurring"] == "0.00"
    assert fila["will_be_negative"] is False


async def test_una_compra_normal_del_super_no_es_un_gasto_inusual(cliente, cesta):
    """La unidad de comparación es la compra, no cada producto de la factura.

    Con la línea suelta como unidad, lo habitual de «Alimentación» pasaba a ser
    el precio de *un producto* —unos 5 €— y el aceite de 22,90 € de una compra
    corriente saltaba como gasto inusual en las tres facturas. Un aviso que
    salta con la compra de todas las semanas no es un aviso.
    """
    laxo = await informe(cliente, "anomalies", z=0.5, **PERIODOS)

    assert laxo["rows"] == []


async def test_gasto_inusual(cliente, cesta):
    cuerpo = await informe(cliente, "anomalies", z=2.5, **PERIODOS)
    assert isinstance(cuerpo["rows"], list)
    assert cuerpo["z"] == 2.5
    # Con el umbral en el suelo aparece lo más caro de la serie, con su explicación.
    laxo = await informe(cliente, "anomalies", z=0.5, **PERIODOS)
    if laxo["rows"]:
        assert laxo["rows"][0]["z_score"] >= 0.5
        assert "media" in laxo["rows"][0]["reason"]
        assert laxo["rows"][0]["transaction"]["kind"] == "expense"


# --------------------------------------------------------------------------- #
# 13. Ingresos, gastos y ahorro
# --------------------------------------------------------------------------- #


async def test_ingresos_vs_gastos(cliente, cesta):
    cuerpo = await informe(cliente, "income-vs-expense", **PERIODOS)
    assert cuerpo["expense_total"] == GASTO_TOTAL
    assert cuerpo["income_total"] == "0.00"
    assert cuerpo["savings_total"] == "-123.41"
    assert cuerpo["savings_rate"] == 0.0
    assert [fila["period"] for fila in cuerpo["rows"]] == ["2026-06", "2026-07", "2026-08"]


# --------------------------------------------------------------------------- #
# Inflación personal
# --------------------------------------------------------------------------- #


async def test_inflacion_personal_de_la_cesta_real(cliente, cesta):
    cuerpo = await informe(
        cliente, "personal-inflation", date_from="2026-06-30", date_to="2026-08-31"
    )
    assert cuerpo["products"] == 5
    assert cuerpo["inflation_pct"] == pytest.approx(11.62, abs=0.05)
    assert "cesta" in cuerpo["message"]
    # El aceite es el que más ha subido de la cesta real.
    assert "ACEITE" in cuerpo["rows"][0]["product"]["name"]
    assert cuerpo["rows"][0]["change_pct"] == pytest.approx(27.93, abs=0.01)


async def test_inflacion_personal_sin_datos_lo_dice(cliente, entorno):
    cuerpo = await informe(
        cliente, "personal-inflation", date_from="2026-06-30", date_to="2026-08-31"
    )
    assert cuerpo["products"] == 0
    assert cuerpo["inflation_pct"] is None
    assert "suficientes" in cuerpo["message"]


# --------------------------------------------------------------------------- #
# Formato CSV y cacheado
# --------------------------------------------------------------------------- #


async def test_todos_los_informes_responden_y_sirven_csv(cliente, cesta, entorno):
    catalogo = (await cliente.get("/api/v1/products", params={"q": "aceite"})).json()
    rutas = {
        "spending-by-category": {},
        "monthly-comparison": {},
        "cash-flow": {},
        "top-payees": {},
        "net-worth": {},
        "budget-vs-actual": {},
        "product-price": {"product_id": catalogo["items"][0]["id"]},
        "price-increases": {},
        "basket": {"product_id": catalogo["items"][0]["id"]},
        "subscriptions": {},
        "projected-balance": {},
        "anomalies": {},
        "income-vs-expense": {},
        "personal-inflation": {},
    }
    assert len(rutas) == 14

    for ruta, extra in rutas.items():
        json = await cliente.get(f"/api/v1/reports/{ruta}", params={**PERIODOS, **extra})
        assert json.status_code == 200, f"{ruta}: {json.text}"
        assert json.headers.get("ETag"), ruta

        salida = await cliente.get(
            f"/api/v1/reports/{ruta}", params={**PERIODOS, **extra, "format": "csv"}
        )
        assert salida.status_code == 200, f"{ruta}: {salida.text}"
        assert salida.headers["content-type"].startswith("text/csv"), ruta
        assert "attachment" in salida.headers["content-disposition"], ruta


async def test_el_csv_del_gasto_por_tematica_trae_la_temática_por_nombre(cliente, cesta):
    respuesta = await cliente.get(
        "/api/v1/reports/spending-by-category", params={**PERIODOS, "format": "csv"}
    )
    assert respuesta.status_code == 200
    lineas = respuesta.text.strip().splitlines()
    assert lineas[0].startswith("category;depth")
    assert "Alimentación" in lineas[1]
    assert "123.41" in lineas[1]


# --------------------------------------------------------------------------- #
# Tenencia
# --------------------------------------------------------------------------- #


async def test_los_informes_solo_ven_el_hogar_propio(aplicacion, entorno):
    otro = await crear_entorno(email="bruno", nombre="Casa de Bruno")

    async with cliente_para(aplicacion, entorno.usuario_id) as de_ana:
        for nombre in SUPERMERCADO:
            await subir_y_confirmar(de_ana, entorno, nombre)
        propio = await informe(de_ana, "spending-by-category", **PERIODOS)
        assert propio["total"] == GASTO_TOTAL

    async with cliente_para(aplicacion, otro.usuario_id) as de_bruno:
        ajeno = await informe(de_bruno, "spending-by-category", **PERIODOS)
        assert ajeno["total"] == "0.00"
        assert ajeno["rows"] == []
        assert (await informe(de_bruno, "top-payees", **PERIODOS))["rows"] == []
        assert (await informe(de_bruno, "net-worth", **PERIODOS))["current"] == "2000.00"
        # Y no puede pedir el informe del hogar de Ana.
        respuesta = await de_bruno.get(
            "/api/v1/reports/spending-by-category",
            params={**PERIODOS, "household_id": str(entorno.household_id)},
        )
        assert respuesta.status_code == 403


async def test_una_factura_de_luz_reparte_su_gasto_en_su_tematica(cliente, entorno):
    factura = (await subir_factura(cliente, LUZ[0])).json()
    await confirmar_factura(
        cliente, entorno, factura["id"], default_category_id=str(entorno.luz_id)
    )
    cuerpo = await informe(cliente, "spending-by-category", period="2026-06", depth=1)
    assert cuerpo["total"] == "30.06"
    assert cuerpo["rows"][0]["category"]["name"] == "Vivienda"
    hijas = {hija["category"]["name"] for hija in cuerpo["rows"][0]["children"]}
    assert "Luz" in hijas
