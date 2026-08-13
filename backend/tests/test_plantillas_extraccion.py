"""Pruebas de las plantillas de extracción por proveedor (F-40).

Los PDF se generan al vuelo con PyMuPDF, igual que los de `conftest.py`, para que
no haya ficheros binarios en el repositorio y se vea en el propio test qué dice la
factura.

La prueba que de verdad importa es `TestDeducir::test_la_plantilla_deducida_lee_la
_factura_como_la_dejo_el_usuario`: si deducir una plantilla de una factura ya
corregida no reproduce esa corrección, la funcionalidad no sirve para nada.
"""

from datetime import date
from decimal import Decimal

import pymupdf
import pytest

from app.services import plantillas_extraccion as plantillas
from app.services.extraccion_pdf import extraer_factura
from app.services.plantillas_extraccion import (
    FacturaCorregida,
    LineaCorregida,
    PlantillaExtraccion,
    PlantillaInvalida,
)
from tests import test_api_facturas as andamio
from tests.test_api_facturas import SUPERMERCADO, cliente_para, crear_entorno, subir_factura

# El andamio de PostgreSQL vive en `test_api_facturas.py`; sus fixturas se
# reexportan aquí para que pytest las resuelva por nombre.
aplicacion = andamio.aplicacion
cliente = andamio.cliente
ejemplos = andamio.ejemplos
entorno = andamio.entorno


def _pdf(lineas: list[tuple[float, float, str]], rejilla=None) -> bytes:
    """Un PDF de una página con el texto en las posiciones indicadas."""
    documento = pymupdf.open()
    pagina = documento.new_page(width=595, height=842)
    for x, y, texto in lineas:
        pagina.insert_text((x, y), texto, fontname="helv", fontsize=9)
    for x0, y0, x1, y1 in rejilla or []:
        pagina.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0, 0, 0), width=0.6)
    datos = documento.tobytes()
    documento.close()
    return datos


@pytest.fixture
def factura_del_norte() -> bytes:
    """La factura problemática: el extractor genérico falla dos veces con ella.

    1. El emisor sale pegado a la referencia del contrato, porque comparten línea.
    2. El total no se encuentra: la etiqueta es «LIQUIDO A PERCIBIR» y no hay base
       ni cuota de las que deducirlo.

    Y encima cuela «Portes y embalaje», que no es un producto (RN-48). Es
    exactamente el caso de F-40: un fallo que se repite igual cada mes.
    """
    return _pdf(
        [
            (50, 60, "COMERCIAL DEL NORTE S.L."),
            (50, 74, "NIF: B12345674"),
            (400, 60, "Ref. contrato 998877"),
            (400, 74, "Fecha de emision: 03/08/2026"),
            (50, 130, "Concepto                    Cantidad   Precio    Importe"),
            (50, 150, "Servicio de limpieza mensual     4       25,00     100,00"),
            (50, 166, "Material fungible de oficina     1       15,50      15,50"),
            (50, 200, "Portes y embalaje                1        7,00       7,00"),
            (50, 240, "LIQUIDO A PERCIBIR                                122,50"),
        ]
    )


@pytest.fixture
def factura_con_rejilla() -> bytes:
    """Factura de suministro con la tabla dibujada: se lee por columnas."""
    filas = [
        (50, 60, "ENERGIA IBERICA S.A."),
        (50, 74, "C.I.F.: A78374725"),
        (400, 60, "Factura n. 2026-LUZ-00931"),
        (400, 74, "Fecha factura: 12 de julio de 2026"),
        (55, 145, "Concepto"),
        (250, 145, "Cantidad"),
        (330, 145, "Precio"),
        (430, 145, "Importe"),
        (55, 175, "Energia consumida P1"),
        (250, 175, "148,00 kWh"),
        (330, 175, "0,148900"),
        (430, 175, "22,04"),
        (55, 205, "Potencia contratada P1"),
        (250, 205, "30,00"),
        (330, 205, "0,103763"),
        (430, 205, "3,11"),
        (55, 235, "Alquiler de equipo de medida"),
        (250, 235, "30,00"),
        (330, 235, "0,026630"),
        (430, 235, "0,80"),
        (50, 300, "Base imponible: 25,95"),
        (50, 316, "TOTAL IMPORTE FACTURA: 33,01"),
    ]
    rejilla = [
        (50, 130, 500, 160),
        (50, 160, 500, 190),
        (50, 190, 500, 220),
        (50, 220, 500, 250),
        (50, 130, 245, 250),
        (245, 130, 325, 250),
        (325, 130, 425, 250),
    ]
    return _pdf(filas, rejilla)


