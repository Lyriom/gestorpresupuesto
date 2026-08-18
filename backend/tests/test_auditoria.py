"""Pruebas de la auditoría de seguridad y corrección del backend.

Cada prueba de este módulo se escribió **antes** del arreglo correspondiente y
falla con el código anterior. El informe con la lista completa de hallazgos está
en `docs/auditoria-backend.md`; aquí solo está la demostración de cada uno.

Van contra PostgreSQL de verdad (`docker compose up -d db`) porque casi todos los
hallazgos viven en la frontera entre el código y la base: claves ajenas
compuestas que no existen, `UPDATE ... FROM` sin desempate, disparadores que
recalculan la cabecera de un reparto.

El montaje se reutiliza de `test_api_auth.py` (una transacción por prueba que se
descarta al terminar). Lo único propio es `APP_COMPLETA`, con **todos** los
routers registrados: la aplicación de `test_api_auth` solo monta cuatro y aquí
hacen falta transferencias, facturas, productos y transacciones.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import test_api_auth as utillaje
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from test_api_auth import CONTRASENYA, PREFIJO, cabeceras, correo_nuevo, hogar_de, registrar

from app.api.deps import cliente_de
from app.api.v1 import api_router
from app.core.config import settings
from app.core.errors import registrar_manejadores
from app.core.security import CSRF_COOKIE_NAME, create_access_token, hash_password
from app.db.session import get_session
from app.models.categoria import Category
from app.models.comercio import Payee
from app.models.cuenta import Account, LoanTerms
from app.models.factura import ExtractionTemplate
from app.models.hogar import Household, HouseholdMember
from app.models.objetivo import Goal
from app.models.presupuesto import BudgetAllocation, BudgetPeriod
from app.models.producto import Product
from app.models.recurrente import RecurringOccurrence, RecurringRule
from app.models.transaccion import Transaction, TransactionSplit
from app.models.usuario import User
from app.services.extraccion_pdf import LineaExtraida
from app.services.formato import dinero
from app.services.numeros import parsear_importe

# Las fixtures del módulo base se reexportan por asignación, como hacen el resto
# de suites de API: pytest las descubre igual.
cliente = utillaje.cliente
navegadores = utillaje.navegadores
sesion_bd = utillaje.sesion_bd
limitador_limpio = utillaje.limitador_limpio

CSRF = "token-csrf-de-auditoria"
HOY = date.today()


def _crear_app() -> FastAPI:
    aplicacion = FastAPI()
    registrar_manejadores(aplicacion)
    aplicacion.include_router(api_router, prefix=PREFIJO)
    return aplicacion


APP_COMPLETA = _crear_app()


@pytest.fixture(autouse=True)
def sin_sustituciones() -> AsyncIterator[None]:
    """La sustitución de sesión no puede sobrevivir a la prueba que la puso."""
    yield
    APP_COMPLETA.dependency_overrides.clear()


def cliente_de_usuario(sesion: AsyncSession, usuario_id: uuid.UUID) -> AsyncClient:
    """Cliente con sesión abierta sobre `APP_COMPLETA` y el doble envío del CSRF."""

    async def _sesion() -> AsyncIterator[AsyncSession]:
        yield sesion

    APP_COMPLETA.dependency_overrides[get_session] = _sesion
    return AsyncClient(
        transport=ASGITransport(app=APP_COMPLETA),
        base_url="http://pruebas",
        cookies={"access_token": create_access_token(str(usuario_id)), CSRF_COOKIE_NAME: CSRF},
        headers={"X-CSRF-Token": CSRF},
    )


async def crear_hogar_ajeno(sesion: AsyncSession) -> tuple[Household, User]:
    """Un segundo hogar con su propietario, para las pruebas de tenencia."""
    hogar = Household(name="Hogar de al lado")
    usuario = User(
        email=correo_nuevo(),
        password_hash=hash_password(CONTRASENYA),
        display_name="Vecina",
    )
    sesion.add_all([hogar, usuario])
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
    await sesion.flush()
    return hogar, usuario


async def tematica_directa(sesion: AsyncSession, hogar: uuid.UUID, nombre: str) -> Category:
    """Temática sembrada por el modelo, con la caché del árbol coherente."""
    identificador = uuid.uuid4()
    categoria = Category(
        id=identificador,
        household_id=hogar,
        name=nombre,
        depth=0,
        path_ids=[identificador],
        sort_key="0000",
    )
    sesion.add(categoria)
    await sesion.flush()
    return categoria


# --------------------------------------------------------------------------- #
# 1. Aislamiento entre hogares
# --------------------------------------------------------------------------- #


async def test_una_transferencia_no_se_cuelga_del_fondo_de_otro_hogar(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """RN-01: `transactions.goal_id` no tiene clave ajena compuesta que lo tape.

    Antes del arreglo la petición devolvía 201 y las dos patas quedaban apuntando
    al fondo del hogar vecino.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)

    origen = Account(household_id=hogar, name="Nómina", type="checking", account_class="asset")
    destino = Account(household_id=hogar, name="Ahorro", type="savings", account_class="asset")
    sesion_bd.add_all([origen, destino])

    ajeno, _ = await crear_hogar_ajeno(sesion_bd)
    fondo_ajeno = Goal(
        household_id=ajeno.id, name="Viaje de la vecina", target_amount=Decimal("1000.00")
    )
    sesion_bd.add(fondo_ajeno)
    await sesion_bd.flush()

    async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
        respuesta = await propio.post(
            f"{PREFIJO}/transfers",
            json={
                "from_account_id": str(origen.id),
                "to_account_id": str(destino.id),
                "date": HOY.isoformat(),
                "amount": "10.00",
                "currency": "EUR",
                "goal_id": str(fondo_ajeno.id),
            },
        )

    assert respuesta.status_code == 404, respuesta.text
    colgadas = await sesion_bd.scalar(
        text("SELECT count(*) FROM transactions WHERE goal_id = :fondo"),
        {"fondo": fondo_ajeno.id},
    )
    assert colgadas == 0


