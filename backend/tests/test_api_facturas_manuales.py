"""Alta de una factura a mano, sin PDF (el ticket de papel).

Lo que se comprueba aquí no es que el endpoint responda 201: es que una factura
metida a mano **sirve para lo mismo** que una extraída de un PDF. Si no acaba en
el catálogo de productos y en el histórico de precios, teclearla no vale la pena
y es mejor no ofrecer la opción.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.categoria import Category
from app.models.factura import Invoice, InvoiceLine
from app.models.producto import Product, ProductPrice
from app.models.transaccion import Transaction
from tests import test_api_facturas as andamio
from tests.test_api_facturas import Entorno, SesionPrueba, contar, filas

# Las fixturas del andamio se reexportan para que pytest las resuelva por nombre.
aplicacion = andamio.aplicacion
cliente = andamio.cliente
ejemplos = andamio.ejemplos
entorno = andamio.entorno

RUTA = "/api/v1/invoices/manual"


def factura_de_papel(entorno: Entorno, **extra) -> dict:
    """Una compra del súper como la teclearía una persona con el ticket delante."""
    cuerpo = {
        "issuer": "Supermaxi",
        "number": "001-001-000012345",
        "date": "2026-08-14",
        "total": "23.55",
        "category_id": str(entorno.categoria_id),
        "lines": [
            {"description": "Arroz Flor 2 kg", "quantity": "1", "unit_price": "3.45"},
            {"description": "Aceite Girasol 1 L", "quantity": "2", "unit_price": "4.80"},
            {"description": "Leche Toni 1 L", "quantity": "6", "unit_price": "1.75"},
        ],
    }
    cuerpo.update(extra)
    return cuerpo


# --------------------------------------------------------------------------- #
# El alta
# --------------------------------------------------------------------------- #


async def test_una_factura_a_mano_queda_igual_que_una_extraida(cliente, entorno):
    respuesta = await cliente.post(RUTA, json=factura_de_papel(entorno))

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "pending_review"
    assert cuerpo["issuer"] == "Supermaxi"
    assert cuerpo["total"] == "23.55"
    # Lo ha escrito una persona mirando el papel: no hay nada que dudar.
    assert cuerpo["confidence"] == 1.0
    assert cuerpo["lines_count"] == 3
    assert len(cuerpo["lines"]) == 3


async def test_no_tiene_documento_y_lo_dice_en_vez_de_fingirlo(cliente, entorno):
    """El campo va a nulo a propósito: la interfaz no debe ofrecer «ver original»."""
    creada = (await cliente.post(RUTA, json=factura_de_papel(entorno))).json()

    assert creada["file_url"] is None
    assert creada["filename"] is None
    assert creada["checksum"] is None
    assert creada["size_bytes"] is None

    descarga = await cliente.get(f"/api/v1/invoices/{creada['id']}/file")
    assert descarga.status_code == 404
    assert "no tiene documento original" in descarga.json()["error"]["mensaje"]


async def test_el_total_de_cada_linea_se_calcula_solo(cliente, entorno):
    """Se teclea cantidad y precio; el producto lo hace el servidor (RN-41)."""
    cuerpo = (await cliente.post(RUTA, json=factura_de_papel(entorno))).json()
    totales = {linea["description"]: linea["total"] for linea in cuerpo["lines"]}

    assert totales["Arroz Flor 2 kg"] == "3.45"
    assert totales["Aceite Girasol 1 L"] == "9.60"
    assert totales["Leche Toni 1 L"] == "10.50"
    assert cuerpo["lines_sum"] == "23.55"


async def test_una_factura_sin_lineas_se_admite(cliente, entorno):
    """A veces solo se sabe el total, y es mejor eso que no apuntar nada."""
    respuesta = await cliente.post(
        RUTA,
        json={
            "issuer": "Farmacia Sana",
            "date": "2026-08-14",
            "total": "12.30",
            "category_id": str(entorno.categoria_id),
        },
    )

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["lines_count"] == 0


# --------------------------------------------------------------------------- #
# El concepto: la temática se elige o se crea
# --------------------------------------------------------------------------- #


async def test_un_concepto_nuevo_crea_la_tematica(cliente, entorno):
    cuerpo = factura_de_papel(entorno)
    del cuerpo["category_id"]
    cuerpo["category_name"] = "Ferretería del barrio"

    creada = (await cliente.post(RUTA, json=cuerpo)).json()

    assert creada["status"] == "pending_review"
    nuevas = await filas(Category, entorno, Category.name == "Ferretería del barrio")
    assert len(nuevas) == 1
    assert nuevas[0].kind == "expense"
    # Y las líneas heredan esa temática, o al confirmar se quedarían fuera de la
    # barra del presupuesto.
    assert {linea["category_id"] for linea in creada["lines"]} == {str(nuevas[0].id)}


async def test_un_concepto_que_ya_existe_no_crea_una_gemela(cliente, entorno):
    """«alimentacion» cuando ya hay «Alimentación» no son dos temáticas."""
    original = (await filas(Category, entorno, Category.template_key == "groceries.supermarket"))[0]
    cuerpo = factura_de_papel(entorno)
    del cuerpo["category_id"]
    cuerpo["category_name"] = original.name.upper()

    creada = (await cliente.post(RUTA, json=cuerpo)).json()

    assert {linea["category_id"] for linea in creada["lines"]} == {str(original.id)}
    assert await contar(Category, entorno, Category.name == original.name) == 1


async def test_el_concepto_no_puede_venir_de_las_dos_formas(cliente, entorno):
    cuerpo = factura_de_papel(entorno)
    cuerpo["category_name"] = "Otra cosa"

    respuesta = await cliente.post(RUTA, json=cuerpo)

    assert respuesta.status_code == 422
    assert "no las dos" in respuesta.text


async def test_guardar_y_confirmar_de_una_vez_exige_el_concepto(cliente, entorno):
    """Un movimiento sin temática queda fuera de la barra: mejor no dejarlo pasar."""
    cuerpo = factura_de_papel(entorno)
    del cuerpo["category_id"]
    cuerpo["account_id"] = str(entorno.cuenta_id)

    respuesta = await cliente.post(RUTA, json=cuerpo)

    assert respuesta.status_code == 422
    assert "hace falta la temática" in respuesta.text


# --------------------------------------------------------------------------- #
# Lo que de verdad importa: que sirva para lo mismo que un PDF
# --------------------------------------------------------------------------- #


async def test_con_cuenta_se_confirma_y_genera_el_movimiento(cliente, entorno):
    respuesta = await cliente.post(
        RUTA, json=factura_de_papel(entorno, account_id=str(entorno.cuenta_id))
    )

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "confirmed"
    assert cuerpo["transaction_id"] is not None

    movimiento = (
        await filas(Transaction, entorno, Transaction.id == uuid.UUID(cuerpo["transaction_id"]))
    )[0]
    # Los importes se guardan firmados: un gasto es negativo (`models/transaccion.py`).
    assert movimiento.amount == Decimal("-23.55")
    assert movimiento.kind == "expense"


async def test_una_factura_a_mano_alimenta_el_historico_de_precios(cliente, entorno):
    """La razón de ser del alta manual: sin esto, teclearla no valdría la pena."""
    await cliente.post(RUTA, json=factura_de_papel(entorno, account_id=str(entorno.cuenta_id)))

    productos = await filas(Product, entorno)
    assert {p.name for p in productos} == {
        "Arroz Flor 2 kg",
        "Aceite Girasol 1 L",
        "Leche Toni 1 L",
    }

    precios = await filas(ProductPrice, entorno)
    por_producto = {p.product_id: p for p in precios}
    assert len(por_producto) == 3
    aceite = next(p for p in productos if p.name.startswith("Aceite"))
    assert por_producto[aceite.id].unit_price == Decimal("4.8000")


async def test_dos_facturas_a_mano_distintas_no_son_duplicadas(cliente, entorno):
    """Ninguna tiene checksum, y `None == None` las hacía «idénticas».

    El resultado era que la segunda factura que metías a mano se rechazaba como
    duplicada de la primera, con confianza 1,0, aunque no tuvieran nada que ver.
    """
    primera = factura_de_papel(entorno, account_id=str(entorno.cuenta_id))
    assert (await cliente.post(RUTA, json=primera)).status_code == 201

    otra = factura_de_papel(
        entorno,
        account_id=str(entorno.cuenta_id),
        issuer="Farmacia Sana",
        number="002-004-000000777",
        date="2026-08-20",
        total="9.99",
    )
    otra["lines"] = [{"description": "Ibuprofeno 400 mg", "quantity": "1", "unit_price": "9.99"}]

    respuesta = await cliente.post(RUTA, json=otra)

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["status"] == "confirmed"


async def test_dos_compras_a_mano_dan_la_variacion_de_precio(cliente, entorno):
    """El aceite sube de 4,80 a 5,60: es lo que el usuario quiere ver."""
    await cliente.post(
        RUTA,
        json=factura_de_papel(entorno, date="2026-07-14", account_id=str(entorno.cuenta_id)),
    )
    segunda = factura_de_papel(entorno, account_id=str(entorno.cuenta_id))
    segunda["lines"] = [
        {"description": "Aceite Girasol 1 L", "quantity": "2", "unit_price": "5.60"}
    ]
    segunda["total"] = "11.20"
    # Otro número, como en la vida real: con el mismo, RN-45 la detecta duplicada.
    segunda["number"] = "001-001-000012399"
    r2 = await cliente.post(RUTA, json=segunda)
    assert r2.status_code == 201, r2.text

    aceite = next(p for p in await filas(Product, entorno) if p.name.startswith("Aceite"))
    observaciones = sorted(
        await filas(ProductPrice, entorno, ProductPrice.product_id == aceite.id),
        key=lambda p: p.priced_on,
    )

    assert [o.unit_price for o in observaciones] == [Decimal("4.8000"), Decimal("5.6000")]
    # +16,67 %, calculado contra la observación anterior del mismo comercio.
    assert observaciones[1].change_pct is not None
    assert round(float(observaciones[1].change_pct), 1) == 16.7


async def test_si_falla_anotar_el_gasto_la_factura_no_se_pierde_y_se_avisa(cliente, entorno):
    """El caso feo: guardar y confirmar de una vez, y que la confirmación falle.

    La factura ya está guardada cuando se intenta confirmar. Borrarla sería tirar
    lo que el usuario acabó de teclear; dejarla con un error a secas es peor,
    porque cree que no se guardó nada, lo vuelve a teclear y acaba con dos.
    """
    cuerpo = factura_de_papel(entorno, account_id=str(entorno.cuenta_id))
    # Las líneas suman 23,55 y aquí se dice que el total es otro, sin aceptarlo.
    cuerpo["total"] = "30.00"

    respuesta = await cliente.post(RUTA, json=cuerpo)

    assert respuesta.status_code == 422
    mensaje = respuesta.json()["error"]["mensaje"]
    assert "no cuadra" in mensaje or "suman" in mensaje
    assert "sí se ha guardado" in mensaje
    # Y está de verdad, esperando revisión.
    guardadas = await filas(Invoice, entorno)
    assert len(guardadas) == 1
    assert guardadas[0].status == "pending_review"


# --------------------------------------------------------------------------- #
# La invariante del fichero
# --------------------------------------------------------------------------- #


async def test_la_base_de_datos_no_admite_una_factura_subida_sin_fichero(entorno):
    """La restricción cambió de «toda factura tiene fichero» a «lo tiene si vino
    de uno». La segunda mitad tiene que seguir siendo imposible."""
    async with SesionPrueba() as sesion:
        sesion.add(
            Invoice(
                household_id=entorno.household_id,
                status="pending_review",
                source="upload",  # dice que vino de un fichero, pero no lo trae
                total_amount=Decimal("10.00"),
                currency="USD",
            )
        )
        with pytest.raises(IntegrityError):
            await sesion.commit()


async def test_borrar_una_factura_a_mano_no_falla_por_buscar_su_fichero(cliente, entorno):
    creada = (await cliente.post(RUTA, json=factura_de_papel(entorno))).json()

    respuesta = await cliente.delete(f"/api/v1/invoices/{creada['id']}")

    assert respuesta.status_code == 204, respuesta.text
    assert await contar(Invoice, entorno, Invoice.id == uuid.UUID(creada["id"])) == 0
    assert (
        await contar(InvoiceLine, entorno, InvoiceLine.invoice_id == uuid.UUID(creada["id"])) == 0
    )