def _buscar(factura, fragmento: str):
    for linea in factura.lineas:
        if fragmento.lower() in linea.descripcion.lower():
            return linea
    return None


# --------------------------------------------------------------------------- #
# La plantilla como dato: validación y ida y vuelta
# --------------------------------------------------------------------------- #


class TestValidacion:
    def test_una_expresion_mal_escrita_se_explica_en_castellano(self):
        errores = plantillas.validar(PlantillaExtraccion(nombre="X", campos={"total": "(("}))

        assert len(errores) == 1
        assert "total" in errores[0]
        assert errores[0].endswith(".")

    def test_un_campo_de_cabecera_que_no_existe_se_rechaza(self):
        errores = plantillas.validar(PlantillaExtraccion(nombre="X", campos={"inventado": r"\d+"}))

        assert "inventado" in errores[0]
        assert "issuer" in errores[0]

    def test_el_patron_de_fila_necesita_el_grupo_de_la_descripcion(self):
        errores = plantillas.validar(
            PlantillaExtraccion(nombre="X", patron_linea=r"^(?P<total>[\d,]+)$")
        )

        assert "description" in errores[0]

    def test_un_indice_de_columna_negativo_se_rechaza(self):
        errores = plantillas.validar(
            PlantillaExtraccion(nombre="X", columnas={"description": 0, "total": -1})
        )

        assert "total" in errores[0]

    def test_el_mapa_de_columnas_sin_descripcion_no_vale(self):
        errores = plantillas.validar(PlantillaExtraccion(nombre="X", columnas={"total": 3}))

        assert "description" in errores[0]

    def test_una_columna_que_no_existe_se_rechaza(self):
        errores = plantillas.validar(
            PlantillaExtraccion(nombre="X", columnas={"description": 0, "descuento": 1})
        )

        assert "descuento" in errores[0]

    def test_aplicar_una_plantilla_invalida_falla_antes_de_abrir_el_pdf(self, factura_del_norte):
        with pytest.raises(PlantillaInvalida):
            plantillas.aplicar(
                factura_del_norte, PlantillaExtraccion(nombre="X", campos={"total": "(("})
            )

    def test_una_plantilla_vacia_es_valida(self):
        assert plantillas.validar(PlantillaExtraccion(nombre="X")) == []


class TestIdaYVuelta:
    def _completa(self) -> PlantillaExtraccion:
        return PlantillaExtraccion(
            nombre="Comercial del Norte",
            patron_emisor="COMERCIAL DEL NORTE",
            nif_emisor="B12345674",
            prioridad=50,
            campos={"total": r"LIQUIDO A PERCIBIR\s+(?P<valor>[\d.,]+)"},
            columnas={"description": 0, "total": 3},
            encabezados={"quantity": "cantidad"},
            patron_linea=r"^(?P<description>.+?)\s+(?P<total>[\d.,]+)$",
            ignorar=[r"^\s*portes"],
            forzar_ocr=True,
            descartar_sin_importe=False,
            unidad_por_defecto="ud",
        )

    def test_las_cuatro_columnas_jsonb_conservan_toda_la_plantilla(self):
        original = self._completa()
        columnas = plantillas.a_jsonb(original)

        vuelta = plantillas.desde_jsonb(
            nombre=original.nombre,
            patron_emisor=original.patron_emisor,
            nif_emisor=original.nif_emisor,
            prioridad=original.prioridad,
            **columnas,
        )
        assert vuelta == original

    def test_una_fila_a_medio_rellenar_no_revienta(self):
        """Las plantillas de serie pueden traer solo la cabecera."""
        plantilla = plantillas.desde_jsonb(nombre="Mínima", patron_emisor="ACME")

        assert plantilla.campos == {}
        assert plantilla.columnas == {}
        assert plantilla.ignorar == []
        assert plantilla.descartar_sin_importe is True
        assert plantilla.toca_las_lineas is False

    def test_los_campos_editables_son_un_solo_mapa_plano(self):
        editables = plantillas.campos_editables(self._completa())

        assert editables["total"].startswith("LIQUIDO")
        assert editables["line_row"].startswith("^(?P<description>")
        assert editables["column:quantity"] == "cantidad"
        assert editables["ignore:1"] == r"^\s*portes"

    def test_el_mapa_plano_vuelve_a_la_plantilla(self):
        original = self._completa()
        vacia = PlantillaExtraccion(nombre=original.nombre)

        rehecha = plantillas.con_campos_editables(
            vacia, plantillas.campos_editables(original), dict(original.columnas)
        )
        assert rehecha.campos == original.campos
        assert rehecha.encabezados == original.encabezados
        assert rehecha.ignorar == original.ignorar
        assert rehecha.patron_linea == original.patron_linea
        assert rehecha.columnas == original.columnas


