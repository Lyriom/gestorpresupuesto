"""Pruebas del análisis de historial de precios."""

from datetime import date
from decimal import Decimal

from app.services.precios import (
    LineaCesta,
    PuntoPrecio,
    Tendencia,
    analizar_historial,
    comparar_cesta,
    comparar_comercios,
    detectar_subidas,
    inflacion_personal,
    variacion,
)


def punto(dia: int, precio: str, comercio: str | None = None) -> PuntoPrecio:
    return PuntoPrecio(fecha=date(2026, 8, dia), precio=Decimal(precio), comercio=comercio)


class TestVariacion:
    def test_subida(self):
        assert variacion(Decimal("1.00"), Decimal("1.08")) == Decimal("0.0800")

    def test_bajada(self):
        assert variacion(Decimal("2.00"), Decimal("1.50")) == Decimal("-0.2500")

    def test_sin_cambio(self):
        assert variacion(Decimal("1.15"), Decimal("1.15")) == Decimal("0.0000")

    def test_precio_anterior_cero(self):
        assert variacion(Decimal("0"), Decimal("1.00")) is None


class TestAnalizarHistorial:
    def test_historial_vacio(self):
        analisis = analizar_historial([])
        assert analisis.observaciones == 0
        assert analisis.tendencia is Tendencia.SIN_DATOS
        assert analisis.precio_actual is None
        assert not analisis.hay_alerta

    def test_una_sola_observacion_no_da_tendencia(self):
        analisis = analizar_historial([punto(1, "1.15")])
        assert analisis.observaciones == 1
        assert analisis.precio_actual == Decimal("1.15")
        assert analisis.precio_anterior is None
        assert analisis.variacion_ultima is None
        assert analisis.tendencia is Tendencia.SIN_DATOS

    def test_detecta_subida_y_avisa(self):
        analisis = analizar_historial([punto(1, "1.15"), punto(20, "1.35")])
        assert analisis.tendencia is Tendencia.SUBE
        assert analisis.variacion_ultima == Decimal("0.1739")
        assert analisis.hay_alerta
        assert analisis.mensaje_alerta is not None
        assert "17.39 %" in analisis.mensaje_alerta

    def test_una_bajada_no_genera_alerta(self):
        analisis = analizar_historial([punto(1, "2.00"), punto(20, "1.50")])
        assert analisis.tendencia is Tendencia.BAJA
        assert not analisis.hay_alerta

    def test_un_cambio_minimo_es_estable(self):
        analisis = analizar_historial([punto(1, "1.00"), punto(20, "1.003")])
        assert analisis.tendencia is Tendencia.ESTABLE
        assert not analisis.hay_alerta

    def test_subida_pequenya_no_supera_el_umbral_de_alerta(self):
        analisis = analizar_historial([punto(1, "1.00"), punto(20, "1.02")])
        assert analisis.tendencia is Tendencia.SUBE  # sube, pero poco
        assert not analisis.hay_alerta

    def test_ordena_los_puntos_desordenados(self):
        analisis = analizar_historial([punto(20, "1.35"), punto(1, "1.15"), punto(10, "1.20")])
        assert analisis.precio_actual == Decimal("1.35")
        assert analisis.precio_anterior == Decimal("1.20")
        assert analisis.fecha_actual == date(2026, 8, 20)

    def test_estadisticas_del_periodo(self):
        analisis = analizar_historial(
            [punto(1, "1.00"), punto(5, "2.00"), punto(10, "1.50"), punto(15, "1.50")]
        )
        assert analisis.precio_minimo == Decimal("1.00")
        assert analisis.precio_maximo == Decimal("2.00")
        assert analisis.precio_medio == Decimal("1.5000")
        assert analisis.fecha_minimo == date(2026, 8, 1)
        assert analisis.fecha_maximo == date(2026, 8, 5)
        assert analisis.variacion_total == Decimal("0.5000")

    def test_ignora_precios_no_validos(self):
        puntos = [punto(1, "1.15"), PuntoPrecio(date(2026, 8, 5), Decimal("0")), punto(10, "1.20")]
        analisis = analizar_historial(puntos)
        assert analisis.observaciones == 2

    def test_umbral_de_alerta_configurable(self):
        puntos = [punto(1, "1.00"), punto(10, "1.03")]
        assert not analizar_historial(puntos).hay_alerta
        assert analizar_historial(puntos, umbral_alerta=Decimal("0.02")).hay_alerta


class TestComparativaEntreComercios:
    def test_usa_el_ultimo_precio_de_cada_comercio(self):
        puntos = [
            punto(1, "1.20", "Mercadona"),
            punto(15, "1.10", "Mercadona"),
            punto(10, "1.35", "Carrefour"),
        ]
        comparativa = comparar_comercios(puntos)
        assert [c.comercio for c in comparativa] == ["Mercadona", "Carrefour"]
        assert comparativa[0].precio == Decimal("1.10")
        assert comparativa[0].observaciones == 2

    def test_calcula_el_ahorro_frente_al_mas_barato(self):
        puntos = [punto(1, "1.10", "Mercadona"), punto(20, "1.45", "Carrefour")]
        analisis = analizar_historial(puntos)
        assert analisis.comercio_mas_barato == "Mercadona"
        assert analisis.ahorro_por_unidad == Decimal("0.3500")

    def test_sin_ahorro_si_ya_compras_en_el_mas_barato(self):
        puntos = [punto(1, "1.45", "Carrefour"), punto(20, "1.10", "Mercadona")]
        analisis = analizar_historial(puntos)
        assert analisis.comercio_mas_barato == "Mercadona"
        assert analisis.ahorro_por_unidad is None

    def test_ignora_puntos_sin_comercio(self):
        assert comparar_comercios([punto(1, "1.10")]) == []