async def test_una_factura_no_usa_la_plantilla_de_extraccion_de_otro_hogar(
    cliente: AsyncClient,
    sesion_bd: AsyncSession,
    factura_supermercado_texto: bytes,
    tmp_path: Path,
) -> None:
    """`extraction_templates.household_id` es nulable, así que no hay FK compuesta.

    Antes del arreglo la subida respondía 202 y la factura quedaba apuntando a la
    plantilla de otro hogar; con ella se habría interpretado el PDF.
    """
    correo = await registrar(cliente)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)
    ajeno, _ = await crear_hogar_ajeno(sesion_bd)
    plantilla = ExtractionTemplate(
        household_id=ajeno.id, name="Plantilla de la vecina", issuer_tax_id="B12345674"
    )
    sesion_bd.add(plantilla)
    await sesion_bd.flush()

    original = settings.upload_dir
    settings.upload_dir = tmp_path
    try:
        async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
            respuesta = await propio.post(
                f"{PREFIJO}/invoices",
                files={"fichero": ("factura.pdf", factura_supermercado_texto, "application/pdf")},
                data={"template_id": str(plantilla.id)},
            )
    finally:
        settings.upload_dir = original

    assert respuesta.status_code == 404, respuesta.text
    usadas = await sesion_bd.scalar(
        text("SELECT count(*) FROM invoices WHERE extraction_template_id = :plantilla"),
        {"plantilla": plantilla.id},
    )
    assert usadas == 0