# --------------------------------------------------------------------------- #
# ¿Qué plantilla toca?
# --------------------------------------------------------------------------- #


class TestSeleccion:
    def test_el_nif_reconoce_la_factura_aunque_cambie_el_nombre(self, factura_del_norte):
        texto = plantillas.texto_de_portada(factura_del_norte)
        plantilla = PlantillaExtraccion(nombre="X", nif_emisor="B-12345674")

        assert plantillas.coincide(plantilla, texto)

    def test_el_patron_del_emisor_reconoce_la_factura(self, factura_del_norte):
        texto = plantillas.texto_de_portada(factura_del_norte)

        assert plantillas.coincide(
            PlantillaExtraccion(nombre="X", patron_emisor="del norte"), texto
        )
        assert not plantillas.coincide(
            PlantillaExtraccion(nombre="X", patron_emisor="ENDESA"), texto
        )

    def test_una_plantilla_sin_selector_no_reconoce_nada(self, factura_del_norte):
        texto = plantillas.texto_de_portada(factura_del_norte)

        assert not plantillas.coincide(PlantillaExtraccion(nombre="X"), texto)

    def test_un_patron_roto_no_reconoce_en_vez_de_reventar(self, factura_del_norte):
        texto = plantillas.texto_de_portada(factura_del_norte)

        assert not plantillas.coincide(PlantillaExtraccion(nombre="X", patron_emisor="(("), texto)

    def test_gana_la_prioridad_mas_baja_la_del_hogar_antes_que_la_de_serie(self, factura_del_norte):
        texto = plantillas.texto_de_portada(factura_del_norte)
        serie = PlantillaExtraccion(nombre="De serie", patron_emisor="NORTE", prioridad=100)
        hogar = PlantillaExtraccion(nombre="Mía", patron_emisor="NORTE", prioridad=50)

        elegidas = plantillas.seleccionar([serie, hogar], texto)
        assert [una.nombre for una in elegidas] == ["Mía", "De serie"]

    def test_la_portada_de_un_pdf_ilegible_es_cadena_vacia(self):
        assert plantillas.texto_de_portada(b"no soy un pdf") == ""


# --------------------------------------------------------------------------- #
# Aplicar la plantilla
# --------------------------------------------------------------------------- #


