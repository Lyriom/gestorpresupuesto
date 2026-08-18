"""Segunda vuelta de la auditoría: cierre de los pendientes reproducibles.

Continúa `test_auditoria.py` con las filas que la primera vuelta dejó abiertas.
El criterio es el mismo: **cada prueba se escribió antes del arreglo y falla con
el código anterior**, y lo que no se ha conseguido reproducir se queda sin tocar
y anotado en `docs/auditoria-backend.md`.

Lo que se cierra aquí:

1. El redondeo del dinero, centralizado en `formato.cuantizar()`. Además de las
   pruebas numéricas hay un **barrido del código fuente** (`ast`) que recorre
   todos los `quantize()` de `app/` y exige que los de dinero pasen por el
   ayudante: es la única forma de que la corrección no se deshaga sola la
   próxima vez que alguien escriba `.quantize(CENTIMO)`.
2. El `IndexError` de confirmar una factura con todas las líneas excluidas.
3. La huella de duplicados sin cuantizar.
4. El N+1 del listado de facturas, con un contador de consultas enganchado a
   `before_cursor_execute`. Esa misma fixture sirve para medir los otros dos.
5. Los dos 500 del deshacer de una fusión que deberían ser 409.
6. Cuatro medios más: el coste anual de una suscripción derivado del mensual ya
   redondeado, el prorrateo del presupuesto restante que perdía el céntimo, el
   `required_monthly` de un objetivo redondeado a la baja y —hallazgo nuevo, no
   estaba en el informe— `GET /reports/subscriptions`, que respondía **500 con
   cualquier suscripción** porque el informe leía `recurring_rules.frequency` con
   el vocabulario público en lugar del del motor.

Dos pruebas de este módulo **no** fallaban antes y se dicen así en su docstring:
la del ahorro máximo de la cesta (fija el invariante de que centralizar el
redondeo no descuadre los totales) y la de la CSP (la cabecera ya estaba; la fila
del informe era un error del informe).

El montaje se reutiliza de `test_auditoria.py` (una transacción por prueba que se
descarta al terminar, y `APP_COMPLETA` con todos los routers).
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import test_api_auth as utillaje
import test_auditoria as primera
from httpx import AsyncClient
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession
from test_api_auth import PREFIJO, cabeceras, hogar_de, registrar

from app.api.v1.facturas import _repartir
from app.core.errors import ReglaDeNegocio
from app.models.comercio import Payee
from app.models.cuenta import Account
from app.models.factura import Invoice, InvoiceLine
from app.models.presupuesto import BudgetAllocation, BudgetPeriod
from app.models.recurrente import RecurringRule
from app.models.transaccion import Transaction, TransactionSplit
from app.services import precios
from app.services.formato import CUATRO_DECIMALES, cuantizar
from app.services.importacion import calcular_huella

# Fixtures del módulo base, reexportadas por asignación como en el resto de suites.
cliente = utillaje.cliente
navegadores = utillaje.navegadores
sesion_bd = utillaje.sesion_bd
limitador_limpio = utillaje.limitador_limpio
sin_sustituciones = primera.sin_sustituciones

cliente_de_usuario = primera.cliente_de_usuario
tematica_directa = primera.tematica_directa
_tematica_api = primera._tematica_api

HOY = date.today()
RAIZ_APP = Path(__file__).resolve().parents[1] / "app"


# --------------------------------------------------------------------------- #
# 1. El redondeo del dinero, en un solo sitio
# --------------------------------------------------------------------------- #


def test_el_cuantizador_del_dinero_redondea_al_alza() -> None:
    """`ROUND_HALF_UP` y no el redondeo bancario del contexto de Python.

    Con el modo por defecto el empate cae a un lado o a otro según la cifra
    anterior: 12,345 € bajaba a 12,34 € y 12,355 € subía a 12,36 €. PostgreSQL
    sube siempre al guardar en `numeric(14,2)`.
    """
    assert cuantizar(Decimal("12.345")) == Decimal("12.35")
    assert cuantizar(Decimal("12.355")) == Decimal("12.36")
    assert cuantizar(Decimal("0.125")) == Decimal("0.13")
    # El signo no cambia la magnitud: se aleja del cero, como la base.
    assert cuantizar(Decimal("-12.345")) == Decimal("-12.35")
    # Y con la escala de los precios unitarios (cuatro decimales).
    assert cuantizar(Decimal("0.12345"), CUATRO_DECIMALES) == Decimal("0.1235")


def _quantize_sin_modo() -> list[str]:
    """`fichero:línea` de cada `quantize()` de `app/` que no fija el redondeo.

    Se recorre el árbol sintáctico y no el texto: hay llamadas partidas en dos
    líneas por el formateador y un `grep` no las ve enteras.
    """
    hallados: list[str] = []
    for fichero in sorted(RAIZ_APP.rglob("*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if (
                isinstance(nodo, ast.Call)
                and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "quantize"
                and not any(clave.arg == "rounding" for clave in nodo.keywords)
            ):
                hallados.append(f"{fichero.relative_to(RAIZ_APP.parent).as_posix()}:{nodo.lineno}")
    return hallados


#: Los `quantize()` que **no** son dinero y por eso siguen con el redondeo del
#: contexto: proporciones, porcentajes, puntuaciones z y cantidades. Cada uno se
#: revisó a mano; la lista es la documentación de esa revisión.
NO_SON_DINERO = {
    # Proporción de ahorro y porcentaje de consumo del presupuesto.
    "app/api/v1/alertas.py",
    # Porcentaje de variación de precio (`Variacion.porcentaje`).
    "app/api/v1/productos.py",
    # Umbrales de aviso del hogar: porcentajes y sigmas, no importes.
    "app/api/v1/ajustes.py",
    # Cantidad deducida de total/precio, en milésimas de unidad.
    "app/services/extraccion_pdf.py",
    # Proporciones de variación de precio e inflación personal.
    "app/services/precios.py",
    # Porcentaje de variación de una línea de factura.
    "app/api/v1/facturas.py",
    # Porcentajes de reparto, tasas de ahorro y puntuaciones z.
    "app/api/v1/informes.py",
}


def test_el_dinero_no_se_cuantiza_nunca_con_el_redondeo_del_contexto() -> None:
    """El arreglo tiene que ser estructural, no treinta arreglos sueltos.

    Antes de centralizar había ~30 `quantize()` de dinero sin `rounding=` en
    nueve ficheros. Esta prueba fija el resultado: los únicos `quantize()` que
    quedan sin modo están en los ficheros de `NO_SON_DINERO`, y ahí son
    porcentajes, proporciones o cantidades.
    """
    culpables = sorted({sitio.rsplit(":", 1)[0] for sitio in _quantize_sin_modo()} - NO_SON_DINERO)
    assert culpables == [], (
        "Estos ficheros cuantizan dinero con el redondeo bancario: usa "
        f"`formato.cuantizar()`. {culpables}"
    )


def test_el_precio_medio_de_un_producto_redondea_al_alza() -> None:
    """`AnalisisPrecio.precio_medio` es un precio, y el empate baja donde la base sube."""
    puntos = [
        precios.PuntoPrecio(fecha=date(2026, 1, 1), precio=Decimal("0.1234")),
        precios.PuntoPrecio(fecha=date(2026, 2, 1), precio=Decimal("0.1235")),
    ]
    analisis = precios.analizar_historial(puntos)
    assert analisis.precio_medio == Decimal("0.1235")


def test_el_total_de_la_cesta_redondea_al_alza() -> None:
    """Un litro y medio a 0,67 €/l son 1,01 €, no 1,00 €."""
    comparativa = precios.comparar_cesta(
        [
            precios.LineaCesta(
                producto_id="p1",
                nombre="Leche",
                cantidad=Decimal("1.5"),
                precios={"Súper": Decimal("0.67")},
            )
        ]
    )
    assert comparativa.totales["Súper"] == Decimal("1.01")


def test_el_ahorro_maximo_de_la_cesta_redondea_al_alza() -> None:
    """Los dos totales ya vienen cuantizados: el arreglo no puede descuadrarlos."""
    comparativa = precios.comparar_cesta(
        [
            precios.LineaCesta(
                producto_id="p1",
                nombre="Leche",
                cantidad=Decimal("1.5"),
                precios={"Súper": Decimal("0.67"), "Barato": Decimal("0.55")},
            )
        ]
    )
    assert comparativa.ahorro_maximo == Decimal("0.18")


async def test_el_coste_anual_de_una_suscripcion_no_sale_del_mensual_redondeado(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """Una suscripción semanal de 10,00 € cuesta 520,00 € al año, no 519,96 €.

    El coste anual se derivaba del mensual **ya redondeado** (43,33 × 12), así
    que el error crecía con el número de suscripciones.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)
    cuenta = Account(household_id=hogar, name="Nómina", type="checking", account_class="asset")
    sesion_bd.add(cuenta)
    await sesion_bd.flush()
    sesion_bd.add(
        RecurringRule(
            household_id=hogar,
            name="Fruta semanal",
            kind="expense",
            account_id=cuenta.id,
            expected_amount=Decimal("-10.00"),
            frequency="semanal",  # el vocabulario del motor, que es lo que guarda la columna
            starts_on=HOY,
            status="active",
            is_subscription=True,
        )
    )
    await sesion_bd.flush()

    async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
        respuesta = await propio.get(f"{PREFIJO}/reports/subscriptions")

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["rows"][0]["monthly_cost"] == "43.33"
    assert cuerpo["rows"][0]["annual_cost"] == "520.00"
    assert cuerpo["annual_total"] == "520.00"


