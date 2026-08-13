"""Pruebas de la auto-categorización por reglas."""

from decimal import Decimal

import pytest

from app.services.reglas import (
    Asignacion,
    Campo,
    Condicion,
    ErrorRegla,
    MovimientoEvaluable,
    Operador,
    Regla,
    aplicar_a_lote,
    aplicar_reglas,
    normalizar,
    sugerir_regla,
)


def regla(
    nombre: str,
    condiciones: list[Condicion],
    categoria: str = "cat",
    prioridad: int = 100,
    **kwargs,
) -> Regla:
    return Regla(
        regla_id=nombre,
        nombre=nombre,
        condiciones=condiciones,
        categoria_id=categoria,
        prioridad=prioridad,
        **kwargs,
    )


class TestNormalizar:
    def test_quita_tildes_y_mayusculas(self):
        assert normalizar("ALIMENTACIÓN") == "alimentacion"

    def test_colapsa_espacios(self):
        assert normalizar("  MERCADONA   4021  ") == "mercadona 4021"

    def test_texto_vacio(self):
        assert normalizar(None) == ""
        assert normalizar("") == ""


class TestCondicionesDeTexto:
    @pytest.mark.parametrize(
        ("operador", "valor", "esperado"),
        [
            (Operador.CONTIENE, "mercadona", True),
            (Operador.CONTIENE, "carrefour", False),
            (Operador.NO_CONTIENE, "carrefour", True),
            (Operador.EMPIEZA_POR, "compra", True),
            (Operador.EMPIEZA_POR, "mercadona", False),
            (Operador.TERMINA_EN, "4021", True),
            (Operador.ES_IGUAL, "COMPRA MERCADONA 4021", True),
            (Operador.COINCIDE_REGEX, r"mercadona\s+\d+", True),
        ],
    )
    def test_operadores(self, operador, valor, esperado):
        condicion = Condicion(Campo.DESCRIPCION, operador, valor)
        movimiento = MovimientoEvaluable(descripcion="COMPRA MERCADONA 4021")
        assert condicion.evaluar(movimiento) is esperado

    def test_compara_sin_tildes(self):
        condicion = Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "farmacia")
        assert condicion.evaluar(MovimientoEvaluable(descripcion="FARMÀCIA DEL CARME"))

    def test_campo_comercio(self):
        condicion = Condicion(Campo.COMERCIO, Operador.ES_IGUAL, "Netflix")
        assert condicion.evaluar(MovimientoEvaluable(comercio="netflix"))

    def test_texto_ausente_no_coincide(self):
        condicion = Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "mercadona")
        assert not condicion.evaluar(MovimientoEvaluable())

    def test_regex_invalida(self):
        with pytest.raises(ErrorRegla, match="expresión regular"):
            Condicion(Campo.DESCRIPCION, Operador.COINCIDE_REGEX, "[sin cerrar")


class TestCondicionesDeImporte:
    def test_mayor_que(self):
        condicion = Condicion(Campo.IMPORTE, Operador.MAYOR_QUE, "50")
        assert condicion.evaluar(MovimientoEvaluable(importe=Decimal("75")))
        assert not condicion.evaluar(MovimientoEvaluable(importe=Decimal("25")))

    def test_usa_el_valor_absoluto(self):
        condicion = Condicion(Campo.IMPORTE, Operador.MAYOR_QUE, "50")
        # Un gasto se guarda en negativo pero el usuario piensa en positivo.
        assert condicion.evaluar(MovimientoEvaluable(importe=Decimal("-75")))

    def test_entre(self):
        condicion = Condicion(Campo.IMPORTE, Operador.ENTRE, "10", "20")
        assert condicion.evaluar(MovimientoEvaluable(importe=Decimal("15")))
        assert condicion.evaluar(MovimientoEvaluable(importe=Decimal("10")))
        assert not condicion.evaluar(MovimientoEvaluable(importe=Decimal("25")))

    def test_entre_con_los_valores_invertidos(self):
        condicion = Condicion(Campo.IMPORTE, Operador.ENTRE, "20", "10")
        assert condicion.evaluar(MovimientoEvaluable(importe=Decimal("15")))

    def test_acepta_la_coma_decimal(self):
        condicion = Condicion(Campo.IMPORTE, Operador.MENOR_QUE, "10,50")
        assert condicion.evaluar(MovimientoEvaluable(importe=Decimal("10")))

    def test_sin_importe_no_coincide(self):
        condicion = Condicion(Campo.IMPORTE, Operador.MAYOR_QUE, "50")
        assert not condicion.evaluar(MovimientoEvaluable())

    def test_entre_necesita_dos_valores(self):
        with pytest.raises(ErrorRegla, match="dos valores"):
            Condicion(Campo.IMPORTE, Operador.ENTRE, "10")


class TestValidacionDeCondiciones:
    def test_no_se_puede_usar_texto_sobre_el_importe(self):
        with pytest.raises(ErrorRegla, match="sobre el importe"):
            Condicion(Campo.IMPORTE, Operador.CONTIENE, "50")

    def test_no_se_puede_usar_numerico_sobre_texto(self):
        with pytest.raises(ErrorRegla, match="solo se puede usar sobre el importe"):
            Condicion(Campo.DESCRIPCION, Operador.MAYOR_QUE, "50")

    def test_valor_obligatorio(self):
        with pytest.raises(ErrorRegla, match="necesita un valor"):
            Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "   ")