class TestAplicar:
    def test_el_extractor_generico_falla_con_esta_factura(self, factura_del_norte):
        """El punto de partida: sin esto, las pruebas siguientes no prueban nada."""
        leida = extraer_factura(factura_del_norte, ocr_habilitado=False)

        assert leida.total is None
        assert "Ref. contrato" in (leida.emisor or "")
        assert _buscar(leida, "portes") is not None

    def test_una_regla_de_cabecera_pisa_lo_que_leyo_el_extractor(self, factura_del_norte):
        plantilla = PlantillaExtraccion(
            nombre="Norte",
            patron_emisor="COMERCIAL DEL NORTE",
            campos={
                "total": r"LIQUIDO\s+A\s+PERCIBIR\s+(?P<valor>[\d.,]+)",
                "issuer": r"(?P<valor>COMERCIAL\s+DEL\s+NORTE\s+S\.L\.)",
            },
        )
        leida = plantillas.aplicar(factura_del_norte, plantilla, ocr_habilitado=False)

        assert leida is not None
        assert leida.total == Decimal("122.50")
        assert leida.emisor == "COMERCIAL DEL NORTE S.L."

    def test_lo_que_la_plantilla_no_dice_lo_sigue_leyendo_el_extractor(self, factura_del_norte):
        """Una plantilla arregla lo que falla; no tiene que repetir lo que ya va bien."""
        plantilla = PlantillaExtraccion(
            nombre="Norte",
            patron_emisor="NORTE",
            campos={"total": r"LIQUIDO\s+A\s+PERCIBIR\s+(?P<valor>[\d.,]+)"},
        )
        leida = plantillas.aplicar(factura_del_norte, plantilla, ocr_habilitado=False)

        assert leida is not None
        assert leida.nif_emisor == "B12345674"
        assert leida.fecha == date(2026, 8, 3)
        assert _buscar(leida, "limpieza") is not None

    def test_una_regla_que_no_encuentra_nada_avisa_en_vez_de_borrar_el_dato(
        self, factura_del_norte
    ):
        plantilla = PlantillaExtraccion(
            nombre="Norte",
            patron_emisor="NORTE",
            campos={"number": r"NUMERO\s+MAGICO\s+(?P<valor>\S+)"},
        )
        leida = plantillas.aplicar(factura_del_norte, plantilla, ocr_habilitado=False)

        assert leida is not None
        assert any("no ha encontrado number" in aviso for aviso in leida.avisos)

    def test_las_filas_que_no_son_productos_se_descartan(self, factura_del_norte):
        plantilla = PlantillaExtraccion(
            nombre="Norte", patron_emisor="NORTE", ignorar=[r"^\s*portes\s+y\s+embalaje"]
        )
        leida = plantillas.aplicar(factura_del_norte, plantilla, ocr_habilitado=False)

        assert leida is not None
        assert _buscar(leida, "portes") is None
        assert _buscar(leida, "limpieza") is not None

    def test_el_patron_de_fila_lee_las_lineas_de_una_factura_sin_rejilla(self, factura_del_norte):
        plantilla = PlantillaExtraccion(
            nombre="Norte",
            patron_emisor="NORTE",
            patron_linea=(
                r"^(?P<description>.+?)\s+(?P<quantity>\d+)\s+"
                r"(?P<unit_price>[\d.,]+)\s+(?P<total>[\d.,]+)$"
            ),
        )
        leida = plantillas.aplicar(factura_del_norte, plantilla, ocr_habilitado=False)

        assert leida is not None
        assert leida.metodo == "texto"
        limpieza = _buscar(leida, "limpieza")
        assert limpieza is not None
        assert limpieza.cantidad == Decimal("4")
        assert limpieza.precio_unitario == Decimal("25.00")
        assert limpieza.total == Decimal("100.00")

    def test_las_columnas_por_indice_leen_la_tabla_con_rejilla(self, factura_con_rejilla):
        plantilla = PlantillaExtraccion(
            nombre="Luz",
            patron_emisor="ENERGIA IBERICA",
            columnas={"description": 0, "quantity": 1, "unit_price": 2, "total": 3},
        )
        leida = plantillas.aplicar(factura_con_rejilla, plantilla, ocr_habilitado=False)

        assert leida is not None
        assert leida.metodo == "tabla"
        energia = _buscar(leida, "energia consumida")
        assert energia is not None
        assert energia.cantidad == Decimal("148.00")
        assert energia.unidad == "kWh"
        # El precio unitario conserva sus cuatro decimales: redondearlo a céntimos
        # falsearía el histórico del kWh.
        assert energia.precio_unitario == Decimal("0.1489")

    def test_las_columnas_por_encabezado_aguantan_que_se_muevan_de_sitio(self, factura_con_rejilla):
        plantilla = PlantillaExtraccion(
            nombre="Luz",
            patron_emisor="ENERGIA IBERICA",
            encabezados={
                "description": "concepto",
                "quantity": "cantidad",
                "unit_price": "precio",
                "total": "importe",
            },
        )
        leida = plantillas.aplicar(factura_con_rejilla, plantilla, ocr_habilitado=False)

        assert leida is not None
        assert len(leida.lineas) == 3
        assert _buscar(leida, "concepto") is None

    def test_la_unidad_por_defecto_rellena_las_lineas_que_no_la_traen(self, factura_con_rejilla):
        plantilla = PlantillaExtraccion(
            nombre="Luz",
            patron_emisor="ENERGIA IBERICA",
            columnas={"description": 0, "quantity": 1, "unit_price": 2, "total": 3},
            unidad_por_defecto="mes",
        )
        leida = plantillas.aplicar(factura_con_rejilla, plantilla, ocr_habilitado=False)

        assert leida is not None
        assert _buscar(leida, "potencia contratada").unidad == "mes"
        # La que sí traía unidad se queda con la suya.
        assert _buscar(leida, "energia consumida").unidad == "kWh"

    def test_una_plantilla_que_dice_como_leer_las_lineas_y_no_lee_ninguna_es_un_fallo(
        self, factura_del_norte
    ):
        """Devolver una factura vacía «según la plantilla» esconde el problema."""
        plantilla = PlantillaExtraccion(
            nombre="Norte",
            patron_emisor="NORTE",
            # Esta factura no tiene rejilla, así que por columnas no sale nada.
            columnas={"description": 0, "total": 3},
        )
        assert plantillas.aplicar(factura_del_norte, plantilla, ocr_habilitado=False) is None


# --------------------------------------------------------------------------- #
# El envoltorio: plantilla primero, tres pasadas después
# --------------------------------------------------------------------------- #