# --------------------------------------------------------------------------- #
# 2. Confirmar una factura con todas las líneas excluidas
# --------------------------------------------------------------------------- #


async def _factura_sembrada(
    sesion: AsyncSession,
    hogar: uuid.UUID,
    *,
    total: str = "32.08",
    excluidas: bool = False,
    payee_id: uuid.UUID | None = None,
    lineas: int = 2,
) -> Invoice:
    """Una factura en revisión con sus líneas, sin pasar por el PDF."""
    factura = Invoice(
        household_id=hogar,
        payee_id=payee_id,
        issuer_name="Supermercados El Ahorro",
        issuer_tax_id=None,
        invoice_number=None,
        issued_on=HOY,
        total_amount=Decimal(total),
        status="pending_review",
        file_name="factura.pdf",
        storage_key=f"{uuid.uuid4()}.pdf",
        byte_size=1024,
        content_sha256=uuid.uuid4().hex * 2,
    )
    sesion.add(factura)
    await sesion.flush()
    for numero in range(1, lineas + 1):
        sesion.add(
            InvoiceLine(
                household_id=hogar,
                invoice_id=factura.id,
                line_number=numero,
                raw_description=f"Concepto {numero}",
                quantity=Decimal("1"),
                unit_price=Decimal("1.0000"),
                line_total=Decimal("1.00"),
                excluded=excluidas,
            )
        )
    await sesion.flush()
    return factura


