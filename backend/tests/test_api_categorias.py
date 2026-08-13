"""Pruebas del árbol de temáticas: alta, jerarquía, archivado, movimiento y uso.

La fusión tiene su propio módulo (`test_fusion.py`); aquí solo se comprueba que los
tres endpoints existen y validan lo que les toca.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal

import test_api_auth as utillaje
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from test_api_auth import PREFIJO, cabeceras, hogar_de, registrar

from app.models.transaccion import Transaction

# Las fixtures del módulo base se reexportan por asignación y no por `import`:
# pytest las descubre igual, y así el analizador no confunde el nombre importado
# con el parámetro homónimo de cada prueba.
cliente = utillaje.cliente
navegadores = utillaje.navegadores
sesion_bd = utillaje.sesion_bd
limitador_limpio = utillaje.limitador_limpio


async def crear(
    cliente_http: AsyncClient, nombre: str, madre: str | None = None, **extra: object
) -> dict:
    cuerpo: dict = {"name": nombre, **extra}
    if madre is not None:
        cuerpo["parent_id"] = madre
    respuesta = await cliente_http.post(
        f"{PREFIJO}/categories", headers=cabeceras(cliente_http), json=cuerpo
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# --------------------------------------------------------------------------- #
# Alta y jerarquía
# --------------------------------------------------------------------------- #


async def test_alta_con_ruta_profundidad_y_miga_de_pan(cliente: AsyncClient) -> None:
    await registrar(cliente)
    vivienda = await crear(cliente, "Vivienda", color="#1E88E5", icon="house")
    suministros = await crear(cliente, "Suministros", vivienda["id"])
    luz = await crear(cliente, "Luz", suministros["id"])

    assert vivienda["depth"] == 0
    assert vivienda["parent_id"] is None
    assert vivienda["color"] == "#1e88e5"

    # Los contadores se releen: al crear la madre todavía no tenía descendencia.
    madre = (await cliente.get(f"{PREFIJO}/categories/{vivienda['id']}")).json()
    assert madre["children_count"] == 1
    assert madre["descendants_count"] == 2

    assert luz["depth"] == 2
    assert luz["path"] == f"{vivienda['id']}/{suministros['id']}/{luz['id']}"
    assert [a["name"] for a in luz["ancestors"]] == ["Vivienda", "Suministros"]
    # RN-13: el tipo se hereda de la madre.
    assert luz["kind"] == "expense"


async def test_el_tipo_se_hereda_y_no_se_mezcla(cliente: AsyncClient) -> None:
    await registrar(cliente)
    nomina = await crear(cliente, "Nómina", kind="income")
    hija = await crear(cliente, "Paga extra", nomina["id"], kind="expense")
    assert nomina["kind"] == "income"
    assert hija["kind"] == "income"


async def test_nombre_unico_entre_hermanas_pero_no_entre_ramas(cliente: AsyncClient) -> None:
    """RN-12: sin acentos y sin distinguir mayúsculas, solo entre hermanas."""
    await registrar(cliente)
    casa = await crear(cliente, "Casa")
    coche = await crear(cliente, "Coche")
    await crear(cliente, "Seguro", casa["id"])
    # «Seguro» bajo otra madre es legítimo.
    await crear(cliente, "Seguro", coche["id"])

    repetida = await cliente.post(
        f"{PREFIJO}/categories",
        headers=cabeceras(cliente),
        json={"name": "seguró", "parent_id": casa["id"]},
    )
    assert repetida.status_code == 409
    assert repetida.json()["error"]["codigo"] == "nombre_duplicado"


async def test_profundidad_maxima_seis_niveles(cliente: AsyncClient) -> None:
    await registrar(cliente)
    madre: str | None = None
    for nivel in range(6):
        madre = (await crear(cliente, f"Nivel {nivel}", madre))["id"]

    respuesta = await cliente.post(
        f"{PREFIJO}/categories",
        headers=cabeceras(cliente),
        json={"name": "Nivel 6", "parent_id": madre},
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["codigo"] == "profundidad_maxima"


async def test_arbol_anidado_y_ordenado(cliente: AsyncClient) -> None:
    await registrar(cliente)
    ocio = await crear(cliente, "Ocio", position=1)
    await crear(cliente, "Cine", ocio["id"], position=1)
    await crear(cliente, "Bares", ocio["id"], position=0)
    await crear(cliente, "Vivienda", position=0)

    arbol = (await cliente.get(f"{PREFIJO}/categories/tree")).json()
    assert [n["name"] for n in arbol] == ["Vivienda", "Ocio"]
    assert [n["name"] for n in arbol[1]["children"]] == ["Bares", "Cine"]


# --------------------------------------------------------------------------- #
# Renombrar, mover y reordenar
# --------------------------------------------------------------------------- #


async def test_renombrar_no_rompe_el_historico(
    cliente: AsyncClient, sesion_bd: AsyncSession
) -> None:
    """F-05: el identificador no cambia, así que el movimiento sigue apuntándole."""
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    tematica = await crear(cliente, "Compra semanal")

    cuenta = await cliente.post(
        f"{PREFIJO}/accounts",
        headers=cabeceras(cliente),
        json={"name": "Nómina", "type": "checking"},
    )
    sesion_bd.add(
        Transaction(
            household_id=hogar,
            account_id=uuid.UUID(cuenta.json()["id"]),
            kind="expense",
            booked_on=date.today(),
            amount=Decimal("-30.00"),
            category_id=uuid.UUID(tematica["id"]),
            description="Súper",
        )
    )
    await sesion_bd.commit()

    renombrada = await cliente.patch(
        f"{PREFIJO}/categories/{tematica['id']}",
        headers=cabeceras(cliente),
        json={"name": "Supermercado", "monthly_target": "300.00", "rollover_enabled": True},
    )
    assert renombrada.status_code == 200, renombrada.text
    assert renombrada.json()["name"] == "Supermercado"
    assert renombrada.json()["monthly_target"] == "300.00"
    assert renombrada.json()["rollover_enabled"] is True
    assert renombrada.json()["id"] == tematica["id"]

    uso = (await cliente.get(f"{PREFIJO}/categories/{tematica['id']}/usage")).json()
    assert uso["transactions"] == 1


async def test_if_match_obsoleto_da_412(cliente: AsyncClient) -> None:
    await registrar(cliente)
    tematica = await crear(cliente, "Ocio")
    respuesta = await cliente.patch(
        f"{PREFIJO}/categories/{tematica['id']}",
        headers={**cabeceras(cliente), "If-Match": 'W/"caducado"'},
        json={"name": "Ocio y cultura"},
    )
    assert respuesta.status_code == 412
    assert respuesta.json()["error"]["codigo"] == "precondicion_fallida"

    detalle = await cliente.get(f"{PREFIJO}/categories/{tematica['id']}")
    etiqueta = detalle.headers["ETag"]
    buena = await cliente.patch(
        f"{PREFIJO}/categories/{tematica['id']}",
        headers={**cabeceras(cliente), "If-Match": etiqueta},
        json={"name": "Ocio y cultura"},
    )
    assert buena.status_code == 200


async def test_mover_dentro_del_propio_subarbol_es_un_ciclo(cliente: AsyncClient) -> None:
    """RN-11: se comprueba con `path_ids`, no recorriendo madres una a una."""
    await registrar(cliente)
    abuela = await crear(cliente, "Abuela")
    madre = await crear(cliente, "Madre", abuela["id"])
    nieta = await crear(cliente, "Nieta", madre["id"])

    respuesta = await cliente.post(
        f"{PREFIJO}/categories/{abuela['id']}/move",
        headers=cabeceras(cliente),
        json={"parent_id": nieta["id"], "position": 0},
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["error"]["codigo"] == "ciclo_en_arbol"


async def test_mover_recalcula_la_ruta_de_todo_el_subarbol(cliente: AsyncClient) -> None:
    await registrar(cliente)
    origen = await crear(cliente, "Origen")
    destino = await crear(cliente, "Destino")
    hija = await crear(cliente, "Hija", origen["id"])
    nieta = await crear(cliente, "Nieta", hija["id"])

    movida = await cliente.post(
        f"{PREFIJO}/categories/{hija['id']}/move",
        headers=cabeceras(cliente),
        json={"parent_id": destino["id"], "position": 0},
    )
    assert movida.status_code == 200, movida.text
    assert movida.json()["depth"] == 1
    assert [a["name"] for a in movida.json()["ancestors"]] == ["Destino"]

    # La nieta viaja con su madre: la caché del árbol se reconstruye entera.
    detalle_nieta = (await cliente.get(f"{PREFIJO}/categories/{nieta['id']}")).json()
    assert detalle_nieta["depth"] == 2
    assert [a["name"] for a in detalle_nieta["ancestors"]] == ["Destino", "Hija"]
    assert (await cliente.get(f"{PREFIJO}/categories/{origen['id']}")).json()[
        "descendants_count"
    ] == 0


async def test_mover_al_nivel_raiz(cliente: AsyncClient) -> None:
    await registrar(cliente)
    madre = await crear(cliente, "Madre")
    hija = await crear(cliente, "Hija", madre["id"])
    movida = await cliente.post(
        f"{PREFIJO}/categories/{hija['id']}/move",
        headers=cabeceras(cliente),
        json={"parent_id": None, "position": 5},
    )
    assert movida.status_code == 200
    assert movida.json()["parent_id"] is None
    assert movida.json()["depth"] == 0
    assert movida.json()["position"] == 5


async def test_reordenar_varias_hermanas_de_golpe(cliente: AsyncClient) -> None:
    await registrar(cliente)
    una = await crear(cliente, "Una", position=0)
    dos = await crear(cliente, "Dos", position=1)
    tres = await crear(cliente, "Tres", position=2)

    respuesta = await cliente.post(
        f"{PREFIJO}/categories/reorder",
        headers=cabeceras(cliente),
        json={
            "items": [
                {"id": tres["id"], "parent_id": None, "position": 0},
                {"id": dos["id"], "parent_id": None, "position": 1},
                {"id": una["id"], "parent_id": None, "position": 2},
            ]
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    arbol = (await cliente.get(f"{PREFIJO}/categories/tree")).json()
    assert [n["name"] for n in arbol] == ["Tres", "Dos", "Una"]


async def test_reordenar_rechaza_repetidos(cliente: AsyncClient) -> None:
    await registrar(cliente)
    una = await crear(cliente, "Una")
    respuesta = await cliente.post(
        f"{PREFIJO}/categories/reorder",
        headers=cabeceras(cliente),
        json={
            "items": [
                {"id": una["id"], "position": 0},
                {"id": una["id"], "position": 1},
            ]
        },
    )
    assert respuesta.status_code == 422


# --------------------------------------------------------------------------- #
# Archivado (F-06, RN-13)
# --------------------------------------------------------------------------- #


async def test_archivar_arrastra_el_subarbol_y_desarchivar_los_antepasados(
    cliente: AsyncClient,
) -> None:
    await registrar(cliente)
    madre = await crear(cliente, "Madre")
    hija = await crear(cliente, "Hija", madre["id"])
    nieta = await crear(cliente, "Nieta", hija["id"])

    archivada = await cliente.post(
        f"{PREFIJO}/categories/{madre['id']}/archive", headers=cabeceras(cliente)
    )
    assert archivada.status_code == 200
    assert archivada.json()["is_archived"] is True
    assert (await cliente.get(f"{PREFIJO}/categories/{nieta['id']}")).json()["is_archived"] is True
    assert (await cliente.get(f"{PREFIJO}/categories/tree")).json() == []

    # Desarchivar la nieta reactiva la rama entera: una activa no puede colgar de
    # una archivada.
    recuperada = await cliente.post(
        f"{PREFIJO}/categories/{nieta['id']}/unarchive", headers=cabeceras(cliente)
    )
    assert recuperada.json()["is_archived"] is False
    assert (await cliente.get(f"{PREFIJO}/categories/{madre['id']}")).json()["is_archived"] is False
    assert (await cliente.get(f"{PREFIJO}/categories/{hija['id']}")).json()["is_archived"] is False


async def test_archivar_sin_cascada_avisa_de_las_hijas(cliente: AsyncClient) -> None:
    await registrar(cliente)
    madre = await crear(cliente, "Madre")
    await crear(cliente, "Hija", madre["id"])
    respuesta = await cliente.post(
        f"{PREFIJO}/categories/{madre['id']}/archive?cascade=false", headers=cabeceras(cliente)
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["codigo"] == "tematica_con_descendientes"


async def test_las_archivadas_se_listan_aparte(cliente: AsyncClient) -> None:
    await registrar(cliente)
    viva = await crear(cliente, "Viva")
    muerta = await crear(cliente, "Antigua")
    await cliente.post(f"{PREFIJO}/categories/{muerta['id']}/archive", headers=cabeceras(cliente))

    activas = (await cliente.get(f"{PREFIJO}/categories")).json()
    assert [c["name"] for c in activas["items"]] == ["Viva"]
    archivadas = (await cliente.get(f"{PREFIJO}/categories?is_archived=true")).json()
    assert [c["name"] for c in archivadas["items"]] == ["Antigua"]
    assert viva["id"] != muerta["id"]


# --------------------------------------------------------------------------- #
# Uso y borrado (RN-14)
# --------------------------------------------------------------------------- #


async def test_uso_y_borrado_con_historico(cliente: AsyncClient, sesion_bd: AsyncSession) -> None:
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    tematica = await crear(cliente, "Con histórico")
    limpia = await crear(cliente, "Sin nada")

    cuenta = await cliente.post(
        f"{PREFIJO}/accounts",
        headers=cabeceras(cliente),
        json={"name": "Nómina", "type": "checking"},
    )
    sesion_bd.add(
        Transaction(
            household_id=hogar,
            account_id=uuid.UUID(cuenta.json()["id"]),
            kind="expense",
            booked_on=date(2026, 3, 4),
            amount=Decimal("-15.00"),
            category_id=uuid.UUID(tematica["id"]),
            description="Algo",
        )
    )
    await sesion_bd.commit()

    uso = (await cliente.get(f"{PREFIJO}/categories/{tematica['id']}/usage")).json()
    assert uso["transactions"] == 1
    assert uso["first_used_on"] == "2026-03-04"
    assert uso["can_hard_delete"] is False

    sin_reasignar = await cliente.delete(
        f"{PREFIJO}/categories/{tematica['id']}", headers=cabeceras(cliente)
    )
    assert sin_reasignar.status_code == 409
    assert sin_reasignar.json()["error"]["codigo"] == "tematica_con_historico"

    # Con destino, el histórico se traslada y la temática desaparece del árbol.
    reasignada = await cliente.delete(
        f"{PREFIJO}/categories/{tematica['id']}?reassign_to={limpia['id']}",
        headers=cabeceras(cliente),
    )
    assert reasignada.status_code == 204
    assert (await cliente.get(f"{PREFIJO}/categories/{limpia['id']}/usage")).json()[
        "transactions"
    ] == 1
    assert [c["name"] for c in (await cliente.get(f"{PREFIJO}/categories/tree")).json()] == [
        "Sin nada"
    ]


async def test_borrar_una_tematica_con_hijas_no_se_permite(cliente: AsyncClient) -> None:
    await registrar(cliente)
    madre = await crear(cliente, "Madre")
    await crear(cliente, "Hija", madre["id"])
    respuesta = await cliente.delete(
        f"{PREFIJO}/categories/{madre['id']}", headers=cabeceras(cliente)
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["error"]["codigo"] == "tematica_con_descendientes"


async def test_borrar_una_tematica_limpia(cliente: AsyncClient) -> None:
    await registrar(cliente)
    tematica = await crear(cliente, "Prueba")
    assert (await cliente.get(f"{PREFIJO}/categories/{tematica['id']}/usage")).json()[
        "can_hard_delete"
    ] is True
    borrada = await cliente.delete(
        f"{PREFIJO}/categories/{tematica['id']}", headers=cabeceras(cliente)
    )
    assert borrada.status_code == 204
    assert (await cliente.get(f"{PREFIJO}/categories/{tematica['id']}")).status_code == 404


# --------------------------------------------------------------------------- #
# Estadísticas y temática por defecto
# --------------------------------------------------------------------------- #


async def test_estadisticas_por_periodo(cliente: AsyncClient, sesion_bd: AsyncSession) -> None:
    correo = await registrar(cliente)
    hogar = await hogar_de(sesion_bd, correo)
    tematica = await crear(cliente, "Ocio")
    cuenta = await cliente.post(
        f"{PREFIJO}/accounts",
        headers=cabeceras(cliente),
        json={"name": "Nómina", "type": "checking"},
    )
    for importe, dia in (("-20.00", 3), ("-30.00", 14)):
        sesion_bd.add(
            Transaction(
                household_id=hogar,
                account_id=uuid.UUID(cuenta.json()["id"]),
                kind="expense",
                booked_on=date(2026, 5, dia),
                amount=Decimal(importe),
                category_id=uuid.UUID(tematica["id"]),
                description="Cine",
            )
        )
    await sesion_bd.commit()

    mayo = (await cliente.get(f"{PREFIJO}/categories?period=2026-05")).json()["items"][0]
    # `spent` invierte el signo del gasto: 50 € gastados, no −50.
    assert mayo["spent"] == "50.00"
    assert mayo["transactions_count"] == 2
    assert mayo["allocated"] == "0.00"

    junio = (await cliente.get(f"{PREFIJO}/categories?period=2026-06")).json()["items"][0]
    assert junio["spent"] == "0.00"


async def test_tematica_por_defecto_es_unica(cliente: AsyncClient) -> None:
    await registrar(cliente)
    una = await crear(cliente, "Sin clasificar")
    otra = await crear(cliente, "Varios")

    primera = await cliente.patch(
        f"{PREFIJO}/categories/{una['id']}", headers=cabeceras(cliente), json={"is_default": True}
    )
    assert primera.json()["is_default"] is True

    segunda = await cliente.patch(
        f"{PREFIJO}/categories/{otra['id']}", headers=cabeceras(cliente), json={"is_default": True}
    )
    assert segunda.json()["is_default"] is True
    assert (await cliente.get(f"{PREFIJO}/categories/{una['id']}")).json()["is_default"] is False


async def test_la_del_sistema_no_se_renombra_ni_se_archiva(cliente: AsyncClient) -> None:
    await registrar(cliente)
    await cliente.post(
        f"{PREFIJO}/onboarding/seed", headers=cabeceras(cliente), json={"preset": "es_basico"}
    )
    todas = (await cliente.get(f"{PREFIJO}/categories?size=200")).json()["items"]
    sistema = next(c for c in todas if c["is_default"])

    renombrada = await cliente.patch(
        f"{PREFIJO}/categories/{sistema['id']}", headers=cabeceras(cliente), json={"name": "Otra"}
    )
    assert renombrada.status_code == 409
    archivada = await cliente.post(
        f"{PREFIJO}/categories/{sistema['id']}/archive", headers=cabeceras(cliente)
    )
    assert archivada.status_code == 409


# --------------------------------------------------------------------------- #
# Validaciones de los endpoints de fusión
# --------------------------------------------------------------------------- #


async def test_fusion_rechaza_consigo_misma_y_entre_tipos_distintos(
    cliente: AsyncClient,
) -> None:
    await registrar(cliente)
    gasto = await crear(cliente, "Gasto")
    ingreso = await crear(cliente, "Ingreso", kind="income")

    # RN-17 la corta ya en el esquema, así que llega como error de validación con
    # el mensaje concreto en `detalles`.
    consigo = await cliente.post(
        f"{PREFIJO}/categories/merge/preview",
        headers=cabeceras(cliente),
        json={"source_ids": [gasto["id"]], "target_id": gasto["id"]},
    )
    assert consigo.status_code == 422
    assert consigo.json()["error"]["codigo"] == "datos_invalidos"
    assert "consigo misma" in consigo.json()["error"]["detalles"][0]["mensaje"]

    cruzada = await cliente.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(cliente),
        json={"source_ids": [ingreso["id"]], "target_id": gasto["id"]},
    )
    assert cruzada.status_code == 422
    assert cruzada.json()["error"]["codigo"] == "fusion_invalida"


async def test_el_historial_de_fusiones_esta_vacio_al_principio(cliente: AsyncClient) -> None:
    await registrar(cliente)
    historial = (await cliente.get(f"{PREFIJO}/categories/merges")).json()
    assert historial["total"] == 0
    assert historial["items"] == []

    inexistente = await cliente.post(
        f"{PREFIJO}/categories/merges/{uuid.uuid4()}/undo", headers=cabeceras(cliente)
    )
    assert inexistente.status_code == 404


# --------------------------------------------------------------------------- #
# Aislamiento entre hogares (RN-01, RN-02)
# --------------------------------------------------------------------------- #


async def test_un_hogar_no_ve_ni_toca_las_tematicas_de_otro(
    cliente: AsyncClient, navegadores: Callable[[], AsyncClient]
) -> None:
    await registrar(cliente, nombre="Ana")
    de_ana = await crear(cliente, "Temática de Ana")

    bruno = navegadores()
    await registrar(bruno, nombre="Bruno")
    de_bruno = await crear(bruno, "Temática de Bruno")

    assert [c["name"] for c in (await bruno.get(f"{PREFIJO}/categories")).json()["items"]] == [
        "Temática de Bruno"
    ]
    assert [n["name"] for n in (await bruno.get(f"{PREFIJO}/categories/tree")).json()] == [
        "Temática de Bruno"
    ]

    ruta = f"{PREFIJO}/categories/{de_ana['id']}"
    assert (await bruno.get(ruta)).status_code == 404
    assert (await bruno.get(f"{ruta}/usage")).status_code == 404
    assert (
        await bruno.patch(ruta, headers=cabeceras(bruno), json={"name": "Mía"})
    ).status_code == 404
    assert (await bruno.post(f"{ruta}/archive", headers=cabeceras(bruno))).status_code == 404
    assert (await bruno.delete(ruta, headers=cabeceras(bruno))).status_code == 404
    assert (
        await bruno.post(
            f"{ruta}/move", headers=cabeceras(bruno), json={"parent_id": de_bruno["id"]}
        )
    ).status_code == 404

    # Ni siquiera puede intentar fusionar la ajena con la suya.
    fusion = await bruno.post(
        f"{PREFIJO}/categories/merge",
        headers=cabeceras(bruno),
        json={"source_ids": [de_ana["id"]], "target_id": de_bruno["id"]},
    )
    assert fusion.status_code == 404

    # Y mover la suya bajo una ajena tampoco cuela.
    cruzado = await bruno.post(
        f"{PREFIJO}/categories/{de_bruno['id']}/move",
        headers=cabeceras(bruno),
        json={"parent_id": de_ana["id"]},
    )
    assert cruzado.status_code == 404

    # Nada de lo anterior ha tocado la temática de Ana.
    intacta = (await cliente.get(ruta)).json()
    assert (intacta["name"], intacta["is_archived"], intacta["parent_id"]) == (
        "Temática de Ana",
        False,
        None,
    )
