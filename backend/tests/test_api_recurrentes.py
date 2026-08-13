"""Pruebas de la API de recurrentes y suscripciones.

Las fechas no se calculan aquí ni en el router: las decide
`app/services/recurrencia.py`, así que estas pruebas comprueban sobre todo que la
traducción entre las columnas del esquema y el motor no pierde nada —incluido el
día 31 en febrero (RN-37)— y que una ocurrencia se materializa una sola vez
(RN-36).

El montaje se importa de `test_api_transacciones.py`.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerta import Alert
from app.models.cuenta import Account
from tests.test_api_transacciones import (  # noqa: F401 - fixtures compartidas
    HOY,
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

#: Año siguiente al actual: deja las pruebas de calendario fuera del mes en curso.
ANYO = HOY.year + 1


async def crear_recurrente(cliente: AsyncClient, entorno: Entorno, **extra: Any) -> dict[str, Any]:
    cuerpo = {
        "name": extra.pop("name", f"Netflix {uuid.uuid4().hex[:6]}"),
        "account_id": str(entorno.corriente.id),
        "category_id": str(entorno.ocio.id),
        "amount": extra.pop("amount", "12.99"),
        "frequency": extra.pop("frequency", "monthly"),
        "starts_on": extra.pop("starts_on", HOY.replace(day=1).isoformat()),
        **extra,
    }
    respuesta = await cliente.post(f"{RUTA}/recurring", json=cuerpo)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# --------------------------------------------------------------------------- #
# Altas y bajas
# --------------------------------------------------------------------------- #


async def test_un_recurrente_mensual_calcula_su_proxima_fecha(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await crear_recurrente(
        cliente, entorno, name="Alquiler", amount="750.00", day_of_month=1
    )
    assert datos["frequency"] == "monthly"
    assert datos["day_of_month"] == 1
    assert datos["is_active"] is True
    # La primera ocurrencia es la propia fecha de inicio, aunque ya haya pasado: es
    # lo que hace que un recurrente dado de alta a mitad de mes aparezca como
    # vencido en lugar de saltarse la primera cuota.
    assert datos["next_occurrence_on"] == HOY.replace(day=1).isoformat()
    # El texto de la regla lo compone el propio servicio.
    assert datos["rule_text"] == "cada mes, el día 1"
    assert datos["annual_cost"] == "9000.00"


async def test_el_nombre_de_un_recurrente_no_se_repite(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await crear_recurrente(cliente, entorno, name="Seguro del coche")
    respuesta = await cliente.post(
        f"{RUTA}/recurring",
        json={
            "name": "seguro del coche",
            "account_id": str(entorno.corriente.id),
            "amount": "300.00",
            "frequency": "semiannual",
            "starts_on": HOY.isoformat(),
        },
    )
    assert respuesta.status_code == 409
    assert codigo_de(respuesta) == "nombre_duplicado"


async def test_rn37_el_dia_31_cae_en_el_ultimo_dia_de_febrero(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """Nunca se salta el mes: el 31 de febrero es el 28 o el 29."""
    enero = date(ANYO, 1, 31)
    datos = await crear_recurrente(
        cliente,
        entorno,
        name="Cuota del día 31",
        day_of_month=31,
        starts_on=enero.isoformat(),
    )
    assert datos["next_occurrence_on"] == enero.isoformat()

    saltada = await cliente.post(
        f"{RUTA}/recurring/{datos['id']}/skip", json={"occurrence_date": enero.isoformat()}
    )
    assert saltada.status_code == 200, saltada.text
    ultimo_de_febrero = date(ANYO, 2, calendar.monthrange(ANYO, 2)[1])
    assert saltada.json()["next_occurrence_on"] == ultimo_de_febrero.isoformat()


async def test_el_ultimo_dia_del_mes_sobrevive_a_la_ida_y_vuelta(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """`day_of_month = -1` se guarda como política de mes, no como día 31."""
    datos = await crear_recurrente(
        cliente, entorno, name="Nómina", frequency="monthly", day_of_month=-1
    )
    assert datos["day_of_month"] == -1
    detalle = (await cliente.get(f"{RUTA}/recurring/{datos['id']}")).json()
    assert detalle["day_of_month"] == -1
    proxima = date.fromisoformat(detalle["next_occurrence_on"])
    assert proxima.day == calendar.monthrange(proxima.year, proxima.month)[1]


async def test_una_frecuencia_de_cada_n_dias_conserva_el_intervalo(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await crear_recurrente(
        cliente,
        entorno,
        name="Fruta semanal",
        frequency="every_n_days",
        interval=10,
        starts_on=HOY.isoformat(),
    )
    assert datos["frequency"] == "every_n_days"
    assert datos["interval"] == 10
    assert date.fromisoformat(datos["next_occurrence_on"]) == HOY

    # Al saltar la primera, la siguiente cae diez días después: el intervalo se ha
    # guardado como tal y no como una frecuencia diaria cualquiera.
    saltada = await cliente.post(
        f"{RUTA}/recurring/{datos['id']}/skip", json={"occurrence_date": HOY.isoformat()}
    )
    assert saltada.status_code == 200, saltada.text
    assert date.fromisoformat(saltada.json()["next_occurrence_on"]) == HOY + timedelta(days=10)


async def test_pausar_y_reanudar(cliente: AsyncClient, entorno: Entorno) -> None:
    datos = await crear_recurrente(cliente, entorno, name="Gimnasio")
    pausado = (await cliente.post(f"{RUTA}/recurring/{datos['id']}/pause")).json()
    assert pausado["is_paused"] is True
    assert pausado["is_active"] is False
    assert pausado["next_occurrence_on"] is None

    reanudado = (await cliente.post(f"{RUTA}/recurring/{datos['id']}/resume")).json()
    assert reanudado["is_active"] is True
    assert reanudado["next_occurrence_on"] is not None


async def test_los_filtros_del_listado(cliente: AsyncClient, entorno: Entorno) -> None:
    await crear_recurrente(cliente, entorno, name="Netflix", is_subscription=True)
    await crear_recurrente(cliente, entorno, name="Alquiler", is_subscription=False)

    todos = (await cliente.get(f"{RUTA}/recurring")).json()
    assert todos["total"] == 2

    suscripciones = (
        await cliente.get(f"{RUTA}/recurring", params={"is_subscription": "true"})
    ).json()
    assert suscripciones["total"] == 1
    assert suscripciones["items"][0]["name"] == "Netflix"

    buscados = (await cliente.get(f"{RUTA}/recurring", params={"q": "alqui"})).json()
    assert buscados["total"] == 1


async def test_borrar_la_plantilla_conserva_las_transacciones(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    """RN-38: lo ya generado queda como movimiento normal."""
    datos = await crear_recurrente(cliente, entorno, name="Luz")
    publicada = await cliente.post(
        f"{RUTA}/recurring/{datos['id']}/post", json={"occurrence_date": HOY.isoformat()}
    )
    assert publicada.status_code == 201, publicada.text

    assert (await cliente.delete(f"{RUTA}/recurring/{datos['id']}")).status_code == 204
    movimiento = await cliente.get(f"{RUTA}/transactions/{publicada.json()['id']}")
    assert movimiento.status_code == 200
    assert movimiento.json()["recurring_id"] is None


# --------------------------------------------------------------------------- #
# Próximas ocurrencias y materialización
# --------------------------------------------------------------------------- #


async def test_las_proximas_ocurrencias_caben_en_la_ventana(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await crear_recurrente(
        cliente,
        entorno,
        name="Café semanal",
        frequency="weekly",
        starts_on=(HOY - timedelta(days=1)).isoformat(),
    )
    respuesta = await cliente.get(f"{RUTA}/recurring/upcoming", params={"days": 20})
    assert respuesta.status_code == 200, respuesta.text
    vencimientos = respuesta.json()
    # Empezó ayer, así que en veinte días caben tres semanas: +6, +13 y +20.
    assert [item["days_until"] for item in vencimientos] == [6, 13, 20]
    assert all(
        date.fromisoformat(item["due_on"]) <= HOY + timedelta(days=20) for item in vencimientos
    )
    assert vencimientos[0]["expected_amount"] == "12.99"


async def test_rn36_una_ocurrencia_se_materializa_una_sola_vez(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await crear_recurrente(cliente, entorno, name="Netflix")
    primera = await cliente.post(
        f"{RUTA}/recurring/{datos['id']}/post",
        json={"occurrence_date": HOY.isoformat(), "amount": "13.99"},
    )
    assert primera.status_code == 201, primera.text
    movimiento = primera.json()
    assert movimiento["amount"] == "13.99"
    assert movimiento["signed_amount"] == "-13.99"
    assert movimiento["recurring_id"] == datos["id"]
    assert movimiento["source"] == "recurring"

    segunda = await cliente.post(
        f"{RUTA}/recurring/{datos['id']}/post", json={"occurrence_date": HOY.isoformat()}
    )
    assert segunda.status_code == 409
    # Sigue habiendo un solo movimiento.
    assert (await cliente.get(f"{RUTA}/transactions")).json()["total"] == 1


async def test_una_ocurrencia_materializada_no_se_salta(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await crear_recurrente(cliente, entorno, name="Internet")
    await cliente.post(
        f"{RUTA}/recurring/{datos['id']}/post", json={"occurrence_date": HOY.isoformat()}
    )
    respuesta = await cliente.post(
        f"{RUTA}/recurring/{datos['id']}/skip", json={"occurrence_date": HOY.isoformat()}
    )
    assert respuesta.status_code == 409


async def test_publicar_deja_el_historico_de_precio(cliente: AsyncClient, entorno: Entorno) -> None:
    datos = await crear_recurrente(cliente, entorno, name="Móvil", amount="10.00")
    for dia, importe in ((1, "10.00"), (2, "12.00"), (3, "12.00")):
        respuesta = await cliente.post(
            f"{RUTA}/recurring/{datos['id']}/post",
            json={
                "occurrence_date": (HOY - timedelta(days=30 * (4 - dia))).isoformat(),
                "amount": importe,
            },
        )
        assert respuesta.status_code == 201, respuesta.text

    historial = (await cliente.get(f"{RUTA}/recurring/{datos['id']}/price-history")).json()
    assert historial["first_amount"] == "10.00"
    assert historial["last_amount"] == "12.00"
    assert historial["increases"] == 1
    assert historial["points"][1]["is_increase"] is True
    assert historial["points"][1]["change_pct"] == 20.0

    detalle = (await cliente.get(f"{RUTA}/recurring/{datos['id']}")).json()
    assert detalle["occurrences_count"] == 3
    assert detalle["last_amount"] == "12.00"
    assert detalle["price_change_pct"] == 0.0


async def test_rn40_una_subida_de_importe_genera_aviso(
    cliente: AsyncClient, entorno: Entorno, sesion: AsyncSession
) -> None:
    """La subida se mide contra el último cargo, no contra la media."""
    datos = await crear_recurrente(cliente, entorno, name="Seguro", amount="20.00")
    await cliente.post(
        f"{RUTA}/recurring/{datos['id']}/post",
        json={"occurrence_date": (HOY - timedelta(days=60)).isoformat(), "amount": "20.00"},
    )
    await cliente.post(
        f"{RUTA}/recurring/{datos['id']}/post",
        json={"occurrence_date": (HOY - timedelta(days=30)).isoformat(), "amount": "26.00"},
    )

    avisos = list(
        await sesion.scalars(
            select(Alert).where(
                Alert.household_id == entorno.hogar.id,
                Alert.type == "recurring_price_increase",
            )
        )
    )
    assert len(avisos) == 1
    assert avisos[0].payload["change_pct"] == "30.00"
    assert "Seguro" in avisos[0].title

    detalle = (await cliente.get(f"{RUTA}/recurring/{datos['id']}")).json()
    assert detalle["price_change_pct"] == 30.0


async def test_un_recurrente_sin_tematica_no_se_puede_materializar(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    respuesta = await cliente.post(
        f"{RUTA}/recurring",
        json={
            "name": "Sin temática",
            "account_id": str(entorno.corriente.id),
            "amount": "5.00",
            "frequency": "monthly",
            "starts_on": HOY.isoformat(),
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    fallo = await cliente.post(
        f"{RUTA}/recurring/{respuesta.json()['id']}/post",
        json={"occurrence_date": HOY.isoformat()},
    )
    assert fallo.status_code == 422


# --------------------------------------------------------------------------- #
# Detección de suscripciones (F-29, RN-39)
# --------------------------------------------------------------------------- #


async def sembrar_cargos(
    cliente: AsyncClient,
    entorno: Entorno,
    comercio: str,
    importes: tuple[str, ...] = ("12.99", "12.99", "12.99"),
) -> None:
    """Tres cargos mensuales del mismo comercio: el patrón que RN-39 exige."""
    for indice, importe in enumerate(reversed(importes)):
        respuesta = await cliente.post(
            f"{RUTA}/transactions",
            json={
                "account_id": str(entorno.corriente.id),
                "date": (HOY - timedelta(days=30 * indice)).isoformat(),
                "amount": importe,
                "category_id": str(entorno.ocio.id),
                "payee_name": comercio,
                "description": comercio,
            },
        )
        assert respuesta.status_code == 201, respuesta.text


async def test_rn39_se_detecta_una_suscripcion_en_el_historico(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await sembrar_cargos(cliente, entorno, "Netflix")
    respuesta = await cliente.get(f"{RUTA}/recurring/detected")
    assert respuesta.status_code == 200, respuesta.text
    detectadas = respuesta.json()["items"]
    assert len(detectadas) == 1
    grupo = detectadas[0]
    assert grupo["payee_name"] == "Netflix"
    assert grupo["occurrences"] == 3
    assert grupo["estimated_frequency"] == "monthly"
    assert grupo["amount_stability"] >= 0.8
    assert grupo["average_amount"] == "12.99"
    assert len(grupo["transaction_ids"]) == 3


async def test_rn39_dos_cargos_no_son_una_suscripcion(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await sembrar_cargos(cliente, entorno, "Solo dos", importes=("9.99", "9.99"))
    detectadas = (await cliente.get(f"{RUTA}/recurring/detected")).json()
    assert detectadas["total"] == 0


async def test_rn39_un_importe_inestable_no_es_una_suscripcion(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await sembrar_cargos(cliente, entorno, "Bar de la esquina", importes=("4.00", "40.00", "9.00"))
    detectadas = (await cliente.get(f"{RUTA}/recurring/detected")).json()
    assert detectadas["total"] == 0


async def test_confirmar_una_deteccion_crea_el_recurrente_y_vincula_el_historico(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    await sembrar_cargos(cliente, entorno, "Spotify")
    grupo = (await cliente.get(f"{RUTA}/recurring/detected")).json()["items"][0]

    respuesta = await cliente.post(
        f"{RUTA}/recurring/detected/{grupo['group_id']}/confirm",
        json={"name": "Spotify Premium", "is_subscription": True},
    )
    assert respuesta.status_code == 201, respuesta.text
    creado = respuesta.json()
    assert creado["name"] == "Spotify Premium"
    assert creado["is_subscription"] is True
    assert creado["payee"]["name"] == "Spotify"

    vinculadas = (
        await cliente.get(f"{RUTA}/transactions", params={"only_recurring": "true"})
    ).json()
    assert vinculadas["total"] == 3
    # Ya no se propone: tiene recurrente propio.
    assert (await cliente.get(f"{RUTA}/recurring/detected")).json()["total"] == 0


async def test_descartar_una_deteccion_la_silencia(cliente: AsyncClient, entorno: Entorno) -> None:
    """RN-39: un grupo descartado no vuelve a proponerse."""
    await sembrar_cargos(cliente, entorno, "Prensa digital")
    grupo = (await cliente.get(f"{RUTA}/recurring/detected")).json()["items"][0]

    respuesta = await cliente.post(f"{RUTA}/recurring/detected/{grupo['group_id']}/dismiss")
    assert respuesta.status_code == 204
    assert (await cliente.get(f"{RUTA}/recurring/detected")).json()["total"] == 0
    # Y la lápida no aparece como recurrente del hogar.
    assert (await cliente.get(f"{RUTA}/recurring")).json()["total"] == 0


async def test_un_grupo_inexistente_da_404(cliente: AsyncClient) -> None:
    respuesta = await cliente.post(f"{RUTA}/recurring/detected/{uuid.uuid4()}/dismiss")
    assert respuesta.status_code == 404


# --------------------------------------------------------------------------- #
# Edición y aislamiento
# --------------------------------------------------------------------------- #


async def test_editar_cambia_la_regla_y_recalcula_la_proxima_fecha(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    datos = await crear_recurrente(cliente, entorno, name="Revista", frequency="monthly")
    respuesta = await cliente.patch(
        f"{RUTA}/recurring/{datos['id']}",
        json={"frequency": "yearly", "amount": "99.00", "day_of_month": 15},
    )
    assert respuesta.status_code == 200, respuesta.text
    editado = respuesta.json()
    assert editado["frequency"] == "yearly"
    assert editado["amount"] == "99.00"
    assert editado["day_of_month"] == 15
    assert editado["annual_cost"] == "99.00"
    assert date.fromisoformat(editado["next_occurrence_on"]).day == 15


async def test_un_recurrente_de_otro_hogar_da_404(sesion: AsyncSession, entorno: Entorno) -> None:
    otro_hogar, otro_usuario = await crear_hogar(sesion, f"{uuid.uuid4().hex[:10]}@vecina.es")
    otra_cuenta = Account(
        household_id=otro_hogar.id, name="Vecina", type="checking", account_class="asset"
    )
    sesion.add(otra_cuenta)
    await sesion.commit()
    otra_tematica = await crear_tematica(sesion, otro_hogar, "Ocio")

    async with cliente_de(sesion, otro_usuario) as vecina:
        suyo = await vecina.post(
            f"{RUTA}/recurring",
            json={
                "name": "Netflix de la vecina",
                "account_id": str(otra_cuenta.id),
                "category_id": str(otra_tematica.id),
                "amount": "12.99",
                "frequency": "monthly",
                "starts_on": HOY.isoformat(),
            },
        )
        assert suyo.status_code == 201, suyo.text

    async with cliente_de(sesion, entorno.usuario) as propio:
        assert (await propio.get(f"{RUTA}/recurring")).json()["total"] == 0
        assert (await propio.get(f"{RUTA}/recurring/{suyo.json()['id']}")).status_code == 404
        publicado = await propio.post(
            f"{RUTA}/recurring/{suyo.json()['id']}/post",
            json={"occurrence_date": HOY.isoformat()},
        )
        assert publicado.status_code == 404


async def test_el_coste_anual_depende_de_la_frecuencia(
    cliente: AsyncClient, entorno: Entorno
) -> None:
    mensual = await crear_recurrente(cliente, entorno, name="Mensual", amount="10.00")
    trimestral = await crear_recurrente(
        cliente, entorno, name="Trimestral", amount="10.00", frequency="quarterly"
    )
    assert Decimal(mensual["annual_cost"]) == Decimal("120.00")
    assert Decimal(trimestral["annual_cost"]) == Decimal("40.00")