class TestDetectarSubidas:
    def test_ordena_de_mayor_a_menor_subida(self):
        historiales = {
            "p1": ("Aceite de oliva", [punto(1, "9.00"), punto(20, "11.50")]),
            "p2": ("Leche", [punto(1, "1.00"), punto(20, "1.08")]),
            "p3": ("Pan", [punto(1, "1.00"), punto(20, "1.01")]),
            "p4": ("Huevos", [punto(1, "3.00"), punto(20, "2.50")]),
        }
        subidas = detectar_subidas(historiales)
        assert [s.producto_id for s in subidas] == ["p1", "p2"]
        assert subidas[0].nombre == "Aceite de oliva"
        assert subidas[0].porcentaje == Decimal("27.78")

    def test_sin_subidas_devuelve_lista_vacia(self):
        historiales = {"p1": ("Pan", [punto(1, "1.00"), punto(20, "1.00")])}
        assert detectar_subidas(historiales) == []

    def test_conserva_el_comercio_de_la_ultima_compra(self):
        historiales = {
            "p1": ("Aceite", [punto(1, "9.00", "Mercadona"), punto(20, "11.50", "Carrefour")])
        }
        assert detectar_subidas(historiales)[0].comercio == "Carrefour"


class TestComparativaDeCesta:
    def test_suma_la_cesta_por_comercio(self):
        lineas = [
            LineaCesta(
                "p1",
                "Leche 1L",
                Decimal("6"),
                {"Mercadona": Decimal("1.10"), "Carrefour": Decimal("1.20")},
            ),
            LineaCesta(
                "p2",
                "Aceite 1L",
                Decimal("2"),
                {"Mercadona": Decimal("9.50"), "Carrefour": Decimal("8.90")},
            ),
        ]
        comparativa = comparar_cesta(lineas)
        # Mercadona: 6 x 1,10 + 2 x 9,50 = 25,60. Carrefour: 6 x 1,20 + 2 x 8,90 = 25,00.
        assert comparativa.totales["Mercadona"] == Decimal("25.60")
        assert comparativa.totales["Carrefour"] == Decimal("25.00")
        assert comparativa.mas_barato == "Carrefour"
        assert comparativa.ahorro_maximo == Decimal("0.60")

    def test_marca_los_comercios_con_precios_incompletos(self):
        lineas = [
            LineaCesta(
                "p1",
                "Leche 1L",
                Decimal("1"),
                {"Mercadona": Decimal("1.10"), "Lidl": Decimal("1.00")},
            ),
            LineaCesta("p2", "Aceite 1L", Decimal("1"), {"Mercadona": Decimal("9.50")}),
        ]
        comparativa = comparar_cesta(lineas)
        assert comparativa.incompletos["Lidl"] == ["Aceite 1L"]
        # Lidl sale más bajo porque le falta el aceite, así que no debe ganar.
        assert comparativa.mas_barato == "Mercadona"

    def test_linea_conoce_su_comercio_mas_barato(self):
        linea = LineaCesta(
            "p1", "Leche", Decimal("1"), {"Mercadona": Decimal("1.10"), "Lidl": Decimal("0.95")}
        )
        assert linea.comercio_mas_barato == "Lidl"

    def test_cesta_vacia(self):
        comparativa = comparar_cesta([])
        assert comparativa.totales == {}
        assert comparativa.mas_barato is None
        assert comparativa.ahorro_maximo == Decimal("0.00")


class TestInflacionPersonal:
    def test_media_de_las_variaciones(self):
        historiales = [
            [
                PuntoPrecio(date(2026, 1, 5), Decimal("1.00")),
                PuntoPrecio(date(2026, 8, 5), Decimal("1.10")),
            ],
            [
                PuntoPrecio(date(2026, 1, 5), Decimal("2.00")),
                PuntoPrecio(date(2026, 8, 5), Decimal("2.40")),
            ],
        ]
        resultado = inflacion_personal(historiales, date(2026, 2, 1), date(2026, 12, 31))
        # +10 % y +20 % -> 15 %
        assert resultado == Decimal("0.1500")

    def test_ignora_productos_sin_observacion_previa(self):
        historiales = [[PuntoPrecio(date(2026, 8, 5), Decimal("1.10"))]]
        assert inflacion_personal(historiales, date(2026, 2, 1), date(2026, 12, 31)) is None

    def test_sin_datos_devuelve_none(self):
        assert inflacion_personal([], date(2026, 1, 1), date(2026, 12, 31)) is None