class TestEnvoltorio:
    def test_sin_plantillas_se_lee_como_siempre(self, factura_del_norte):
        resultado = plantillas.extraer_con_plantillas(factura_del_norte, [], ocr_habilitado=False)

        assert resultado.plantilla is None
        assert resultado.fallidas == []
        assert _buscar(resultado.factura, "limpieza") is not None

    def test_la_plantilla_del_emisor_se_usa_primero(self, factura_del_norte):
        plantilla = PlantillaExtraccion(
            nombre="Norte",
            patron_emisor="COMERCIAL DEL NORTE",
            campos={"total": r"LIQUIDO\s+A\s+PERCIBIR\s+(?P<valor>[\d.,]+)"},
        )
        resultado = plantillas.extraer_con_plantillas(
            factura_del_norte, [plantilla], ocr_habilitado=False
        )

        assert resultado.plantilla is plantilla
        assert resultado.factura.total == Decimal("122.50")
        assert any("plantilla «Norte»" in aviso for aviso in resultado.factura.avisos)

    def test_la_plantilla_de_otro_emisor_no_se_aplica(self, factura_del_norte):
        otra = PlantillaExtraccion(
            nombre="Endesa", patron_emisor="ENDESA", campos={"total": r"NADA\s+(?P<valor>\d+)"}
        )
        resultado = plantillas.extraer_con_plantillas(
            factura_del_norte, [otra], ocr_habilitado=False
        )

        assert resultado.plantilla is None
        assert resultado.fallidas == []

    def test_si_la_plantilla_falla_se_cae_a_las_tres_pasadas_y_se_avisa(self, factura_del_norte):
        """Que la plantilla se haya quedado vieja no puede dejar la factura sin leer."""
        rota = PlantillaExtraccion(
            nombre="Vieja", patron_emisor="NORTE", columnas={"description": 0, "total": 3}
        )
        resultado = plantillas.extraer_con_plantillas(
            factura_del_norte, [rota], ocr_habilitado=False
        )

        assert resultado.plantilla is None
        assert [una.nombre for una in resultado.fallidas] == ["Vieja"]
        assert _buscar(resultado.factura, "limpieza") is not None
        assert any("no ha servido" in aviso for aviso in resultado.factura.avisos)

    def test_la_elegida_a_mano_se_prueba_aunque_su_patron_no_coincida(self, factura_del_norte):
        elegida = PlantillaExtraccion(
            nombre="A mano",
            patron_emisor="ENDESA",
            campos={"total": r"LIQUIDO\s+A\s+PERCIBIR\s+(?P<valor>[\d.,]+)"},
        )
        resultado = plantillas.extraer_con_plantillas(
            factura_del_norte, [elegida], exigir_coincidencia=False, ocr_habilitado=False
        )

        assert resultado.plantilla is elegida
        assert resultado.factura.total == Decimal("122.50")

    def test_una_plantilla_invalida_se_salta_sin_tumbar_la_extraccion(self, factura_del_norte):
        rota = PlantillaExtraccion(nombre="Rota", patron_emisor="NORTE", campos={"total": "(("})
        resultado = plantillas.extraer_con_plantillas(
            factura_del_norte, [rota], ocr_habilitado=False
        )

        assert resultado.plantilla is None
        assert [una.nombre for una in resultado.fallidas] == ["Rota"]
        assert resultado.factura.lineas


# --------------------------------------------------------------------------- #
# Deducir la plantilla de una factura ya corregida
# --------------------------------------------------------------------------- #


def _corregida(datos: bytes) -> tuple[FacturaCorregida, object]:
    """La factura del Norte tal y como la deja el usuario tras revisarla."""
    leida = extraer_factura(datos, ocr_habilitado=False)
    corregida = FacturaCorregida(
        texto=leida.texto_crudo,
        emisor="COMERCIAL DEL NORTE S.L.",
        nif_emisor="B12345674",
        fecha=date(2026, 8, 3),
        total=Decimal("122.50"),
        lineas=(
            LineaCorregida(
                "Servicio de limpieza mensual", Decimal("4"), None, None, Decimal("100.00")
            ),
            LineaCorregida(
                "Material fungible de oficina", Decimal("1"), None, None, Decimal("15.50")
            ),
            LineaCorregida("Portes y embalaje", Decimal("1"), None, None, Decimal("7.00"), True),
        ),
    )
    return corregida, leida