def test_repartir_sin_ninguna_linea_incluida_no_revienta() -> None:
    """`defecto or repartos[0].category_id` con la lista vacía daba `IndexError`."""
    factura = Invoice(
        household_id=uuid.uuid4(),
        total_amount=Decimal("32.08"),
        file_name="f.pdf",
        storage_key="f.pdf",
        byte_size=1,
        content_sha256="0" * 64,
    )
    with pytest.raises(ReglaDeNegocio):
        _repartir(factura, [], None)


async def test_confirmar_una_factura_con_todas_las_lineas_excluidas_no_da_500(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """`_repartir` cogía `repartos[0]` de una lista vacía: `IndexError` → 500.

    Debe salir un 422 explicado y en español, que es lo que pide RN-02 para un
    error de negocio.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)
    cuenta = Account(household_id=hogar, name="Nómina", type="checking", account_class="asset")
    sesion_bd.add(cuenta)
    await sesion_bd.flush()
    factura = await _factura_sembrada(sesion_bd, hogar, excluidas=True)
    await sesion_bd.commit()

    async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
        respuesta = await propio.post(
            f"{PREFIJO}/invoices/{factura.id}/confirm",
            json={"account_id": str(cuenta.id), "allow_total_mismatch": True},
        )

    assert respuesta.status_code == 422, respuesta.text
    error = respuesta.json()["error"]
    assert error["codigo"] == "datos_invalidos"
    assert "temática" in error["mensaje"]


# --------------------------------------------------------------------------- #
# 3. La huella de duplicados
# --------------------------------------------------------------------------- #


def test_la_huella_no_cambia_con_los_decimales_del_importe() -> None:
    """`-42,3` y `-42,30` son el mismo apunte y tienen que dar la misma huella.

    La huella interpola el `Decimal` como texto, así que el número de decimales
    la cambiaba: corregir una fila mandando `"12.3"` en vez de `"12.30"` hacía
    que el duplicado dejara de detectarse al reimportar el extracto.
    """
    corta = calcular_huella(date(2026, 8, 1), Decimal("-42.3"), "Compra en el súper")
    larga = calcular_huella(date(2026, 8, 1), Decimal("-42.30"), "Compra en el súper")
    assert corta == larga
    # Y el redondeo es el del dinero, no el bancario.
    assert calcular_huella(date(2026, 8, 1), Decimal("-42.345"), "x") == calcular_huella(
        date(2026, 8, 1), Decimal("-42.35"), "x"
    )


# --------------------------------------------------------------------------- #
# 4. N+1 en el listado de facturas
# --------------------------------------------------------------------------- #


@pytest.fixture
def contador_de_consultas() -> Iterator[list[str]]:
    """Cada sentencia que sale hacia PostgreSQL, en orden.

    El enganche va sobre la clase `Engine` y no sobre una instancia: la sesión de
    la prueba está atada a una conexión, no a un motor accesible desde aquí.
    """
    ejecutadas: list[str] = []

    def anotar(_conexion, _cursor, sentencia, _parametros, _contexto, _muchas) -> None:  # noqa: ANN001
        ejecutadas.append(sentencia)

    event.listen(Engine, "before_cursor_execute", anotar)
    try:
        yield ejecutadas
    finally:
        event.remove(Engine, "before_cursor_execute", anotar)


async def test_el_listado_de_facturas_no_hace_una_consulta_por_fila(
    cliente: AsyncClient, sesion_bd: AsyncSession, contador_de_consultas: list[str]
) -> None:
    """`respuesta_factura()` por factura hacía `_lineas_de` + `get(Payee)`.

    Con veinte facturas eran ~60 consultas por página (~150 con `size=50`), y con
    `include=lines` dos más por factura. El tope de la prueba es holgado a
    propósito: lo que fija es que el número **no crece con las filas**.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)
    tematica = await tematica_directa(sesion_bd, hogar, "Alimentación")
    comercios = []
    for numero in range(4):
        comercio = Payee(
            household_id=hogar, name=f"Súper {numero}", normalized_name=f"super {numero}"
        )
        sesion_bd.add(comercio)
        comercios.append(comercio)
    await sesion_bd.flush()
    for numero in range(20):
        factura = await _factura_sembrada(
            sesion_bd, hogar, payee_id=comercios[numero % 4].id, lineas=3
        )
        await sesion_bd.execute(
            text("UPDATE invoice_lines SET category_id = :cat WHERE invoice_id = :fac"),
            {"cat": tematica.id, "fac": factura.id},
        )
    await sesion_bd.commit()

    async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
        contador_de_consultas.clear()
        respuesta = await propio.get(f"{PREFIJO}/invoices?size=20")
        sin_lineas = len(contador_de_consultas)
        assert respuesta.status_code == 200, respuesta.text
        assert len(respuesta.json()["items"]) == 20

        contador_de_consultas.clear()
        con_lineas = await propio.get(f"{PREFIJO}/invoices?size=20&include=lines")
        cuantas_con_lineas = len(contador_de_consultas)
        assert con_lineas.status_code == 200, con_lineas.text

    # Usuario, pertenencia, `set_config`, recuento, página, líneas y comercios: el
    # tope de doce deja sitio de sobra para el andamio y ninguno para un N+1. Antes
    # del arreglo eran 46 con veinte facturas de tres líneas.
    assert sin_lineas <= 12, f"{sin_lineas} consultas para veinte facturas"
    assert cuantas_con_lineas <= 12, f"{cuantas_con_lineas} consultas con las líneas"
    # Y las líneas y el comercio siguen saliendo en la respuesta.
    primera_fila = con_lineas.json()["items"][0]
    assert primera_fila["payee"] is not None
    assert len(primera_fila["lines"]) == 3
    assert primera_fila["lines_count"] == 3


