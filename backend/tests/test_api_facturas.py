"""Flujo completo de facturas contra PostgreSQL real.

Aquí vive además el andamio que comparten `test_api_productos.py` y
`test_api_informes.py`: el motor de pruebas, la aplicación con los seis routers
montados y el hogar de ejemplo. Se monta una `FastAPI` propia en lugar de usar
`app.main` porque el agregador de `app/api/v1/__init__.py` no es de este módulo.

Las facturas son las de `ejemplos/facturas/`, generadas con
`scripts/generar_facturas_ejemplo.py`: tres compras del mismo supermercado en
meses distintos donde el aceite sube del 8,95 € al 11,45 €.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1 import ajustes, alertas, facturas, importaciones, informes, productos
from app.core.config import settings
from app.core.errors import registrar_manejadores
from app.core.security import create_access_token
from app.db.semillas import copiar_plantillas_a_hogar
from app.db.session import get_session
from app.models.alerta import Alert
from app.models.categoria import Category
from app.models.cuenta import Account
from app.models.factura import Invoice, InvoiceLine
from app.models.hogar import Household, HouseholdMember
from app.models.producto import Product, ProductAlias, ProductPrice
from app.models.transaccion import Transaction, TransactionSplit
from app.models.usuario import User

# --------------------------------------------------------------------------- #
# Andamio compartido
# --------------------------------------------------------------------------- #

#: PostgreSQL de verdad: el emparejado usa `pg_trgm`, las vistas de informes son
#: SQL de PostgreSQL y el invariante de los splits lo sostiene un disparador.
URL_PRUEBAS = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://presupuesto:presupuesto@localhost:5432/presupuesto",
)

#: `NullPool` porque pytest-asyncio abre un bucle de eventos por test y una
#: conexión del pool no se puede reutilizar desde otro bucle.
MOTOR = create_async_engine(URL_PRUEBAS, poolclass=NullPool)
SesionPrueba = async_sessionmaker(bind=MOTOR, class_=AsyncSession, expire_on_commit=False)

RAIZ = Path(__file__).resolve().parents[2]
EJEMPLOS = RAIZ / "ejemplos" / "facturas"

SUPERMERCADO = ("supermercado-2026-06.pdf", "supermercado-2026-07.pdf", "supermercado-2026-08.pdf")
LUZ = ("luz-2026-06.pdf", "luz-2026-07.pdf", "luz-2026-08.pdf")

CSRF = "token-csrf-de-pruebas"
MODULOS = (facturas, productos, informes, importaciones, alertas, ajustes)


@dataclass(slots=True)
class Entorno:
    """Un hogar de pruebas ya montado: usuario, temáticas y cuenta."""

    usuario_id: uuid.UUID
    household_id: uuid.UUID
    cuenta_id: uuid.UUID
    categoria_id: uuid.UUID
    luz_id: uuid.UUID


async def _sesion_de_prueba():
    """Sustituye a `get_session`: misma forma, pero contra el PostgreSQL de test."""
    async with SesionPrueba() as sesion:
        try:
            yield sesion
        except Exception:
            await sesion.rollback()
            raise


@pytest.fixture(scope="session", autouse=True)
def ejemplos() -> Path:
    """Las facturas de ejemplo, generándolas si aún no están."""
    if not (EJEMPLOS / SUPERMERCADO[0]).is_file():
        subprocess.run(  # noqa: S603 - script del propio repositorio
            [sys.executable, str(RAIZ / "scripts" / "generar_facturas_ejemplo.py"), str(EJEMPLOS)],
            check=True,
            cwd=RAIZ,
        )
    return EJEMPLOS


@pytest.fixture
def aplicacion(tmp_path, monkeypatch) -> FastAPI:
    """La API con los seis routers de este módulo y ficheros en un temporal."""
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    # El OCR es lo más caro del sistema y ninguna factura de ejemplo lo necesita.
    monkeypatch.setattr(settings, "ocr_enabled", False)
    aplicacion = FastAPI()
    registrar_manejadores(aplicacion)
    for modulo in MODULOS:
        aplicacion.include_router(modulo.router, prefix=settings.api_prefix)
    aplicacion.dependency_overrides[get_session] = _sesion_de_prueba
    return aplicacion


async def crear_entorno(email: str = "ana", nombre: str = "Casa de Ana") -> Entorno:
    """Da de alta un usuario con su hogar, el árbol de temáticas y una cuenta.

    Cada test trabaja en un hogar recién creado y **nunca** vacía tablas
    compartidas: el aislamiento es el mismo que sostiene la multi-tenencia en
    producción, así que las pruebas no se estorban entre ellas ni con nada más
    que esté usando la misma base de datos.
    """
    async with SesionPrueba() as sesion:
        usuario = User(
            email=f"{email}-{uuid.uuid4().hex[:12]}@example.com",
            password_hash="hash-de-pruebas",
            display_name=nombre,
            is_active=True,
        )
        sesion.add(usuario)
        await sesion.flush()

        hogar = Household(name=nombre, created_by_id=usuario.id)
        sesion.add(hogar)
        await sesion.flush()
        sesion.add(
            HouseholdMember(
                household_id=hogar.id,
                user_id=usuario.id,
                role="owner",
                is_default=True,
                accepted_at=datetime.now(UTC),
            )
        )
        await copiar_plantillas_a_hogar(sesion, hogar.id)

        cuenta = Account(
            household_id=hogar.id,
            name="Cuenta corriente",
            type="checking",
            account_class="asset",
            opening_balance=Decimal("2000.00"),
        )
        sesion.add(cuenta)
        await sesion.commit()

        async def tematica(clave: str) -> uuid.UUID:
            return (
                await sesion.execute(
                    select(Category.id).where(
                        Category.household_id == hogar.id, Category.template_key == clave
                    )
                )
            ).scalar_one()

        return Entorno(
            usuario_id=usuario.id,
            household_id=hogar.id,
            cuenta_id=cuenta.id,
            categoria_id=await tematica("groceries.supermarket"),
            luz_id=await tematica("housing.electricity"),
        )


def cliente_para(aplicacion: FastAPI, usuario_id: uuid.UUID) -> AsyncClient:
    """Cliente con la cookie de sesión y el doble envío del token CSRF."""
    cliente = AsyncClient(
        transport=ASGITransport(app=aplicacion), base_url="http://pruebas", timeout=60.0
    )
    cliente.cookies.set("access_token", create_access_token(str(usuario_id)))
    cliente.cookies.set("csrf_token", CSRF)
    cliente.headers["X-CSRF-Token"] = CSRF
    return cliente


@pytest.fixture
async def entorno() -> Entorno:
    return await crear_entorno()


@pytest.fixture
async def cliente(aplicacion, entorno):
    async with cliente_para(aplicacion, entorno.usuario_id) as cliente:
        yield cliente


async def contar(modelo, entorno: Entorno, *condiciones) -> int:
    """Cuántas filas de ese modelo tiene el hogar del entorno."""
    async with SesionPrueba() as sesion:
        return (
            await sesion.execute(
                select(func.count(modelo.id)).where(
                    modelo.household_id == entorno.household_id, *condiciones
                )
            )
        ).scalar_one()


async def filas(modelo, entorno: Entorno, *condiciones) -> list:
    """Las filas de ese modelo que hay en el hogar del entorno."""
    async with SesionPrueba() as sesion:
        return list(
            (
                await sesion.execute(
                    select(modelo).where(modelo.household_id == entorno.household_id, *condiciones)
                )
            ).scalars()
        )


async def subir_factura(cliente: AsyncClient, nombre: str, *, como: str | None = None):
    """Sube una de las facturas de ejemplo y devuelve la respuesta cruda."""
    datos = (EJEMPLOS / nombre).read_bytes()
    return await cliente.post(
        "/api/v1/invoices",
        files={"fichero": (como or nombre, datos, "application/pdf")},
    )


async def confirmar_factura(
    cliente: AsyncClient, entorno: Entorno, invoice_id: str, **extra
) -> dict:
    cuerpo = {
        "account_id": str(entorno.cuenta_id),
        "default_category_id": str(entorno.categoria_id),
        **extra,
    }
    respuesta = await cliente.post(f"/api/v1/invoices/{invoice_id}/confirm", json=cuerpo)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


async def subir_y_confirmar(cliente: AsyncClient, entorno: Entorno, nombre: str) -> dict:
    respuesta = await subir_factura(cliente, nombre)
    assert respuesta.status_code == 202, respuesta.text
    return await confirmar_factura(cliente, entorno, respuesta.json()["id"])


# --------------------------------------------------------------------------- #
# Subida y validación del PDF (RN-43, RN-44, RN-75, RN-77)
# --------------------------------------------------------------------------- #


async def test_subir_valida_el_pdf_y_deja_la_factura_en_revision(cliente):
    respuesta = await subir_factura(cliente, SUPERMERCADO[0])
    assert respuesta.status_code == 202
    factura = respuesta.json()
    # La extracción es de segundo plano, así que la respuesta inmediata no la trae.
    assert factura["status"] == "processing"
    assert factura["checksum"] and len(factura["checksum"]) == 64

    estado = await cliente.get(f"/api/v1/invoices/{factura['id']}/status")
    assert estado.status_code == 200
    cuerpo = estado.json()
    assert cuerpo["status"] == "pending_review"
    assert cuerpo["progress"] == 100
    assert cuerpo["extraction_method"] == "tabla"
    assert cuerpo["lines_count"] == 5

    detalle = (await cliente.get(f"/api/v1/invoices/{factura['id']}")).json()
    assert detalle["issuer_tax_id"] == "B12345674"
    assert detalle["number"] == "FS-2026/0006"
    assert detalle["date"] == "2026-06-05"
    assert detalle["total"] == "37.48"
    assert detalle["taxable_base"] == "36.04"
    assert detalle["payee"] is None or detalle["payee"]["name"]


async def test_el_estado_responde_304_con_if_none_match(cliente):
    factura = (await subir_factura(cliente, SUPERMERCADO[0])).json()
    primera = await cliente.get(f"/api/v1/invoices/{factura['id']}/status")
    sello = primera.headers["ETag"]
    segunda = await cliente.get(
        f"/api/v1/invoices/{factura['id']}/status", headers={"If-None-Match": sello}
    )
    assert segunda.status_code == 304


async def test_la_misma_factura_dos_veces_se_detecta_como_duplicado(cliente, entorno):
    """RN-44: el mismo SHA-256 devuelve 200 con la factura anterior, no otra."""
    primera = await subir_factura(cliente, SUPERMERCADO[0])
    assert primera.status_code == 202

    segunda = await subir_factura(cliente, SUPERMERCADO[0], como="otro-nombre-cualquiera.pdf")
    assert segunda.status_code == 200
    assert segunda.json()["id"] == primera.json()["id"]

    bandeja = (await cliente.get("/api/v1/invoices")).json()
    assert bandeja["total"] == 1

    assert await contar(Invoice, entorno) == 1


async def test_un_html_con_nombre_pdf_se_rechaza(cliente, entorno):
    """RN-43: manda la firma del fichero, no el `content-type` ni la extensión."""
    falso = b"<html><body><h1>Factura</h1><p>no soy un PDF</p></body></html>"
    respuesta = await cliente.post(
        "/api/v1/invoices",
        files={"fichero": ("factura.pdf", falso, "application/pdf")},
    )
    assert respuesta.status_code == 415
    assert respuesta.json()["error"]["codigo"] == "tipo_no_soportado"

    assert await contar(Invoice, entorno) == 0


async def test_un_pdf_dañado_se_rechaza_como_pdf_invalido(cliente):
    respuesta = await cliente.post(
        "/api/v1/invoices",
        files={"fichero": ("roto.pdf", b"%PDF-1.7\nbasura que no es un PDF", "application/pdf")},
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["codigo"] == "pdf_invalido"


async def test_el_nombre_del_fichero_se_sanea(cliente):
    """RN-77: el nombre del cliente es metadato, y la ruta la calcula el servidor."""
    respuesta = await subir_factura(
        cliente, SUPERMERCADO[0], como="../../../etc/pásswórd; rm -rf.pdf"
    )
    factura = respuesta.json()
    assert "/" not in factura["filename"]
    assert ".." not in factura["filename"]
    assert factura["filename"].endswith(".pdf")

    descarga = await cliente.get(f"/api/v1/invoices/{factura['id']}/file")
    assert descarga.status_code == 200
    assert descarga.headers["content-type"] == "application/pdf"
    assert descarga.headers["x-content-type-options"] == "nosniff"


# --------------------------------------------------------------------------- #
# Revisión de líneas y sugerencias (§3.13, RN-41)
# --------------------------------------------------------------------------- #


async def test_las_lineas_llegan_con_confianza_y_normalizacion(cliente):
    factura = (await subir_factura(cliente, SUPERMERCADO[0])).json()
    cuerpo = (await cliente.get(f"/api/v1/invoices/{factura['id']}/lines")).json()

    assert cuerpo["status"] == "pending_review"
    assert len(cuerpo["lines"]) == 5
    assert cuerpo["lines_sum"] == "36.04"
    assert cuerpo["tolerance"] == "0.02"

    aceite = next(linea for linea in cuerpo["lines"] if "ACEITE" in linea["description"])
    assert aceite["unit_price"] == "8.95"
    assert aceite["total"] == "17.90"
    assert aceite["normalized"]["canonical"] == "aceite oliva virgen extra"
    assert aceite["normalized"]["size_value"] == "1"
    assert aceite["normalized"]["size_unit"] == "l"
    assert aceite["confidence"] >= 0.6


async def test_la_segunda_factura_trae_producto_ultimo_precio_y_variacion(cliente, entorno):
    """§3.13: la pantalla de revisión ya sabe qué producto es y cuánto ha subido."""
    await subir_y_confirmar(cliente, entorno, SUPERMERCADO[0])

    segunda = (await subir_factura(cliente, SUPERMERCADO[1])).json()
    cuerpo = (
        await cliente.get(
            f"/api/v1/invoices/{segunda['id']}/lines", params={"include_suggestions": True}
        )
    ).json()
    aceite = next(linea for linea in cuerpo["lines"] if "ACEITE" in linea["description"])

    assert aceite["product"] is not None
    assert "ACEITE" in aceite["product"]["name"]
    assert aceite["last_unit_price"] == "8.95"
    assert aceite["last_seen_on"] == "2026-06-05"
    assert aceite["change_pct"] == pytest.approx(9.5, abs=0.01)
    # La temática se recuerda de la vez anterior (F-17).
    assert aceite["suggested_category"] is not None
    assert aceite["suggested_category"]["id"] == str(entorno.categoria_id)


async def test_corregir_una_linea_recalcula_el_hueco_y_la_marca_editada(cliente):
    """RN-41: con dos de los tres valores se deduce el tercero."""
    factura = (await subir_factura(cliente, SUPERMERCADO[0])).json()
    lineas = (await cliente.get(f"/api/v1/invoices/{factura['id']}/lines")).json()["lines"]
    pan = next(linea for linea in lineas if "PAN" in linea["description"])

    respuesta = await cliente.patch(
        f"/api/v1/invoices/{factura['id']}/lines/{pan['id']}",
        json={"quantity": "3", "unit_price": "1.85"},
    )
    assert respuesta.status_code == 200
    corregida = respuesta.json()
    assert corregida["total"] == "5.55"
    assert corregida["is_edited"] is True
    assert corregida["confidence"] == 1.0


async def test_guardar_toda_la_revision_sustituye_el_conjunto(cliente, entorno):
    factura = (await subir_factura(cliente, SUPERMERCADO[0])).json()
    lineas = (await cliente.get(f"/api/v1/invoices/{factura['id']}/lines")).json()["lines"]

    respuesta = await cliente.put(
        f"/api/v1/invoices/{factura['id']}/lines",
        json={
            "lines": [
                {
                    "id": lineas[0]["id"],
                    "description": lineas[0]["description"],
                    "quantity": lineas[0]["quantity"],
                    "unit_price": lineas[0]["unit_price"],
                    "total": lineas[0]["total"],
                    "category_id": str(entorno.categoria_id),
                },
                {
                    "description": "BOLSA REUTILIZABLE",
                    "quantity": "1",
                    "unit_price": "0.15",
                    "total": "0.15",
                    "category_id": str(entorno.categoria_id),
                    "is_product": False,
                },
            ]
        },
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo["lines"]) == 2
    assert cuerpo["lines"][1]["description"] == "BOLSA REUTILIZABLE"
    assert cuerpo["lines"][1]["is_product"] is False
    assert [fila["line_number"] for fila in cuerpo["lines"]] == [1, 2]


async def test_anadir_y_borrar_lineas_a_mano(cliente, entorno):
    factura = (await subir_factura(cliente, SUPERMERCADO[0])).json()
    creada = await cliente.post(
        f"/api/v1/invoices/{factura['id']}/lines",
        json={
            "description": "AGUA MINERAL 1.5L",
            "quantity": "6",
            "unit_price": "0.45",
            "category_id": str(entorno.categoria_id),
        },
    )
    assert creada.status_code == 201
    assert creada.json()["total"] == "2.70"

    borrada = await cliente.delete(f"/api/v1/invoices/{factura['id']}/lines/{creada.json()['id']}")
    assert borrada.status_code == 204
    cuerpo = (await cliente.get(f"/api/v1/invoices/{factura['id']}/lines")).json()
    assert len(cuerpo["lines"]) == 5


async def test_vincular_una_linea_a_un_producto_nuevo_aprende_el_alias(cliente, entorno):
    """§3.13 paso 5: vincular guarda la grafía para la próxima factura."""
    factura = (await subir_factura(cliente, SUPERMERCADO[0])).json()
    lineas = (await cliente.get(f"/api/v1/invoices/{factura['id']}/lines")).json()["lines"]
    cafe = next(linea for linea in lineas if "CAFE" in linea["description"])
    await cliente.patch(
        f"/api/v1/invoices/{factura['id']}/lines/{cafe['id']}",
        json={"category_id": str(entorno.categoria_id)},
    )

    respuesta = await cliente.post(
        f"/api/v1/invoices/{factura['id']}/lines/{cafe['id']}/link-product",
        json={
            "new_product": {
                "name": "Café molido natural",
                "size_value": "250",
                "size_unit": "g",
                "unit": "ud",
            },
            "remember_alias": True,
            "set_default_category": True,
        },
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["product"]["name"] == "Café molido natural"

    alias = await filas(ProductAlias, entorno)
    assert any(uno.normalized_text == "cafe molido natural" for uno in alias)
    productos = await filas(Product, entorno)
    assert len(productos) == 1
    assert productos[0].category_id == entorno.categoria_id

    desvinculada = await cliente.delete(
        f"/api/v1/invoices/{factura['id']}/lines/{cafe['id']}/link-product"
    )
    assert desvinculada.status_code == 200
    assert desvinculada.json()["product_id"] is None


# --------------------------------------------------------------------------- #
# Confirmación (RN-42, RN-45, RN-46, RN-47, RN-48)
# --------------------------------------------------------------------------- #


async def test_confirmar_crea_transaccion_splits_y_observaciones_de_precio(cliente, entorno):
    factura = (await subir_factura(cliente, SUPERMERCADO[0])).json()
    resultado = await confirmar_factura(cliente, entorno, factura["id"])

    assert resultado["invoice"]["status"] == "confirmed"
    assert resultado["prices_registered"] == 5
    assert resultado["products_created"] == 5
    assert resultado["splits_created"] >= 5

    transacciones = await filas(Transaction, entorno)
    assert len(transacciones) == 1
    transaccion = transacciones[0]
    # Los importes son firmados: un gasto es negativo.
    assert transaccion.amount == Decimal("-37.48")
    assert transaccion.kind == "expense"
    assert transaccion.category_id is None
    assert transaccion.categorized_by == "invoice"

    splits = await filas(TransactionSplit, entorno)
    # El disparador mantiene el invariante: los splits suman el importe.
    assert sum(split.amount for split in splits) == transaccion.amount
    assert transaccion.split_total == transaccion.amount
    assert transaccion.split_count == len(splits)

    precios = await filas(ProductPrice, entorno)
    assert len(precios) == 5
    assert all(precio.source == "invoice" for precio in precios)
    assert all(precio.invoice_line_id is not None for precio in precios)


async def test_no_se_puede_confirmar_dos_veces(cliente, entorno):
    """RN-46: la confirmación es irrepetible."""
    factura = (await subir_factura(cliente, SUPERMERCADO[0])).json()
    await confirmar_factura(cliente, entorno, factura["id"])

    segunda = await cliente.post(
        f"/api/v1/invoices/{factura['id']}/confirm",
        json={
            "account_id": str(entorno.cuenta_id),
            "default_category_id": str(entorno.categoria_id),
        },
    )
    assert segunda.status_code == 409
    assert segunda.json()["error"]["codigo"] == "factura_ya_confirmada"

    assert await contar(Transaction, entorno) == 1
    assert await contar(ProductPrice, entorno) == 5


async def test_una_factura_confirmada_no_es_revisable(cliente, entorno):
    """RN-49: para editar hay que deshacer la confirmación primero."""
    factura = (await subir_factura(cliente, SUPERMERCADO[0])).json()
    await confirmar_factura(cliente, entorno, factura["id"])

    respuesta = await cliente.patch(
        f"/api/v1/invoices/{factura['id']}", json={"issuer": "Otro emisor"}
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["codigo"] == "factura_no_revisable"


async def test_confirmar_sin_cuadrar_exige_permiso_explicito(cliente, entorno):
    """RN-42: tolerancia de 0,02 € o base imponible; si no, `allow_total_mismatch`."""
    factura = (await subir_factura(cliente, SUPERMERCADO[0])).json()
    lineas = (await cliente.get(f"/api/v1/invoices/{factura['id']}/lines")).json()["lines"]
    await cliente.patch(
        f"/api/v1/invoices/{factura['id']}/lines/{lineas[0]['id']}",
        json={"total": "999.00"},
    )

    fallo = await cliente.post(
        f"/api/v1/invoices/{factura['id']}/confirm",
        json={
            "account_id": str(entorno.cuenta_id),
            "default_category_id": str(entorno.categoria_id),
        },
    )
    assert fallo.status_code == 422
    assert fallo.json()["error"]["codigo"] == "total_no_cuadra"

    resultado = await confirmar_factura(cliente, entorno, factura["id"], allow_total_mismatch=True)
    assert resultado["total_mismatch"] is not None


async def test_los_conceptos_de_una_factura_de_luz_no_contaminan_el_catalogo(cliente, entorno):
    """RN-48: potencia contratada y alquiler de contador no son productos."""
    factura = (await subir_factura(cliente, LUZ[0])).json()
    lineas = (await cliente.get(f"/api/v1/invoices/{factura['id']}/lines")).json()["lines"]
    assert len(lineas) == 3
    for linea in lineas:
        if "Energ" not in linea["description"]:
            respuesta = await cliente.patch(
                f"/api/v1/invoices/{factura['id']}/lines/{linea['id']}",
                json={"is_product": False, "category_id": str(entorno.luz_id)},
            )
            assert respuesta.json()["is_product"] is False

    resultado = await confirmar_factura(
        cliente,
        entorno,
        factura["id"],
        default_category_id=str(entorno.luz_id),
    )
    assert resultado["prices_registered"] == 1

    productos_creados = await filas(Product, entorno)
    assert len(productos_creados) == 1
    assert "Energ" in productos_creados[0].name
    # El precio del kWh conserva sus cuatro decimales (RN-61).
    observaciones = await filas(ProductPrice, entorno)
    assert len(observaciones) == 1
    assert observaciones[0].unit_price == Decimal("0.1389")


async def test_deshacer_la_confirmacion_es_la_inversa_exacta(cliente, entorno):
    """RN-50: se va la transacción, los precios y la alerta; vuelve a revisión."""
    await subir_y_confirmar(cliente, entorno, SUPERMERCADO[0])
    segunda = (await subir_factura(cliente, SUPERMERCADO[1])).json()
    await confirmar_factura(cliente, entorno, segunda["id"])

    assert await contar(ProductPrice, entorno) == 10
    assert await contar(Alert, entorno) >= 1

    respuesta = await cliente.post(f"/api/v1/invoices/{segunda['id']}/unconfirm")
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "pending_review"
    assert respuesta.json()["transaction_id"] is None

    assert await contar(Transaction, entorno) == 1
    assert await contar(ProductPrice, entorno) == 5
    assert await contar(Alert, entorno) == 0
    # Las líneas y su emparejado siguen ahí: solo se ha deshecho el volcado.
    assert await contar(InvoiceLine, entorno) == 10
    aceites = await filas(Product, entorno, Product.name.like("ACEITE%"))
    assert len(aceites) == 1
    assert aceites[0].last_unit_price == Decimal("8.95")
    assert aceites[0].price_observation_count == 1

    # Y se puede volver a confirmar sin duplicar nada.
    otra_vez = await confirmar_factura(cliente, entorno, segunda["id"])
    assert otra_vez["prices_registered"] == 5


async def test_duplicado_logico_por_emisor_numero_fecha_y_total(cliente, entorno):
    """RN-45: la misma factura reetiquetada se detecta por sus datos, no por bytes."""
    primera = (await subir_factura(cliente, SUPERMERCADO[0])).json()
    await confirmar_factura(cliente, entorno, primera["id"])

    # Mismo contenido lógico, bytes distintos: se cambia un byte del PDF original.
    datos = bytearray((EJEMPLOS / SUPERMERCADO[0]).read_bytes())
    datos.extend(b"\n% copia con otros bytes\n")
    segunda = await cliente.post(
        "/api/v1/invoices",
        files={"fichero": ("copia.pdf", bytes(datos), "application/pdf")},
    )
    assert segunda.status_code == 202
    identificador = segunda.json()["id"]

    candidatas = (await cliente.get(f"/api/v1/invoices/{identificador}/duplicates")).json()
    assert candidatas
    assert candidatas[0]["match_reason"] == "issuer_number_date_total"
    assert candidatas[0]["invoice_id"] == primera["id"]

    fallo = await cliente.post(
        f"/api/v1/invoices/{identificador}/confirm",
        json={
            "account_id": str(entorno.cuenta_id),
            "default_category_id": str(entorno.categoria_id),
        },
    )
    assert fallo.status_code == 409
    assert fallo.json()["error"]["codigo"] == "factura_duplicada"

    forzada = await confirmar_factura(cliente, entorno, identificador, ignore_duplicate=True)
    assert forzada["invoice"]["status"] == "confirmed"


# --------------------------------------------------------------------------- #
# Lo que hace que el producto valga la pena
# --------------------------------------------------------------------------- #


async def test_tres_facturas_construyen_el_historial_y_detectan_la_subida_del_aceite(
    cliente, entorno
):
    """El caso completo: misma cesta, tres meses, y el aceite sube un 16,8 %."""
    resultados = [await subir_y_confirmar(cliente, entorno, nombre) for nombre in SUPERMERCADO]

    # La primera factura no puede alertar de nada: no hay con qué comparar.
    assert resultados[0]["price_alerts"] == []
    assert resultados[0]["products_created"] == 5
    # Las siguientes reconocen los mismos productos por su clave de agrupación.
    assert resultados[1]["products_created"] == 0
    assert resultados[1]["products_linked"] == 5
    assert resultados[2]["products_created"] == 0

    subidas = {a["product"]["name"]: a["change_pct"] for a in resultados[2]["price_alerts"]}
    aceite = next(nombre for nombre in subidas if "ACEITE" in nombre)
    assert subidas[aceite] == pytest.approx(16.84, abs=0.01)

    catalogo = (await cliente.get("/api/v1/products", params={"size": 50})).json()
    assert catalogo["total"] == 5
    ficha = next(p for p in catalogo["items"] if "ACEITE" in p["name"])
    assert ficha["observations_count"] == 3
    assert ficha["last_unit_price"] == "11.45"
    assert ficha["min_unit_price"] == "8.95"
    assert ficha["trend"] == "sube"
    assert ficha["has_increase"] is True

    historial = (await cliente.get(f"/api/v1/products/{ficha['id']}/prices")).json()
    assert [fila["unit_price"] for fila in historial["items"]] == ["11.45", "9.8", "8.95"]
    assert [fila["observed_at"] for fila in historial["items"]] == [
        "2026-08-07",
        "2026-07-06",
        "2026-06-05",
    ]

    # Y la alerta de subida queda en la bandeja, una por factura y no una por producto.
    avisos = (await cliente.get("/api/v1/alerts")).json()
    assert avisos["total"] == 2
    assert all(aviso["type"] == "product_price_increase" for aviso in avisos["items"])
    assert (await cliente.get("/api/v1/alerts/unread-count")).json()["unread"] == 2


# --------------------------------------------------------------------------- #
# Tenencia (RN-01)
# --------------------------------------------------------------------------- #


async def test_aislamiento_entre_hogares(aplicacion, entorno):
    """Otro hogar no ve la factura, ni sus líneas, ni sus productos."""
    otro = await crear_entorno(email="bruno", nombre="Casa de Bruno")

    async with cliente_para(aplicacion, entorno.usuario_id) as de_ana:
        factura = (await subir_factura(de_ana, SUPERMERCADO[0])).json()
        await confirmar_factura(de_ana, entorno, factura["id"])
        catalogo = (await de_ana.get("/api/v1/products")).json()
        assert catalogo["total"] == 5

    async with cliente_para(aplicacion, otro.usuario_id) as de_bruno:
        assert (await de_bruno.get("/api/v1/invoices")).json()["total"] == 0
        assert (await de_bruno.get("/api/v1/products")).json()["total"] == 0
        assert (await de_bruno.get(f"/api/v1/invoices/{factura['id']}")).status_code == 404
        assert (await de_bruno.get(f"/api/v1/invoices/{factura['id']}/lines")).status_code == 404
        assert (
            await de_bruno.post(f"/api/v1/invoices/{factura['id']}/unconfirm")
        ).status_code == 404
        # Y pedir explícitamente el hogar ajeno es 403, no datos.
        assert (
            await de_bruno.get(
                "/api/v1/invoices", params={"household_id": str(entorno.household_id)}
            )
        ).status_code == 403


async def test_sin_cabecera_csrf_no_se_puede_escribir(aplicacion, entorno):
    """§1.11: el doble envío del token protege toda petición mutante."""
    async with AsyncClient(
        transport=ASGITransport(app=aplicacion), base_url="http://pruebas"
    ) as cliente:
        cliente.cookies.set("access_token", create_access_token(str(entorno.usuario_id)))
        cliente.cookies.set("csrf_token", CSRF)
        respuesta = await cliente.post(
            "/api/v1/invoices",
            files={"fichero": ("f.pdf", b"%PDF-1.7", "application/pdf")},
        )
        assert respuesta.status_code == 403
        assert respuesta.json()["error"]["codigo"] == "csrf_invalido"