class TestDeducir:
    def test_no_se_propone_ninguna_regla_para_lo_que_ya_se_lee_bien(self, factura_del_norte):
        corregida, leida = _corregida(factura_del_norte)
        deduccion = plantillas.deducir(corregida, leida)

        assert "issuer_tax_id" in deduccion.ya_correctos
        assert "date" in deduccion.ya_correctos
        assert "issuer_tax_id" not in deduccion.plantilla.campos
        assert "date" not in deduccion.plantilla.campos

    def test_se_propone_regla_para_los_campos_que_el_extractor_falla(self, factura_del_norte):
        corregida, leida = _corregida(factura_del_norte)
        deduccion = plantillas.deducir(corregida, leida)

        assert "total" in deduccion.plantilla.campos
        assert "issuer" in deduccion.plantilla.campos
        assert deduccion.sin_resolver == []

    def test_la_regla_del_total_se_ancla_en_su_etiqueta_y_no_en_el_importe(self, factura_del_norte):
        """Fijar «122,50» en la plantilla no valdría para la factura del mes que viene."""
        corregida, leida = _corregida(factura_del_norte)
        regla = plantillas.deducir(corregida, leida).plantilla.campos["total"]

        assert "122" not in regla
        assert "LIQUIDO" in regla.upper()

    def test_toda_regla_propuesta_acierta_sobre_el_texto_de_la_factura(self, factura_del_norte):
        """La verificación es lo que separa deducir de adivinar."""
        corregida, leida = _corregida(factura_del_norte)
        plantilla = plantillas.deducir(corregida, leida).plantilla

        esperado = {
            "issuer": corregida.emisor,
            "total": corregida.total,
            "date": corregida.fecha,
            "issuer_tax_id": corregida.nif_emisor,
        }
        for campo, regla in plantilla.campos.items():
            assert plantillas.valor_de_campo(corregida.texto, campo, regla) == esperado[campo]

    def test_se_deduce_una_regla_para_la_fila_que_el_usuario_excluyo(self, factura_del_norte):
        corregida, leida = _corregida(factura_del_norte)
        plantilla = plantillas.deducir(corregida, leida).plantilla

        assert plantilla.ignorar
        compilados = [plantillas.compilar(p, donde="ignore") for p in plantilla.ignorar]
        assert any(patron.search("portes y embalaje") for patron in compilados)
        # Y ninguna de las reglas se lleva por delante una línea buena.
        assert not any(patron.search("servicio de limpieza mensual") for patron in compilados)

    def test_el_selector_sale_del_emisor_para_que_la_plantilla_se_reconozca_sola(
        self, factura_del_norte
    ):
        corregida, leida = _corregida(factura_del_norte)
        plantilla = plantillas.deducir(corregida, leida).plantilla

        assert plantilla.nif_emisor == "B12345674"
        assert plantilla.patron_emisor
        assert plantillas.coincide(plantilla, plantillas.texto_de_portada(factura_del_norte))

    def test_la_plantilla_deducida_lee_la_factura_como_la_dejo_el_usuario(self, factura_del_norte):
        """La prueba que justifica la funcionalidad entera.

        Se deduce de la factura corregida y se aplica al mismo PDF: tiene que salir
        lo que el usuario dejó, no lo que el extractor había leído.
        """
        corregida, leida = _corregida(factura_del_norte)
        plantilla = plantillas.deducir(corregida, leida).plantilla

        de_nuevo = plantillas.aplicar(factura_del_norte, plantilla, ocr_habilitado=False)

        assert de_nuevo is not None
        assert de_nuevo.emisor == "COMERCIAL DEL NORTE S.L."
        assert de_nuevo.total == Decimal("122.50")
        esperadas = [
            ("Servicio de limpieza mensual", Decimal("100.00")),
            ("Material fungible de oficina", Decimal("15.50")),
        ]
        assert [(linea.descripcion, linea.total) for linea in de_nuevo.lineas] == esperadas

    def test_la_plantilla_deducida_es_valida_y_guardable(self, factura_del_norte):
        corregida, leida = _corregida(factura_del_norte)
        plantilla = plantillas.deducir(corregida, leida).plantilla

        assert plantillas.validar(plantilla) == []
        columnas = plantillas.a_jsonb(plantilla)
        assert (
            plantillas.desde_jsonb(
                nombre=plantilla.nombre,
                patron_emisor=plantilla.patron_emisor,
                nif_emisor=plantilla.nif_emisor,
                **columnas,
            )
            == plantilla
        )

    def test_las_notas_explican_en_castellano_lo_que_se_va_a_guardar(self, factura_del_norte):
        corregida, leida = _corregida(factura_del_norte)
        deduccion = plantillas.deducir(corregida, leida)

        texto = " ".join(deduccion.notas)
        assert "Se han deducido reglas para" in texto
        assert "no es un producto" in texto or "no son productos" in texto

    def test_sin_lo_que_leyo_el_extractor_se_intenta_explicar_todo(self, factura_del_norte):
        corregida, _ = _corregida(factura_del_norte)
        deduccion = plantillas.deducir(corregida, None)

        assert deduccion.ya_correctos == []
        assert "total" in deduccion.plantilla.campos
        assert "issuer_tax_id" in deduccion.plantilla.campos

    def test_una_factura_que_ya_se_lee_bien_lo_dice_en_vez_de_inventar_reglas(
        self, factura_luz_tabla
    ):
        """No forzar reglas cuando no hacen falta: se rompen solas más adelante."""
        leida = extraer_factura(factura_luz_tabla, ocr_habilitado=False)
        corregida = FacturaCorregida(
            texto=leida.texto_crudo,
            emisor=leida.emisor,
            nif_emisor=leida.nif_emisor,
            numero=leida.numero,
            fecha=leida.fecha,
            total=leida.total,
            lineas=tuple(
                LineaCorregida(linea.descripcion, total=linea.total) for linea in leida.lineas
            ),
        )
        deduccion = plantillas.deducir(corregida, leida)

        assert deduccion.plantilla.campos == {}
        assert deduccion.plantilla.ignorar == []
        assert deduccion.plantilla.patron_linea is None
        assert any("se lee bien sin plantilla" in nota for nota in deduccion.notas)

    def test_un_valor_que_no_esta_en_el_texto_queda_sin_resolver(self, factura_del_norte):
        """El usuario puede haber escrito un dato que el PDF no dice."""
        corregida, leida = _corregida(factura_del_norte)
        a_mano = FacturaCorregida(
            texto=corregida.texto,
            numero="ESCRITO-A-MANO-999",
            lineas=corregida.lineas,
        )
        deduccion = plantillas.deducir(a_mano, leida)

        assert "number" in deduccion.sin_resolver
        assert "number" not in deduccion.plantilla.campos
        assert any("corrígelo a mano" in nota for nota in deduccion.notas)