async def test_un_producto_no_apunta_a_la_tematica_de_otro_hogar(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """La clave ajena compuesta lo impedía, pero con un 500 en vez del 404 de RN-02."""
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)
    ajeno, _ = await crear_hogar_ajeno(sesion_bd)
    tematica_ajena = await tematica_directa(sesion_bd, ajeno.id, "Ocio de la vecina")

    async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
        alta = await propio.post(
            f"{PREFIJO}/products",
            json={"name": "Leche entera 1 L", "default_category_id": str(tematica_ajena.id)},
        )
        assert alta.status_code == 404, alta.text

        propio_producto = Product(
            household_id=hogar, name="Leche", canonical_name="leche", grouping_key="leche"
        )
        sesion_bd.add(propio_producto)
        await sesion_bd.flush()

        parche = await propio.patch(
            f"{PREFIJO}/products/{propio_producto.id}",
            json={"default_category_id": str(tematica_ajena.id)},
        )

    assert parche.status_code == 404, parche.text


async def test_un_precio_no_apunta_al_comercio_de_otro_hogar(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)
    producto = Product(
        household_id=hogar, name="Aceite", canonical_name="aceite", grouping_key="aceite"
    )
    ajeno, _ = await crear_hogar_ajeno(sesion_bd)
    comercio_ajeno = Payee(
        household_id=ajeno.id, name="Súper de la vecina", normalized_name="super de la vecina"
    )
    sesion_bd.add_all([producto, comercio_ajeno])
    await sesion_bd.flush()

    async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
        respuesta = await propio.post(
            f"{PREFIJO}/prices",
            json={
                "product_id": str(producto.id),
                "observed_at": HOY.isoformat(),
                "unit_price": "1.2500",
                "payee_id": str(comercio_ajeno.id),
            },
        )

    assert respuesta.status_code == 404, respuesta.text


# --------------------------------------------------------------------------- #
# 2. Autenticación y límite de tasa
# --------------------------------------------------------------------------- #


async def test_el_limitador_no_se_esquiva_falsificando_x_forwarded_for(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient]
) -> None:
    """§2.4: la cabecera solo se cree si viene de un proxy declarado de confianza.

    Antes del arreglo bastaba con cambiar `X-Forwarded-For` en cada intento para
    tener un cubo de fichas nuevo, y el tope de cinco altas por hora no existía.
    """
    correo = await registrar(cliente)  # primer intento: consume una ficha

    otro = navegadores()
    await otro.get(f"{PREFIJO}/auth/csrf")
    cuerpo = {"email": correo, "password": CONTRASENYA, "name": "Otra"}
    codigos = []
    for numero in range(5):
        respuesta = await otro.post(
            f"{PREFIJO}/auth/register",
            json=cuerpo,
            headers={**cabeceras(otro), "X-Forwarded-For": f"203.0.113.{numero}"},
        )
        codigos.append(respuesta.status_code)

    # Los cuatro primeros son el 409 del correo repetido; el quinto ya no queda ficha.
    assert codigos[:4] == [409, 409, 409, 409], codigos
    assert codigos[4] == 429, codigos


async def test_el_429_del_limitador_lleva_retry_after(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient]
) -> None:
    """§2.4: un 429 sin `Retry-After` deja al cliente sin saber cuánto esperar."""
    correo = await registrar(cliente)
    otro = navegadores()
    await otro.get(f"{PREFIJO}/auth/csrf")
    cuerpo = {"email": correo, "password": CONTRASENYA, "name": "Otra"}
    respuesta = None
    for _ in range(6):
        respuesta = await otro.post(
            f"{PREFIJO}/auth/register", json=cuerpo, headers=cabeceras(otro)
        )
        if respuesta.status_code == 429:
            break

    assert respuesta is not None and respuesta.status_code == 429, respuesta
    assert int(respuesta.headers["retry-after"]) >= 1


