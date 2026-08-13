"""Pruebas de la normalización y agrupación de descripciones de producto."""

from decimal import Decimal

import pytest

from app.services.normalizacion import (
    clave_agrupacion,
    es_mismo_producto,
    mejor_coincidencia,
    normalizar_descripcion,
    similitud,
    sin_acentos,
)


class TestNormalizarDescripcion:
    def test_extrae_el_tamanyo_y_su_unidad(self):
        n = normalizar_descripcion("LECHE PASCUAL ENTERA 1L BRIK")
        assert n.tamanyo_valor == Decimal("1")
        assert n.tamanyo_unidad == "l"
        assert "pascual" in n.canonica
        assert "1l" not in n.canonica

    def test_tamanyo_en_gramos(self):
        n = normalizar_descripcion("CAFE MOLIDO NATURAL 250G")
        assert n.tamanyo_valor == Decimal("250")
        assert n.tamanyo_unidad == "g"

    def test_el_tamanyo_no_sale_en_notacion_cientifica(self):
        # Con Decimal.normalize() 250 se escribe "2.5E+2", y ese texto entra en
        # la clave de agrupación del producto.
        n = normalizar_descripcion("CAFE MOLIDO NATURAL 250G")
        assert n.tamanyo_texto == "250 g"
        assert "E+" not in clave_agrupacion(n)

    def test_multiplica_los_packs(self):
        n = normalizar_descripcion("CERVEZA 6X33CL")
        assert n.tamanyo_valor == Decimal("198")
        assert n.tamanyo_unidad == "cl"

    def test_extrae_el_codigo_de_barras(self):
        n = normalizar_descripcion("8410128750121 YOGUR NATURAL")
        assert n.codigo == "8410128750121"

    def test_quita_las_palabras_de_ruido(self):
        n = normalizar_descripcion("ART. 4021 DESCRIPCION: PAN INTEGRAL DTO")
        assert "descripcion" not in n.canonica
        assert "dto" not in n.canonica
        assert "pan" in n.canonica

    def test_sin_tildes_ni_mayusculas(self):
        n = normalizar_descripcion("MELOCOTÓN EN ALMÍBAR")
        # Se conservan las preposiciones de dos letras: no estorban al comparar
        # y quitarlas obligaría a mantener una lista de palabras vacías.
        assert n.canonica == "melocoton en almibar"

    def test_descripcion_sin_texto_util(self):
        n = normalizar_descripcion("4021")
        assert n.canonica  # nunca devuelve vacío: se queda con lo que haya


class TestClaveAgrupacion:
    def test_el_orden_de_las_palabras_no_importa(self):
        a = clave_agrupacion(normalizar_descripcion("LECHE PASCUAL ENTERA 1L"))
        b = clave_agrupacion(normalizar_descripcion("PASCUAL LECHE 1L ENTERA"))
        assert a == b

    def test_el_tamanyo_forma_parte_de_la_clave(self):
        litro = clave_agrupacion(normalizar_descripcion("LECHE PASCUAL 1L"))
        medio = clave_agrupacion(normalizar_descripcion("LECHE PASCUAL 500ML"))
        assert litro != medio

    def test_el_codigo_de_barras_manda(self):
        clave = clave_agrupacion(normalizar_descripcion("8410128750121 YOGUR"))
        assert clave.startswith("cod:")


class TestEsMismoProducto:
    def test_reconoce_la_misma_leche_escrita_de_dos_formas(self):
        a = normalizar_descripcion("LECHE PASCUAL 1L BRIK")
        b = normalizar_descripcion("Leche Pascual brik 1 l")
        assert es_mismo_producto(a, b)

    def test_distingue_tamanyos_distintos(self):
        a = normalizar_descripcion("LECHE PASCUAL 1L")
        b = normalizar_descripcion("LECHE PASCUAL 500ML")
        assert not es_mismo_producto(a, b)

    def test_el_codigo_de_barras_es_definitivo(self):
        a = normalizar_descripcion("8410128750121 YOGUR NATURAL")
        b = normalizar_descripcion("8410128750121 OTRO NOMBRE DISTINTO")
        assert es_mismo_producto(a, b)

    def test_codigos_distintos_no_son_el_mismo_producto(self):
        a = normalizar_descripcion("8410128750121 YOGUR NATURAL")
        b = normalizar_descripcion("8410128750999 YOGUR NATURAL")
        assert not es_mismo_producto(a, b)

    def test_productos_diferentes(self):
        a = normalizar_descripcion("ACEITE OLIVA VIRGEN EXTRA 1L")
        b = normalizar_descripcion("VINAGRE DE MODENA 500ML")
        assert not es_mismo_producto(a, b)


class TestSimilitud:
    def test_identicas(self):
        assert similitud("leche pascual", "leche pascual") == 100

    def test_una_vacia(self):
        assert similitud("", "leche") == 0.0

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("leche pascual entera", "leche pascual"),
            ("aceite oliva virgen extra", "aceite de oliva virgen extra"),
        ],
    )
    def test_parecidas_superan_el_umbral(self, a, b):
        assert similitud(a, b) >= 88


class TestMejorCoincidencia:
    def test_encuentra_el_candidato_mas_parecido(self):
        candidatos = {
            "p1": "leche pascual entera brik",
            "p2": "aceite oliva virgen extra",
            "p3": "pan molde integral",
        }
        resultado = mejor_coincidencia("leche pascual brik", candidatos)
        assert resultado is not None
        assert resultado[0] == "p1"

    def test_devuelve_none_si_nada_se_parece(self):
        candidatos = {"p1": "aceite oliva", "p2": "pan integral"}
        assert mejor_coincidencia("destornillador de estrella", candidatos) is None

    def test_sin_candidatos(self):
        assert mejor_coincidencia("leche", {}) is None


class TestSinAcentos:
    def test_quita_las_tildes(self):
        assert sin_acentos("ENERGÍA IBÉRICA") == "ENERGIA IBERICA"

    def test_conserva_la_enye(self):
        # La ñ se descompone en n + tilde, y aquí se pierde la tilde: es el
        # comportamiento buscado para poder comparar "ALBÓNDIGAS"/"ALBONDIGAS".
        assert sin_acentos("PIÑA") == "PINA"