# --------------------------------------------------------------------------- #
# Los endpoints (§3.12), contra PostgreSQL de verdad
# --------------------------------------------------------------------------- #


async def _factura_revisada(cliente) -> dict:
    """Sube una factura del supermercado y excluye una línea, como el usuario."""
    respuesta = await subir_factura(cliente, SUPERMERCADO[0])
    assert respuesta.status_code == 202, respuesta.text
    factura = respuesta.json()

    lineas = (await cliente.get(f"/api/v1/invoices/{factura['id']}/lines")).json()["lines"]
    assert lineas, "la factura de ejemplo tiene que traer líneas"
    excluida = await cliente.patch(
        f"/api/v1/invoices/{factura['id']}/lines/{lineas[-1]['id']}",
        json={"is_excluded": True},
    )
    assert excluida.status_code == 200, excluida.text
    return factura


async def _crear_plantilla(cliente, invoice_id: str, **extra) -> dict:
    respuesta = await cliente.post(
        "/api/v1/invoices/templates",
        json={
            "name": "Supermercado El Ahorro",
            "issuer_pattern": "EL AHORRO",
            "from_invoice_id": invoice_id,
            **extra,
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


async def test_deducir_de_una_factura_devuelve_las_reglas_antes_de_guardar(cliente):
    factura = await _factura_revisada(cliente)

    respuesta = await cliente.post(
        "/api/v1/invoices/templates/deduce", json={"invoice_id": factura["id"]}
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    # La línea excluida a mano tiene que aparecer como regla de descarte: es la
    # corrección que el usuario no quiere repetir el mes que viene.
    assert any(clave.startswith("ignore") for clave in cuerpo["field_patterns"])
    assert cuerpo["issuer_pattern"]


async def test_crear_una_plantilla_aprendida_de_una_factura(cliente):
    factura = await _factura_revisada(cliente)
    plantilla = await _crear_plantilla(cliente, factura["id"])

    assert plantilla["name"] == "Supermercado El Ahorro"
    assert plantilla["issuer_pattern"] == "EL AHORRO"
    assert plantilla["is_active"] is True
    assert plantilla["invoices_count"] == 0
    assert any(clave.startswith("ignore") for clave in plantilla["field_patterns"])


async def test_la_plantilla_aparece_en_el_listado_y_en_su_detalle(cliente):
    factura = await _factura_revisada(cliente)
    plantilla = await _crear_plantilla(cliente, factura["id"])

    listado = (await cliente.get("/api/v1/invoices/templates", params={"q": "ahorro"})).json()
    assert [fila["id"] for fila in listado["items"]] == [plantilla["id"]]

    detalle = await cliente.get(f"/api/v1/invoices/templates/{plantilla['id']}")
    assert detalle.status_code == 200
    assert detalle.json()["field_patterns"] == plantilla["field_patterns"]


async def test_editar_la_plantilla_cambia_las_reglas(cliente):
    factura = await _factura_revisada(cliente)
    plantilla = await _crear_plantilla(cliente, factura["id"])

    respuesta = await cliente.patch(
        f"/api/v1/invoices/templates/{plantilla['id']}",
        json={"field_patterns": {"total": r"TOTAL A PAGAR\s+(?P<valor>[\d.,]+)"}},
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["field_patterns"] == {"total": r"TOTAL A PAGAR\s+(?P<valor>[\d.,]+)"}


async def test_una_expresion_mal_escrita_se_rechaza_con_422_y_mensaje(cliente):
    factura = await _factura_revisada(cliente)
    plantilla = await _crear_plantilla(cliente, factura["id"])

    respuesta = await cliente.patch(
        f"/api/v1/invoices/templates/{plantilla['id']}", json={"field_patterns": {"total": "(("}}
    )
    assert respuesta.status_code == 422, respuesta.text
    assert "total" in respuesta.json()["error"]["mensaje"]


async def test_probar_la_plantilla_devuelve_lo_que_habria_leido_sin_guardar_nada(cliente):
    factura = await _factura_revisada(cliente)
    plantilla = await _crear_plantilla(cliente, factura["id"])

    respuesta = await cliente.post(
        f"/api/v1/invoices/templates/{plantilla['id']}/test",
        json={"invoice_id": factura["id"]},
    )
    assert respuesta.status_code == 200, respuesta.text
    prueba = respuesta.json()
    assert prueba["lines"], "la prueba tiene que decir qué líneas habría leído"
    # Nada de esto está guardado, así que no se puede confirmar desde aquí.
    assert prueba["can_confirm"] is False
    # Y las líneas guardadas de la factura no han cambiado.
    guardadas = (await cliente.get(f"/api/v1/invoices/{factura['id']}/lines")).json()
    assert {linea["id"] for linea in guardadas["lines"]}.isdisjoint(
        {linea["id"] for linea in prueba["lines"]}
    )


async def test_reprocesar_con_la_plantilla_la_deja_apuntada_y_cuenta_el_acierto(cliente, entorno):
    factura = await _factura_revisada(cliente)
    plantilla = await _crear_plantilla(cliente, factura["id"])

    respuesta = await cliente.post(
        f"/api/v1/invoices/{factura['id']}/reprocess",
        json={"template_id": plantilla["id"], "keep_edited": False},
    )
    assert respuesta.status_code == 202, respuesta.text

    detalle = (await cliente.get(f"/api/v1/invoices/{factura['id']}")).json()
    assert detalle["template_id"] == plantilla["id"]
    guardada = (await cliente.get(f"/api/v1/invoices/templates/{plantilla['id']}")).json()
    assert guardada["last_used_at"] is not None
    assert guardada["invoices_count"] == 1


async def test_borrar_la_plantilla_no_se_lleva_la_factura(cliente):
    factura = await _factura_revisada(cliente)
    plantilla = await _crear_plantilla(cliente, factura["id"])

    borrada = await cliente.delete(f"/api/v1/invoices/templates/{plantilla['id']}")
    assert borrada.status_code == 204
    assert (await cliente.get(f"/api/v1/invoices/templates/{plantilla['id']}")).status_code == 404
    assert (await cliente.get(f"/api/v1/invoices/{factura['id']}")).status_code == 200


async def test_la_plantilla_de_otro_hogar_no_existe(aplicacion, cliente):
    factura = await _factura_revisada(cliente)
    plantilla = await _crear_plantilla(cliente, factura["id"])

    ajena = await crear_entorno(email="bea", nombre="Casa de Bea")
    async with cliente_para(aplicacion, ajena.usuario_id) as otra:
        assert (await otra.get(f"/api/v1/invoices/templates/{plantilla['id']}")).status_code == 404
        assert (
            await otra.delete(f"/api/v1/invoices/templates/{plantilla['id']}")
        ).status_code == 404
        listado = (await otra.get("/api/v1/invoices/templates")).json()
        assert plantilla["id"] not in [fila["id"] for fila in listado["items"]]