async def test_el_429_del_bloqueo_por_credencial_lleva_retry_after(cliente: AsyncClient) -> None:
    """RN-05: cinco fallos bloquean el correo, y el 429 dice cuánto falta."""
    correo = await registrar(cliente)
    for _ in range(5):
        fallo = await cliente.post(
            f"{PREFIJO}/auth/login",
            json={"email": correo, "password": "Equivocada9"},
            headers=cabeceras(cliente),
        )
        assert fallo.status_code == 401

    bloqueado = await cliente.post(
        f"{PREFIJO}/auth/login",
        json={"email": correo, "password": CONTRASENYA},
        headers=cabeceras(cliente),
    )
    assert bloqueado.status_code == 429
    assert 1 <= int(bloqueado.headers["retry-after"]) <= 60


def test_la_ip_reenviada_solo_se_cree_a_un_proxy_de_confianza(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El arreglo no puede romper el despliegue detrás de EasyPanel."""
    peticion = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"198.51.100.7, 10.0.0.1")],
            "client": ("10.0.0.1", 5000),
        }
    )

    monkeypatch.setattr(settings, "trusted_proxies_crudo", "")
    assert cliente_de(peticion)[0] == "10.0.0.1"

    monkeypatch.setattr(settings, "trusted_proxies_crudo", "10.0.0.1")
    assert cliente_de(peticion)[0] == "198.51.100.7"

    monkeypatch.setattr(settings, "trusted_proxies_crudo", "*")
    assert cliente_de(peticion)[0] == "198.51.100.7"


# --------------------------------------------------------------------------- #
# 3. Ficheros adjuntos (RN-77, §8.3)
# --------------------------------------------------------------------------- #


async def test_el_nombre_del_adjunto_se_sanea_y_la_descarga_va_endurecida(
    cliente: AsyncClient, sesion_bd: AsyncSession, tmp_path: Path
) -> None:
    """RN-77 y §8.3.8.

    El nombre del adjunto se saneaba con reglas propias, mucho más laxas que las de
    `facturas.sanear_nombre()`: dejaba pasar `%`, `;`, `"` y los nombres reservados
    de Windows, y recortaba a 200 caracteres en lugar de 120. Ese texto acaba dentro
    de `Content-Disposition`, así que no es solo cosmética. La descarga, además, no
    llevaba ni `nosniff` ni `Content-Security-Policy: sandbox`.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)
    cuenta = Account(household_id=hogar, name="Nómina", type="checking", account_class="asset")
    sesion_bd.add(cuenta)
    tematica = await tematica_directa(sesion_bd, hogar, "Alimentación")
    await sesion_bd.flush()

    original = settings.upload_dir
    settings.upload_dir = tmp_path
    try:
        async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
            movimiento = await propio.post(
                f"{PREFIJO}/transactions",
                json={
                    "account_id": str(cuenta.id),
                    "date": HOY.isoformat(),
                    "amount": "12.00",
                    "category_id": str(tematica.id),
                },
            )
            assert movimiento.status_code == 201, movimiento.text

            subida = await propio.post(
                f"{PREFIJO}/transactions/{movimiento.json()['id']}/attachments",
                files={
                    "fichero": (
                        '../../../etc/re"cibo;x=1.pdf',
                        b"%PDF-1.4\n%%EOF\n",
                        "application/pdf",
                    )
                },
            )
            assert subida.status_code == 201, subida.text
            nombre = subida.json()["filename"]
            # RN-77: solo `[A-Za-z0-9 ._-]`, sin saltos de directorio y hasta 120.
            assert re.fullmatch(r"[A-Za-z0-9 ._-]+", nombre), nombre
            assert ".." not in nombre and len(nombre) <= 120

            largo = await propio.post(
                f"{PREFIJO}/transactions/{movimiento.json()['id']}/attachments",
                files={
                    "fichero": (
                        f"{'n' * 200}.pdf",
                        b"%PDF-1.4\n%%EOF\n",
                        "application/pdf",
                    )
                },
            )
            assert largo.status_code == 201, largo.text
            assert len(largo.json()["filename"]) <= 120

            reservado = await propio.post(
                f"{PREFIJO}/transactions/{movimiento.json()['id']}/attachments",
                files={"fichero": ("..\\..\\CON.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
            )
            assert reservado.status_code == 201, reservado.text
            assert reservado.json()["filename"].split(".")[0].lower() != "con"

            descarga = await propio.get(
                f"{PREFIJO}/attachments/{subida.json()['id']}/content?disposition=attachment"
            )
            assert descarga.status_code == 200
            assert '"' not in descarga.headers["content-disposition"].split("filename=")[1][1:-1]
            assert descarga.headers["x-content-type-options"] == "nosniff"
            assert descarga.headers["content-security-policy"] == "sandbox"
    finally:
        settings.upload_dir = original


# --------------------------------------------------------------------------- #
# 4. Dinero
# --------------------------------------------------------------------------- #


def test_el_importe_de_una_factura_redondea_al_alza_en_el_empate() -> None:
    """El contexto decimal de Python redondea al par: 12,345 € daba 12,34 €.

    PostgreSQL redondea al alza al guardar en `numeric(14,2)`, así que el mismo
    importe salía distinto según quién lo cuantizase.
    """
    assert parsear_importe("12,345") == Decimal("12.35")
    assert parsear_importe("0,125") == Decimal("0.13")
    # El signo no cambia la magnitud: se aleja del cero, como la base.
    assert parsear_importe("-12,345") == Decimal("-12.35")


def test_el_texto_de_un_importe_redondea_al_alza() -> None:
    """Es el número que el usuario lee en un aviso de presupuesto."""
    assert dinero(Decimal("2.665"), moneda="EUR") == "2,67 €"
    assert dinero(Decimal("-2.665"), moneda="EUR") == "-2,67 €"


def test_el_total_de_una_linea_de_factura_redondea_al_alza() -> None:
    """10 kWh a 0,2165 €/kWh son 2,17 €, no 2,16 €."""
    linea = LineaExtraida(
        descripcion="Energía consumida P1",
        cantidad=Decimal("10"),
        precio_unitario=Decimal("0.2165"),
    )
    linea.completar()
    assert linea.total == Decimal("2.17")


async def test_el_tipo_de_interes_no_se_redondea_a_centimos(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """`annual_rate` es `Numeric(7,4)` y se cuantizaba con el redondeo del dinero.

    Un 2,7550 % pasaba a 2,76 % antes de dividir por 1200: la cuota salía 0,37 €
    más alta y el préstamo acumulaba 88,93 € de intereses inventados.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)
    cuenta = Account(household_id=hogar, name="Hipoteca", type="loan", account_class="liability")
    sesion_bd.add(cuenta)
    await sesion_bd.flush()
    sesion_bd.add(
        LoanTerms(
            household_id=hogar,
            account_id=cuenta.id,
            principal=Decimal("150000.00"),
            annual_rate=Decimal("2.7550"),
            first_payment_on=date(2026, 1, 1),
            term_months=240,
        )
    )
    await sesion_bd.flush()

    async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
        respuesta = await propio.get(f"{PREFIJO}/accounts/{cuenta.id}/amortization")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["monthly_payment"] == "813.62"


# --------------------------------------------------------------------------- #
# 5. Saldos y proyección
# --------------------------------------------------------------------------- #


async def test_el_pendiente_de_recurrentes_es_de_la_cuenta_que_se_consulta(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """F-47: `pending_recurring` sumaba los vencimientos de todo el hogar.

    La cuenta no vive en la ocurrencia sino en su regla, y faltaba el join: las dos
    cuentas devolvían el mismo pendiente.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)
    con_recibo = Account(household_id=hogar, name="Nómina", type="checking", account_class="asset")
    sin_nada = Account(household_id=hogar, name="Ahorro", type="savings", account_class="asset")
    sesion_bd.add_all([con_recibo, sin_nada])
    await sesion_bd.flush()

    regla = RecurringRule(
        household_id=hogar,
        name="Alquiler",
        kind="expense",
        account_id=con_recibo.id,
        expected_amount=Decimal("-750.00"),
        frequency="mensual",
        starts_on=HOY,
    )
    sesion_bd.add(regla)
    await sesion_bd.flush()
    sesion_bd.add(
        RecurringOccurrence(
            household_id=hogar,
            recurring_rule_id=regla.id,
            due_on=HOY,
            status="pending",
            expected_amount=Decimal("-750.00"),
        )
    )
    await sesion_bd.flush()

    async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
        suya = await propio.get(f"{PREFIJO}/accounts/{con_recibo.id}/balance")
        ajena = await propio.get(f"{PREFIJO}/accounts/{sin_nada.id}/balance")

    assert suya.json()["pending_recurring"] == "-750.00", suya.text
    assert ajena.json()["pending_recurring"] == "0.00", ajena.text


# --------------------------------------------------------------------------- #
# 6. Fusión de temáticas y su reversión
# --------------------------------------------------------------------------- #


async def _tematica_api(cliente_http: AsyncClient, nombre: str) -> dict[str, Any]:
    respuesta = await cliente_http.post(
        f"{PREFIJO}/categories", headers=cabeceras(cliente_http), json={"name": nombre}
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


async def test_deshacer_una_fusion_de_dos_origenes_restaura_el_reparto_exacto(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """El diario se aplicaba con `max()` sobre el **texto** del importe.

    Con dos orígenes la misma línea se anota dos veces, y quedarse con el máximo
    lexicográfico devolvía un estado intermedio: el reparto restaurado sumaba
    −620,00 € para una transacción de −600,00 € y el invariante de la base tumbaba
    el deshacer con un 500 del que ya no se salía.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    cuenta = (
        await cliente.post(
            f"{PREFIJO}/accounts",
            headers=cabeceras(cliente),
            json={"name": "Nómina", "type": "checking", "initial_balance": "2000.00"},
        )
    ).json()

    destino = await _tematica_api(cliente, "Supermercado")
    primera = await _tematica_api(cliente, "Compra semanal")
    segunda = await _tematica_api(cliente, "Compra del mes")

    movimiento = Transaction(
        household_id=hogar,
        account_id=uuid.UUID(cuenta["id"]),
        kind="expense",
        booked_on=HOY,
        amount=Decimal("-600.00"),
        category_id=uuid.UUID(destino["id"]),
        description="Compra grande",
    )
    sesion_bd.add(movimiento)
    await sesion_bd.flush()
    for numero, (tematica, importe) in enumerate(
        ((destino, "-40.00"), (primera, "-20.00"), (segunda, "-540.00")), start=1
    ):
        sesion_bd.add(
            TransactionSplit(
                household_id=hogar,
                transaction_id=movimiento.id,
                category_id=uuid.UUID(tematica["id"]),
                amount=Decimal(importe),
                line_number=numero,
            )
        )
    await sesion_bd.flush()
    # El identificador se copia antes de las llamadas HTTP: los `commit()` de los
    # endpoints comparten sesión con la prueba y caducan los objetos del ORM.
    movimiento_id = movimiento.id
    await sesion_bd.commit()

    fusion = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [primera["id"], segunda["id"]], "target_id": destino["id"]},
    )
    assert fusion.status_code == 200, fusion.text

    deshacer = await cliente.post(
        f"{PREFIJO}/categories/merges/{fusion.json()['merge_id']}/undo",
        headers=cabeceras(cliente),
    )
    assert deshacer.status_code == 200, deshacer.text

    filas = (
        await sesion_bd.execute(
            text(
                "SELECT category_id, amount FROM transaction_splits "
                " WHERE transaction_id = :movimiento ORDER BY amount"
            ),
            {"movimiento": movimiento_id},
        )
    ).all()
    reparto = {str(fila.category_id): Decimal(str(fila.amount)) for fila in filas}
    assert reparto == {
        destino["id"]: Decimal("-40.00"),
        primera["id"]: Decimal("-20.00"),
        segunda["id"]: Decimal("-540.00"),
    }


async def test_deshacer_una_fusion_de_dos_origenes_restaura_el_presupuesto_exacto(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """`UPDATE ... FROM` con dos anotaciones candidatas elegía una cualquiera.

    Con dos orígenes, la asignación del destino se anota una vez por origen y con
    `old_value` distinto. PostgreSQL no promete qué fila usa —«which one is not
    readily predictable»—, así que el importe restaurado podía ser el intermedio.
    **Esta prueba fija el invariante y no reproduce el fallo**: con tan pocas filas
    el plan elige la correcta por suerte. La corrección es el desempate por `seq`.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    destino = await _tematica_api(cliente, "Supermercado")
    primera = await _tematica_api(cliente, "Compra semanal")
    segunda = await _tematica_api(cliente, "Compra del mes")

    periodo = BudgetPeriod(household_id=hogar, period_start=date(HOY.year, HOY.month, 1))
    sesion_bd.add(periodo)
    await sesion_bd.flush()
    for tematica, importe in ((destino, "320.00"), (primera, "180.00"), (segunda, "60.00")):
        sesion_bd.add(
            BudgetAllocation(
                household_id=hogar,
                budget_period_id=periodo.id,
                category_id=uuid.UUID(tematica["id"]),
                allocated_amount=Decimal(importe),
            )
        )
    await sesion_bd.flush()
    await sesion_bd.commit()

    fusion = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [primera["id"], segunda["id"]], "target_id": destino["id"]},
    )
    assert fusion.status_code == 200, fusion.text
    fusionado = await sesion_bd.scalar(
        text(
            "SELECT allocated_amount FROM budget_allocations "
            " WHERE household_id = :hogar AND category_id = :destino"
        ),
        {"hogar": hogar, "destino": uuid.UUID(destino["id"])},
    )
    assert Decimal(str(fusionado)) == Decimal("560.00")

    deshacer = await cliente.post(
        f"{PREFIJO}/categories/merges/{fusion.json()['merge_id']}/undo",
        headers=cabeceras(cliente),
    )
    assert deshacer.status_code == 200, deshacer.text

    filas = (
        await sesion_bd.execute(
            text(
                "SELECT category_id, allocated_amount FROM budget_allocations "
                " WHERE household_id = :hogar"
            ),
            {"hogar": hogar},
        )
    ).all()
    asignado = {str(fila.category_id): Decimal(str(fila.allocated_amount)) for fila in filas}
    assert asignado == {
        destino["id"]: Decimal("320.00"),
        primera["id"]: Decimal("180.00"),
        segunda["id"]: Decimal("60.00"),
    }


async def test_deshacer_no_resucita_activa_una_tematica_que_estaba_archivada(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """El diario anotaba `archived_at = None` como valor previo, cableado.

    Fusionar una temática ya archivada y deshacerlo la devolvía **activa**, con sus
    hijas archivadas y el árbol en un estado que la API no sabe producir.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    destino = await _tematica_api(cliente, "Supermercado")
    origen = await _tematica_api(cliente, "Compra semanal")

    archivar = await cliente.post(
        f"{PREFIJO}/categories/{origen['id']}/archive", headers=cabeceras(cliente)
    )
    assert archivar.status_code == 200, archivar.text

    fusion = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [origen["id"]], "target_id": destino["id"]},
    )
    assert fusion.status_code == 200, fusion.text
    deshacer = await cliente.post(
        f"{PREFIJO}/categories/merges/{fusion.json()['merge_id']}/undo",
        headers=cabeceras(cliente),
    )
    assert deshacer.status_code == 200, deshacer.text

    fila = (
        await sesion_bd.execute(
            text(
                "SELECT archived_at, merged_into_id FROM categories "
                " WHERE household_id = :hogar AND id = :origen"
            ),
            {"hogar": hogar, "origen": uuid.UUID(origen["id"])},
        )
    ).one()
    assert fila.merged_into_id is None
    assert fila.archived_at is not None, "seguía archivada antes de la fusión"


async def test_la_previa_no_cuenta_dos_veces_lo_asignado_del_destino(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """Con dos orígenes, `allocations_merged` sumaba el destino una vez por origen."""
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    destino = await _tematica_api(cliente, "Supermercado")
    primera = await _tematica_api(cliente, "Compra semanal")
    segunda = await _tematica_api(cliente, "Compra del mes")

    periodo = BudgetPeriod(household_id=hogar, period_start=date(HOY.year, HOY.month, 1))
    sesion_bd.add(periodo)
    await sesion_bd.flush()
    for tematica, importe in ((destino, "320.00"), (primera, "180.00"), (segunda, "60.00")):
        sesion_bd.add(
            BudgetAllocation(
                household_id=hogar,
                budget_period_id=periodo.id,
                category_id=uuid.UUID(tematica["id"]),
                allocated_amount=Decimal(importe),
            )
        )
    await sesion_bd.flush()

    previa = await cliente.post(
        f"{PREFIJO}/categories/merge/preview",
        headers=cabeceras(cliente),
        json={"source_ids": [primera["id"], segunda["id"]], "target_id": destino["id"]},
    )
    assert previa.status_code == 200, previa.text
    assert previa.json()["allocations_merged"] == "560.00"


async def test_una_operacion_hija_no_se_deshace_por_su_cuenta(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """La unidad atómica es la fusión completa, no cada par origen-destino.

    Deshacer la hija revertía media fusión y dejaba la madre en `done`: el deshacer
    de la madre volvía a insertar filas ya restauradas y acababa en 500.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    destino = await _tematica_api(cliente, "Supermercado")
    primera = await _tematica_api(cliente, "Compra semanal")
    segunda = await _tematica_api(cliente, "Compra del mes")

    fusion = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [primera["id"], segunda["id"]], "target_id": destino["id"]},
    )
    assert fusion.status_code == 200, fusion.text
    raiz = uuid.UUID(fusion.json()["merge_id"])
    hija = await sesion_bd.scalar(
        text(
            "SELECT id FROM merge_operations "
            " WHERE household_id = :hogar AND parent_merge_operation_id = :raiz LIMIT 1"
        ),
        {"hogar": hogar, "raiz": raiz},
    )
    assert hija is not None, "una fusión de dos orígenes crea operaciones hijas"

    suelta = await cliente.post(
        f"{PREFIJO}/categories/merges/{hija}/undo", headers=cabeceras(cliente)
    )
    assert suelta.status_code == 404, suelta.text

    # Y la madre sigue pudiéndose deshacer entera.
    entera = await cliente.post(
        f"{PREFIJO}/categories/merges/{raiz}/undo", headers=cabeceras(cliente)
    )
    assert entera.status_code == 200, entera.text


# --------------------------------------------------------------------------- #
# 7. Regresión de la ventana de deshacer
# --------------------------------------------------------------------------- #


async def test_una_fusion_caducada_no_se_deshace(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """RN-20: pasados treinta días el registro se poda y `undo` responde 409."""
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    destino = await _tematica_api(cliente, "Supermercado")
    origen = await _tematica_api(cliente, "Compra semanal")
    fusion = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [origen["id"]], "target_id": destino["id"]},
    )
    assert fusion.status_code == 200, fusion.text

    await sesion_bd.execute(
        text(
            "UPDATE merge_operations SET undo_deadline = :limite "
            " WHERE household_id = :hogar AND id = :operacion"
        ),
        {
            "limite": datetime.now(UTC) - timedelta(days=1),
            "hogar": hogar,
            "operacion": uuid.UUID(fusion.json()["merge_id"]),
        },
    )
    await sesion_bd.commit()

    caducada = await cliente.post(
        f"{PREFIJO}/categories/merges/{fusion.json()['merge_id']}/undo",
        headers=cabeceras(cliente),
    )
    assert caducada.status_code == 409, caducada.text