# --------------------------------------------------------------------------- #
# 5. El deshacer de una fusión: 409, no 500
# --------------------------------------------------------------------------- #


async def test_deshacer_una_fusion_con_el_nombre_ya_ocupado_responde_409(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """El índice único excluye las lápidas, así que el nombre queda libre.

    Fusionar «Compra semanal», crear otra temática con ese nombre y deshacer
    reventaba el índice: 500 `error_interno` y la fusión ya no se podía deshacer.
    `desarchivar` sí comprueba el árbol antes de resucitar (`categorias.py:869`).
    """
    await registrar(cliente)
    destino = await _tematica_api(cliente, "Supermercado")
    origen = await _tematica_api(cliente, "Compra semanal")

    fusion = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [origen["id"]], "target_id": destino["id"]},
    )
    assert fusion.status_code == 200, fusion.text

    # El nombre ha quedado libre porque el índice único no ve las lápidas.
    repetida = await _tematica_api(cliente, "Compra semanal")
    assert repetida["id"] != origen["id"]

    deshacer = await cliente.post(
        f"{PREFIJO}/categories/merges/{fusion.json()['merge_id']}/undo",
        headers=cabeceras(cliente),
    )
    assert deshacer.status_code == 409, deshacer.text
    mensaje = deshacer.json()["error"]["mensaje"]
    assert "Compra semanal" in mensaje


