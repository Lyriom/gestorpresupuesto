"""Catálogo de productos, alias, precios, comparativas, fusión y separación.

Reutiliza el andamio de `test_api_facturas.py`: mismo motor de PostgreSQL, misma
aplicación con los seis routers y el mismo hogar de ejemplo.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models.comercio import Payee
from app.models.producto import Product, ProductAlias, ProductPrice
from tests import test_api_facturas as andamio
from tests.test_api_facturas import (
    SUPERMERCADO,
    SesionPrueba,
    cliente_para,
    confirmar_factura,
    contar,
    crear_entorno,
    filas,
    subir_factura,
    subir_y_confirmar,
)

# Las fixturas del andamio se reexportan para que pytest las resuelva por nombre
# también en este módulo.
aplicacion = andamio.aplicacion
cliente = andamio.cliente
ejemplos = andamio.ejemplos
entorno = andamio.entorno


async def crear_comercio(household_id: uuid.UUID, nombre: str) -> uuid.UUID:
    """Da de alta un comercio: su router es de otro módulo, así que va directo."""
    async with SesionPrueba() as sesion:
        comercio = Payee(
            household_id=household_id,
            name=nombre,
            normalized_name=nombre.lower(),
            kind="merchant",
        )
        sesion.add(comercio)
        await sesion.commit()
        return comercio.id


async def crear_producto(cliente, **campos) -> dict:
    respuesta = await cliente.post("/api/v1/products", json=campos)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


async def registrar_precio(cliente, producto: dict, **campos) -> dict:
    respuesta = await cliente.post("/api/v1/prices", json={"product_id": producto["id"], **campos})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# --------------------------------------------------------------------------- #
# Catálogo
# --------------------------------------------------------------------------- #


async def test_crear_editar_y_archivar_un_producto(cliente, entorno):
    producto = await crear_producto(
        cliente,
        name="Leche Pascual entera brik",
        brand="Pascual",
        size_value="1",
        size_unit="l",
        unit="ud",
        default_category_id=str(entorno.categoria_id),
    )
    assert producto["size_text"] == "1 l"
    assert producto["canonical_name"] == "leche pascual entera brik"
    assert producto["default_category"]["id"] == str(entorno.categoria_id)
    assert producto["is_archived"] is False
    assert producto["trend"] == "sin_datos"

    editado = await cliente.patch(
        f"/api/v1/products/{producto['id']}",
        json={"name": "Leche Pascual entera brik grande", "is_archived": True},
    )
    assert editado.status_code == 200
    assert editado.json()["is_archived"] is True
    # Renombrar cambia la identidad de agrupación, no el identificador (F-05).
    assert editado.json()["id"] == producto["id"]
    assert editado.json()["canonical_name"] != producto["canonical_name"]


async def test_dos_productos_con_la_misma_clave_de_agrupacion_chocan(cliente):
    await crear_producto(cliente, name="Aceite oliva virgen extra", size_value="1", size_unit="l")
    repetido = await cliente.post(
        "/api/v1/products",
        # Mismas palabras en otro orden y el mismo tamaño: misma clave.
        json={"name": "Virgen extra aceite oliva", "size_value": "1", "size_unit": "l"},
    )
    assert repetido.status_code == 409
    assert repetido.json()["error"]["codigo"] == "nombre_duplicado"


async def test_el_tamanyo_va_con_su_unidad_o_no_va(cliente):
    respuesta = await cliente.post("/api/v1/products", json={"name": "Aceite", "size_value": "1"})
    assert respuesta.status_code == 422


# --------------------------------------------------------------------------- #
# Sugerencias por parecido difuso (RN-60)
# --------------------------------------------------------------------------- #


async def test_sugerencias_reconocen_la_misma_cosa_escrita_de_otra_forma(cliente):
    producto = await crear_producto(
        cliente, name="LECHE PASCUAL ENTERA 1L BRIK", size_value="1", size_unit="l"
    )
    respuesta = await cliente.get(
        "/api/v1/products/suggestions", params={"description": "Leche Pascual brik entera 1 l"}
    )
    assert respuesta.status_code == 200
    candidatas = respuesta.json()
    assert candidatas
    assert candidatas[0]["product"]["id"] == producto["id"]
    assert candidatas[0]["score"] >= 88


async def test_dos_tamanyos_distintos_no_son_el_mismo_producto(cliente):
    """RN-60: medio litro y un litro no comparten histórico de precio unitario."""
    await crear_producto(cliente, name="Leche Pascual entera", size_value="1", size_unit="l")
    respuesta = await cliente.get(
        "/api/v1/products/suggestions", params={"description": "Leche Pascual entera 500 ml"}
    )
    assert respuesta.json() == []


# --------------------------------------------------------------------------- #
# Alias
# --------------------------------------------------------------------------- #


async def test_alias_a_mano_y_su_borrado(cliente):
    producto = await crear_producto(cliente, name="Café molido natural")
    creado = await cliente.post(
        f"/api/v1/products/{producto['id']}/aliases",
        json={"raw_description": "CAFE MOLIDO NAT. 250 G"},
    )
    assert creado.status_code == 201
    assert creado.json()["normalized"] == "cafe molido nat"

    listado = (await cliente.get(f"/api/v1/products/{producto['id']}/aliases")).json()
    assert len(listado) == 1

    otro = await crear_producto(cliente, name="Café soluble")
    repetido = await cliente.post(
        f"/api/v1/products/{otro['id']}/aliases",
        json={"raw_description": "CAFE MOLIDO NAT. 250 G"},
    )
    assert repetido.status_code == 409

    borrado = await cliente.delete(
        f"/api/v1/products/{producto['id']}/aliases/{creado.json()['id']}"
    )
    assert borrado.status_code == 204
    assert (await cliente.get(f"/api/v1/products/{producto['id']}/aliases")).json() == []


# --------------------------------------------------------------------------- #
# Historial de precios (F-15, RN-61, RN-62, RN-63)
# --------------------------------------------------------------------------- #


async def test_historial_y_estadisticas_de_precio(cliente, entorno):
    producto = await crear_producto(cliente, name="Energía consumida P1", unit="kWh")
    comercio = await crear_comercio(entorno.household_id, "Energía Ibérica")

    for fecha, precio in (
        ("2026-06-12", "0.1389"),
        ("2026-07-12", "0.1489"),
        ("2026-08-12", "0.1612"),
    ):
        await registrar_precio(
            cliente,
            producto,
            payee_id=str(comercio),
            observed_at=fecha,
            unit_price=precio,
            unit="kWh",
            quantity="150",
        )

    historial = (await cliente.get(f"/api/v1/products/{producto['id']}/prices")).json()
    assert historial["total"] == 3
    # RN-61: cuatro decimales, sin redondear a céntimos.
    assert [fila["unit_price"] for fila in historial["items"]] == ["0.1612", "0.1489", "0.1389"]
    assert historial["items"][0]["change_pct"] == pytest.approx(8.26, abs=0.01)
    assert historial["items"][0]["change_basis"] == "same_payee"

    estadisticas = (await cliente.get(f"/api/v1/products/{producto['id']}/price-stats")).json()
    assert estadisticas["observations"] == 3
    assert estadisticas["min_unit_price"] == "0.1389"
    assert estadisticas["max_unit_price"] == "0.1612"
    assert estadisticas["median_unit_price"] == "0.1489"
    assert estadisticas["trend"] == "sube"
    assert estadisticas["cheapest_payee"]["name"] == "Energía Ibérica"


async def test_el_mismo_precio_el_mismo_dia_y_comercio_no_se_repite(cliente, entorno):
    producto = await crear_producto(cliente, name="Pan de molde integral")
    comercio = await crear_comercio(entorno.household_id, "El Ahorro")
    await registrar_precio(
        cliente,
        producto,
        payee_id=str(comercio),
        observed_at="2026-08-01",
        unit_price="1.85",
    )
    repetido = await cliente.post(
        "/api/v1/prices",
        json={
            "product_id": producto["id"],
            "payee_id": str(comercio),
            "observed_at": "2026-08-01",
            "unit_price": "1.85",
        },
    )
    assert repetido.status_code == 409


async def test_corregir_y_borrar_una_observacion(cliente):
    producto = await crear_producto(cliente, name="Huevos frescos talla M")
    precio = await registrar_precio(cliente, producto, observed_at="2026-08-01", unit_price="2.95")
    corregido = await cliente.patch(f"/api/v1/prices/{precio['id']}", json={"unit_price": "3.20"})
    assert corregido.status_code == 200
    assert corregido.json()["unit_price"] == "3.2"

    ficha = (await cliente.get(f"/api/v1/products/{producto['id']}")).json()
    assert ficha["last_unit_price"] == "3.2"

    borrado = await cliente.delete(f"/api/v1/prices/{precio['id']}")
    assert borrado.status_code == 204
    ficha = (await cliente.get(f"/api/v1/products/{producto['id']}")).json()
    assert ficha["observations_count"] == 0
    assert ficha["last_unit_price"] is None


# --------------------------------------------------------------------------- #
# Comparativa entre comercios (F-38) y cesta (F-60)
# --------------------------------------------------------------------------- #


async def test_comparativa_entre_comercios_del_mismo_producto(cliente, entorno):
    producto = await crear_producto(
        cliente, name="Aceite oliva virgen extra", size_value="1", size_unit="l"
    )
    barato = await crear_comercio(entorno.household_id, "El Ahorro")
    caro = await crear_comercio(entorno.household_id, "Gourmet Selecto")
    hoy = date.today().isoformat()
    await registrar_precio(
        cliente, producto, payee_id=str(barato), observed_at=hoy, unit_price="9.00"
    )
    await registrar_precio(
        cliente, producto, payee_id=str(caro), observed_at=hoy, unit_price="11.25"
    )

    comparativa = (await cliente.get(f"/api/v1/products/{producto['id']}/comparison")).json()
    assert comparativa["cheapest"]["payee"]["name"] == "El Ahorro"
    assert comparativa["most_expensive"]["payee"]["name"] == "Gourmet Selecto"
    assert comparativa["cheapest"]["diff_vs_cheapest"] == "0.00"
    assert comparativa["most_expensive"]["diff_vs_cheapest"] == "2.25"
    assert comparativa["spread_pct"] == pytest.approx(25.0, abs=0.01)
    assert [fila["payee"]["name"] for fila in comparativa["by_payee"]] == [
        "El Ahorro",
        "Gourmet Selecto",
    ]


async def test_comparativa_de_cesta_avisa_del_comercio_incompleto(cliente, entorno):
    aceite = await crear_producto(
        cliente, name="Aceite oliva virgen extra", size_value="1", size_unit="l"
    )
    leche = await crear_producto(
        cliente, name="Leche Pascual entera brik", size_value="1", size_unit="l"
    )
    barato = await crear_comercio(entorno.household_id, "El Ahorro")
    incompleto = await crear_comercio(entorno.household_id, "Tienda de barrio")
    hoy = date.today().isoformat()

    await registrar_precio(
        cliente, aceite, payee_id=str(barato), observed_at=hoy, unit_price="9.00"
    )
    await registrar_precio(cliente, leche, payee_id=str(barato), observed_at=hoy, unit_price="1.10")
    # En la tienda de barrio solo se ha visto el aceite: su cesta no es comparable.
    await registrar_precio(
        cliente, aceite, payee_id=str(incompleto), observed_at=hoy, unit_price="8.50"
    )

    respuesta = await cliente.get(
        "/api/v1/baskets/comparison",
        params={"product_id": [aceite["id"], leche["id"]]},
    )
    assert respuesta.status_code == 200
    cesta = respuesta.json()
    assert cesta["items"] == 2
    por_comercio = {fila["payee"]["name"]: fila for fila in cesta["by_payee"]}
    assert por_comercio["El Ahorro"]["total"] == "10.10"
    assert por_comercio["El Ahorro"]["is_comparable"] is True
    assert por_comercio["Tienda de barrio"]["is_comparable"] is False
    assert por_comercio["Tienda de barrio"]["missing_items"] == 1
    # El más barato solo se elige entre los comparables.
    assert cesta["cheapest"]["payee"]["name"] == "El Ahorro"
    assert "Tienda de barrio" in cesta["missing_by_payee"]


async def test_la_cesta_sin_productos_no_se_inventa_nada(cliente):
    respuesta = await cliente.get("/api/v1/baskets/comparison")
    assert respuesta.status_code == 422


# --------------------------------------------------------------------------- #
# Fusión, deshacer y separación (F-39, RN-65)
# --------------------------------------------------------------------------- #


async def test_fusionar_dos_productos_y_deshacer_la_fusion(cliente, entorno):
    destino = await crear_producto(cliente, name="Aceite de oliva virgen extra 1 L")
    origen = await crear_producto(cliente, name="ACEITE OLIVA V.E. GARRAFA")
    comercio = await crear_comercio(entorno.household_id, "El Ahorro")
    await registrar_precio(
        cliente, destino, payee_id=str(comercio), observed_at="2026-06-01", unit_price="8.95"
    )
    await registrar_precio(
        cliente, origen, payee_id=str(comercio), observed_at="2026-07-01", unit_price="9.80"
    )
    await cliente.post(
        f"/api/v1/products/{origen['id']}/aliases",
        json={"raw_description": "ACEITE OLIVA V.E. GARRAFA 1L"},
    )

    fusion = await cliente.post(
        "/api/v1/products/merge",
        json={"source_ids": [origen["id"]], "target_id": destino["id"]},
    )
    assert fusion.status_code == 200
    resultado = fusion.json()
    assert resultado["prices_moved"] == 1
    assert resultado["aliases_moved"] >= 1
    assert resultado["target"]["id"] == destino["id"]

    ficha = (await cliente.get(f"/api/v1/products/{destino['id']}")).json()
    assert ficha["observations_count"] == 2
    assert ficha["last_unit_price"] == "9.8"
    archivado = (await cliente.get(f"/api/v1/products/{origen['id']}")).json()
    assert archivado["is_archived"] is True

    listado = (await cliente.get("/api/v1/products/merges")).json()
    assert listado["total"] == 1
    assert listado["items"][0]["can_undo"] is True

    deshecha = await cliente.post(f"/api/v1/products/merges/{resultado['merge_id']}/undo")
    assert deshecha.status_code == 200
    assert (await cliente.get(f"/api/v1/products/{origen['id']}")).json()["observations_count"] == 1
    assert (await cliente.get(f"/api/v1/products/{destino['id']}")).json()[
        "observations_count"
    ] == 1
    assert (await cliente.get(f"/api/v1/products/{origen['id']}")).json()["is_archived"] is False

    # Deshacer dos veces no vuelve a mover nada.
    otra_vez = await cliente.post(f"/api/v1/products/merges/{resultado['merge_id']}/undo")
    assert otra_vez.status_code == 422
    assert otra_vez.json()["error"]["codigo"] == "producto_no_fusionado"


async def test_no_se_puede_fusionar_un_producto_consigo_mismo(cliente):
    producto = await crear_producto(cliente, name="Pan de molde")
    respuesta = await cliente.post(
        "/api/v1/products/merge",
        json={"source_ids": [producto["id"]], "target_id": producto["id"]},
    )
    assert respuesta.status_code == 422


async def test_separar_un_producto_mal_fusionado(cliente, entorno):
    """RN-65: se saca lo observado en un comercio a un producto nuevo."""
    mezclado = await crear_producto(cliente, name="Aceite oliva")
    uno = await crear_comercio(entorno.household_id, "El Ahorro")
    otro = await crear_comercio(entorno.household_id, "Gourmet Selecto")
    await registrar_precio(
        cliente, mezclado, payee_id=str(uno), observed_at="2026-06-01", unit_price="8.95"
    )
    await registrar_precio(
        cliente, mezclado, payee_id=str(otro), observed_at="2026-06-02", unit_price="19.90"
    )

    respuesta = await cliente.post(
        f"/api/v1/products/{mezclado['id']}/split",
        json={
            "payee_id": str(otro),
            "new_product": {"name": "Aceite oliva ecológico gourmet"},
        },
    )
    assert respuesta.status_code == 200
    resultado = respuesta.json()
    assert resultado["prices_moved"] == 1
    assert resultado["target"]["name"] == "Aceite oliva ecológico gourmet"

    origen = (await cliente.get(f"/api/v1/products/{mezclado['id']}")).json()
    assert origen["observations_count"] == 1
    assert origen["last_unit_price"] == "8.95"
    nuevo = (await cliente.get(f"/api/v1/products/{resultado['target']['id']}")).json()
    assert nuevo["observations_count"] == 1
    assert nuevo["last_unit_price"] == "19.9"


async def test_separar_sin_decir_que_se_saca_es_invalido(cliente):
    producto = await crear_producto(cliente, name="Aceite oliva")
    respuesta = await cliente.post(
        f"/api/v1/products/{producto['id']}/split",
        json={"new_product": {"name": "Otro aceite"}},
    )
    assert respuesta.status_code == 422


# --------------------------------------------------------------------------- #
# Borrado
# --------------------------------------------------------------------------- #


async def test_borrar_un_producto_con_historial_exige_decidir(cliente, entorno):
    producto = await crear_producto(cliente, name="Café molido natural")
    await registrar_precio(cliente, producto, observed_at="2026-08-01", unit_price="3.40")

    conflicto = await cliente.delete(f"/api/v1/products/{producto['id']}")
    assert conflicto.status_code == 409

    destino = await crear_producto(cliente, name="Café molido de tueste natural")
    reasignado = await cliente.delete(
        f"/api/v1/products/{producto['id']}", params={"reassign_to": destino["id"]}
    )
    assert reasignado.status_code == 204
    assert (await cliente.get(f"/api/v1/products/{destino['id']}")).json()[
        "observations_count"
    ] == 1

    assert await contar(Product, entorno) == 1


# --------------------------------------------------------------------------- #
# Integración con las facturas y tenencia
# --------------------------------------------------------------------------- #


async def test_el_catalogo_nace_de_las_facturas_y_guarda_los_alias(cliente, entorno):
    await subir_y_confirmar(cliente, entorno, SUPERMERCADO[0])
    await subir_y_confirmar(cliente, entorno, SUPERMERCADO[1])

    assert await contar(Product, entorno) == 5
    # Una grafía por producto: RapidFuzz corre una vez por grafía nueva.
    assert await contar(ProductAlias, entorno) == 5
    assert await contar(ProductPrice, entorno) == 10

    filtrado = (await cliente.get("/api/v1/products", params={"q": "aceite"})).json()
    assert filtrado["total"] == 1
    assert "ACEITE" in filtrado["items"][0]["name"]

    con_subida = (
        await cliente.get("/api/v1/products", params={"has_increase": True, "size": 50})
    ).json()
    assert any("ACEITE" in fila["name"] for fila in con_subida["items"])


async def test_aislamiento_del_catalogo_entre_hogares(aplicacion, entorno):
    otro = await crear_entorno(email="bruno", nombre="Casa de Bruno")

    async with cliente_para(aplicacion, entorno.usuario_id) as de_ana:
        producto = await crear_producto(cliente=de_ana, name="Aceite oliva virgen extra")
        await registrar_precio(de_ana, producto, observed_at="2026-08-01", unit_price="9.00")

    async with cliente_para(aplicacion, otro.usuario_id) as de_bruno:
        assert (await de_bruno.get("/api/v1/products")).json()["total"] == 0
        assert (await de_bruno.get(f"/api/v1/products/{producto['id']}")).status_code == 404
        assert (await de_bruno.get(f"/api/v1/products/{producto['id']}/prices")).status_code == 404
        assert (await de_bruno.get("/api/v1/prices")).json()["total"] == 0
        # Y el mismo nombre en el otro hogar es un producto distinto, no un choque.
        propio = await crear_producto(cliente=de_bruno, name="Aceite oliva virgen extra")
        assert propio["id"] != producto["id"]

    assert await contar(Product, entorno) == 1
    assert await contar(Product, otro) == 1
    assert await contar(ProductPrice, otro) == 0


async def test_el_precio_unitario_no_se_redondea_a_centimos(cliente, entorno):
    """RN-61: el kWh de la luz llega con seis decimales y se guarda con cuatro."""
    factura = (await subir_factura(cliente, "luz-2026-06.pdf")).json()
    await confirmar_factura(
        cliente, entorno, factura["id"], default_category_id=str(entorno.luz_id)
    )
    precios = await filas(ProductPrice, entorno)
    energia = next(precio for precio in precios if precio.unit_price == Decimal("0.1389"))
    assert energia.unit_price.as_tuple().exponent == -4