class TestValidacionDeReglas:
    def test_necesita_condiciones(self):
        with pytest.raises(ErrorRegla, match="al menos una condición"):
            Regla(regla_id="r", nombre="r", condiciones=[], categoria_id="cat")

    def test_necesita_asignar_algo(self):
        with pytest.raises(ErrorRegla, match="asignar algo"):
            Regla(
                regla_id="r",
                nombre="r",
                condiciones=[Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "x")],
            )


class TestCombinacionDeCondiciones:
    def test_exige_todas_por_defecto(self):
        r = regla(
            "Súper caro",
            [
                Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "mercadona"),
                Condicion(Campo.IMPORTE, Operador.MAYOR_QUE, "100"),
            ],
        )
        assert r.coincide(MovimientoEvaluable("COMPRA MERCADONA", importe=Decimal("150")))
        assert not r.coincide(MovimientoEvaluable("COMPRA MERCADONA", importe=Decimal("20")))

    def test_puede_exigir_solo_una(self):
        r = regla(
            "Súper",
            [
                Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "mercadona"),
                Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "carrefour"),
            ],
            exigir_todas=False,
        )
        assert r.coincide(MovimientoEvaluable("COMPRA CARREFOUR"))

    def test_una_regla_inactiva_nunca_coincide(self):
        r = regla(
            "Desactivada",
            [Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "mercadona")],
            activa=False,
        )
        assert not r.coincide(MovimientoEvaluable("MERCADONA"))


class TestAplicarReglas:
    def test_devuelve_la_asignacion(self):
        reglas = [
            regla(
                "Súper",
                [Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "mercadona")],
                categoria="alimentacion",
            )
        ]
        asignacion = aplicar_reglas(MovimientoEvaluable("COMPRA MERCADONA 4021"), reglas)
        assert isinstance(asignacion, Asignacion)
        assert asignacion.categoria_id == "alimentacion"
        assert asignacion.nombre_regla == "Súper"

    def test_gana_la_de_mayor_prioridad(self):
        reglas = [
            regla(
                "Genérica",
                [Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "compra")],
                categoria="varios",
                prioridad=100,
            ),
            regla(
                "Específica",
                [Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "mercadona")],
                categoria="alimentacion",
                prioridad=10,
            ),
        ]
        asignacion = aplicar_reglas(MovimientoEvaluable("COMPRA MERCADONA"), reglas)
        assert asignacion.categoria_id == "alimentacion"

    def test_sin_coincidencia_devuelve_none(self):
        reglas = [regla("Súper", [Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "mercadona")])]
        assert aplicar_reglas(MovimientoEvaluable("GASOLINERA REPSOL"), reglas) is None

    def test_sin_reglas_devuelve_none(self):
        assert aplicar_reglas(MovimientoEvaluable("MERCADONA"), []) is None

    def test_arrastra_las_etiquetas(self):
        reglas = [
            Regla(
                regla_id="r",
                nombre="Viaje",
                condiciones=[Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "renfe")],
                categoria_id="transporte",
                etiquetas=["viaje", "trabajo"],
            )
        ]
        asignacion = aplicar_reglas(MovimientoEvaluable("BILLETE RENFE AVE"), reglas)
        assert asignacion.etiquetas == ["viaje", "trabajo"]

    def test_lote_mantiene_el_orden(self):
        reglas = [
            regla(
                "Súper",
                [Condicion(Campo.DESCRIPCION, Operador.CONTIENE, "mercadona")],
                categoria="alimentacion",
            )
        ]
        movimientos = [
            MovimientoEvaluable("MERCADONA"),
            MovimientoEvaluable("REPSOL"),
            MovimientoEvaluable("MERCADONA 2"),
        ]
        resultados = aplicar_a_lote(movimientos, reglas)
        assert [r.categoria_id if r else None for r in resultados] == [
            "alimentacion",
            None,
            "alimentacion",
        ]


class TestSugerirRegla:
    def test_descarta_los_numeros_de_operacion(self):
        propuesta = sugerir_regla("COMPRA 4021 MERCADONA SA 28013", "alimentacion")
        condicion = propuesta.condiciones[0]
        assert condicion.valor == "mercadona"
        assert propuesta.categoria_id == "alimentacion"

    def test_elige_la_palabra_mas_distintiva(self):
        propuesta = sugerir_regla("PAGO CON TARJETA EN GASOLINERA REPSOL SUR", "transporte")
        assert propuesta.condiciones[0].valor == "gasolinera"

    def test_falla_si_no_hay_texto_estable(self):
        with pytest.raises(ErrorRegla, match="texto estable"):
            sugerir_regla("4021 2026 28013", "alimentacion")

    def test_la_regla_sugerida_coincide_con_el_movimiento_original(self):
        descripcion = "COMPRA 4021 MERCADONA SA"
        propuesta = sugerir_regla(descripcion, "alimentacion")
        assert propuesta.coincide(MovimientoEvaluable(descripcion=descripcion))