async def test_deshacer_una_fusion_cuyo_movimiento_se_borro_responde_409(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """El deshacer pisaba sin condición lo que el usuario cambió después.

    Si el movimiento cuyo reparto colapsó la fusión ya no existe, el diario
    intenta reinsertar el reparto borrado y la clave ajena tumba la sentencia:
    500 `error_interno` en lugar de un conflicto explicado.
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
    origen = await _tematica_api(cliente, "Compra semanal")

    movimiento = Transaction(
        household_id=hogar,
        account_id=uuid.UUID(cuenta["id"]),
        kind="expense",
        booked_on=HOY,
        amount=Decimal("-100.00"),
        category_id=uuid.UUID(destino["id"]),
        description="Compra grande",
    )
    sesion_bd.add(movimiento)
    await sesion_bd.flush()
    for numero, (tematica, importe) in enumerate(
        ((destino, "-40.00"), (origen, "-60.00")), start=1
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
    movimiento_id = movimiento.id
    await sesion_bd.commit()

    fusion = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [origen["id"]], "target_id": destino["id"]},
    )
    assert fusion.status_code == 200, fusion.text

    # El usuario borra el movimiento después de fusionar: el reparto que la
    # fusión colapsó ya no se puede resucitar.
    await sesion_bd.execute(
        text("DELETE FROM transactions WHERE id = :movimiento"), {"movimiento": movimiento_id}
    )
    await sesion_bd.commit()

    deshacer = await cliente.post(
        f"{PREFIJO}/categories/merges/{fusion.json()['merge_id']}/undo",
        headers=cabeceras(cliente),
    )
    assert deshacer.status_code == 409, deshacer.text
    assert deshacer.json()["error"]["codigo"] == "conflicto"


# --------------------------------------------------------------------------- #
# 6. Pendientes de gravedad media
# --------------------------------------------------------------------------- #


async def test_el_prorrateo_del_presupuesto_restante_cuadra_al_centimo(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """100,00 € entre tres cuentas repartía 99,99 €: faltaba imputar el resto.

    Es el único prorrateo del proyecto que no cuadraba; `_repartir()` de las
    facturas y `reparto_sugerido()` sí lo hacen.
    """
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)
    for nombre in ("Nómina", "Ahorro", "Gastos"):
        sesion_bd.add(
            Account(household_id=hogar, name=nombre, type="checking", account_class="asset")
        )
    tematica = await tematica_directa(sesion_bd, hogar, "Alimentación")
    periodo = BudgetPeriod(household_id=hogar, period_start=date(HOY.year, HOY.month, 1))
    sesion_bd.add(periodo)
    await sesion_bd.flush()
    sesion_bd.add(
        BudgetAllocation(
            household_id=hogar,
            budget_period_id=periodo.id,
            category_id=tematica.id,
            allocated_amount=Decimal("100.00"),
        )
    )
    await sesion_bd.flush()

    async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
        respuesta = await propio.get(f"{PREFIJO}/reports/projected-balance")

    assert respuesta.status_code == 200, respuesta.text
    filas = respuesta.json()["rows"]
    assert len(filas) == 3
    repartido = sum(Decimal(fila["remaining_budget"]) for fila in filas)
    assert repartido == Decimal("100.00"), [fila["remaining_budget"] for fila in filas]


async def test_lo_que_hace_falta_aportar_a_un_objetivo_se_redondea_hacia_arriba(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """100,00 € en tres meses son 33,34 €/mes, no 33,33 €.

    Aportando 33,33 € tres veces se ingresan 99,99 € y el objetivo no se alcanza,
    pero `is_on_track` decía que sí. Un «cuánto necesito aportar» se redondea
    hacia arriba (`ROUND_CEILING`), no al más cercano.
    """
    correo = await registrar(cliente)
    usuario_id = await utillaje.usuario_de(sesion_bd, correo)

    async with cliente_de_usuario(sesion_bd, usuario_id) as propio:
        # Tres meses justos: el primero de dentro de tres meses.
        objetivo = date(HOY.year + (HOY.month + 3 > 12), (HOY.month + 3 - 1) % 12 + 1, 1)
        alta = await propio.post(
            f"{PREFIJO}/goals",
            json={
                "name": "Portátil nuevo",
                "target_amount": "100.00",
                "target_date": objetivo.isoformat(),
            },
        )
        assert alta.status_code == 201, alta.text
        detalle = await propio.get(f"{PREFIJO}/goals/{alta.json()['id']}")

    assert detalle.status_code == 200, detalle.text
    necesario = Decimal(detalle.json()["required_monthly"])
    meses = detalle.json()["months_left"]
    assert meses == 3, detalle.text
    assert necesario * meses >= Decimal("100.00"), (necesario, meses)


def test_la_cabecera_de_csp_esta_en_la_respuesta() -> None:
    """§8.2 pide `object-src 'none'` y `frame-ancestors 'none'`.

    **Esta prueba ya pasaba**: el informe apuntaba a `main.py:66-79` y la política
    completa está en `main.py:72-83`, aplicada por el middleware de `:96`. Se deja
    como guardia de que no desaparezca y la fila del informe se corrige.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as prueba:
        respuesta = prueba.get("/health")
    politica = respuesta.headers.get("content-security-policy", "")
    assert "default-src 'self'" in politica
    assert "object-src 'none'" in politica
    assert "frame-ancestors 'none'" in politica
