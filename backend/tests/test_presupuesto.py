"""Pruebas del cálculo de la barra de presupuesto."""

from decimal import Decimal

import pytest

from app.services.presupuesto import (
    EntradaCategoria,
    ErrorPresupuesto,
    EstadoSegmento,
    calcular_arrastre,
    calcular_barra,
    periodo_anterior,
    periodo_siguiente,
    reasignar,
    reparto_sugerido,
    validar_asignacion,
    validar_periodo,
)


def entrada(
    nombre: str,
    asignado: str,
    gastado: str = "0",
    *,
    arrastrado: str = "0",
    permite_arrastre: bool = False,
) -> EntradaCategoria:
    return EntradaCategoria(
        categoria_id=nombre.lower(),
        nombre=nombre,
        asignado=Decimal(asignado),
        gastado=Decimal(gastado),
        arrastrado=Decimal(arrastrado),
        permite_arrastre=permite_arrastre,
    )


class TestPeriodos:
    def test_valida_el_formato(self):
        assert validar_periodo("2026-08") == "2026-08"

    @pytest.mark.parametrize("malo", ["2026-13", "2026-00", "26-08", "2026/08", "", "agosto"])
    def test_rechaza_periodos_invalidos(self, malo):
        with pytest.raises(ErrorPresupuesto):
            validar_periodo(malo)

    def test_navega_entre_meses(self):
        assert periodo_anterior("2026-08") == "2026-07"
        assert periodo_siguiente("2026-08") == "2026-09"

    def test_cruza_el_cambio_de_anyo(self):
        assert periodo_anterior("2026-01") == "2025-12"
        assert periodo_siguiente("2026-12") == "2027-01"


class TestBarraDePresupuesto:
    def test_mes_sin_nada(self):
        barra = calcular_barra("2026-08", 0, [])
        assert barra.ingresos == Decimal("0.00")
        assert barra.segmentos == []
        assert barra.avisos  # avisa de que faltan los ingresos

    def test_reparto_completo(self):
        barra = calcular_barra(
            "2026-08",
            "2000",
            [
                entrada("Vivienda", "800"),
                entrada("Alimentación", "400"),
                entrada("Transporte", "150"),
            ],
        )
        assert barra.total_asignado == Decimal("1350.00")
        assert barra.sin_asignar == Decimal("650.00")
        assert not barra.sobreasignado
        assert barra.porcentaje_asignado == Decimal("67.50")

    def test_ordena_los_segmentos_por_asignacion(self):
        barra = calcular_barra(
            "2026-08",
            "1000",
            [entrada("Ocio", "100"), entrada("Vivienda", "600"), entrada("Comida", "300")],
        )
        assert [s.nombre for s in barra.segmentos] == ["Vivienda", "Comida", "Ocio"]

    def test_anchura_de_los_segmentos_sobre_los_ingresos(self):
        barra = calcular_barra("2026-08", "1000", [entrada("Vivienda", "250")])
        assert barra.segmentos[0].porcentaje_de_la_barra == Decimal("25.00")

    def test_una_devolucion_mayor_que_el_gasto_del_mes_no_pinta_en_negativo(self):
        """Se compró el abrigo en julio y se devolvió en agosto.

        Lo gastado del mes es negativo, y así hay que enseñarlo: es dinero que ha
        vuelto. Pero el segmento se dibuja con el porcentaje consumido, y una
        anchura negativa no significa nada; además el esquema de la API lo
        rechazaba y tumbaba la pantalla entera del presupuesto con un 500.
        """
        barra = calcular_barra("2026-08", "1000", [entrada("Ropa", "150", "-130")])
        segmento = barra.segmentos[0]

        assert segmento.gastado == Decimal("-130.00")
        assert segmento.porcentaje_consumido == Decimal("0.00")
        assert segmento.disponible == Decimal("280.00")
        assert segmento.sobrepaso == Decimal("0.00")

    def test_si_se_reparte_mas_de_lo_que_entra_la_barra_no_desborda(self):
        barra = calcular_barra(
            "2026-08", "1000", [entrada("Vivienda", "800"), entrada("Ocio", "600")]
        )
        assert barra.sobreasignado
        assert barra.sin_asignar == Decimal("-400.00")
        # La suma de anchuras sigue siendo 100 %: se calcula sobre lo asignado.
        suma = sum(s.porcentaje_de_la_barra for s in barra.segmentos)
        assert suma == Decimal("100.00")
        assert any("más de lo que has ingresado" in aviso for aviso in barra.avisos)

    def test_estados_de_las_categorias(self):
        barra = calcular_barra(
            "2026-08",
            "1000",
            [
                entrada("Sin gasto", "100", "0"),
                entrada("En margen", "100", "50"),
                entrada("Ajustado", "100", "85"),
                entrada("Agotado", "100", "100"),
                entrada("Sobrepasado", "100", "130"),
                entrada("Sin asignar", "0", "40"),
            ],
        )
        estados = {s.nombre: s.estado for s in barra.segmentos}
        assert estados["Sin gasto"] is EstadoSegmento.SIN_GASTO
        assert estados["En margen"] is EstadoSegmento.EN_MARGEN
        assert estados["Ajustado"] is EstadoSegmento.AJUSTADO
        assert estados["Agotado"] is EstadoSegmento.AGOTADO
        assert estados["Sobrepasado"] is EstadoSegmento.SOBREPASADO
        assert estados["Sin asignar"] is EstadoSegmento.SIN_ASIGNAR

    def test_calcula_el_sobrepaso(self):
        barra = calcular_barra("2026-08", "1000", [entrada("Ocio", "100", "130")])
        segmento = barra.segmentos[0]
        assert segmento.disponible == Decimal("-30.00")
        assert segmento.sobrepaso == Decimal("30.00")
        assert segmento.porcentaje_consumido == Decimal("130.00")
        assert any("Te has pasado 30,00 € en Ocio" in aviso for aviso in barra.avisos)

    def test_avisa_de_varias_categorias_sobrepasadas(self):
        barra = calcular_barra(
            "2026-08", "1000", [entrada("Ocio", "100", "130"), entrada("Comida", "200", "250")]
        )
        assert len(barra.categorias_sobrepasadas) == 2
        assert any("en 2 temáticas" in aviso for aviso in barra.avisos)

    def test_avisa_de_gasto_sin_presupuesto(self):
        barra = calcular_barra("2026-08", "1000", [entrada("Imprevistos", "0", "75")])
        assert any("sin presupuesto asignado" in aviso for aviso in barra.avisos)

    def test_el_arrastre_amplia_el_presupuesto_disponible(self):
        barra = calcular_barra(
            "2026-08",
            "1000",
            [entrada("Vacaciones", "100", "150", arrastrado="200", permite_arrastre=True)],
        )
        segmento = barra.segmentos[0]
        assert segmento.arrastrado == Decimal("200.00")
        assert segmento.presupuesto_efectivo == Decimal("300.00")
        assert segmento.disponible == Decimal("150.00")
        assert segmento.estado is EstadoSegmento.EN_MARGEN
        assert barra.total_arrastrado == Decimal("200.00")

    def test_el_arrastre_se_ignora_si_la_categoria_no_lo_permite(self):
        barra = calcular_barra(
            "2026-08",
            "1000",
            [entrada("Ocio", "100", "150", arrastrado="200", permite_arrastre=False)],
        )
        assert barra.segmentos[0].arrastrado == Decimal("0.00")
        assert barra.segmentos[0].estado is EstadoSegmento.SOBREPASADO
        assert barra.total_arrastrado == Decimal("0.00")

    def test_disponible_global(self):
        barra = calcular_barra(
            "2026-08", "2000", [entrada("Vivienda", "800", "800"), entrada("Comida", "400", "250")]
        )
        assert barra.total_gastado == Decimal("1050.00")
        assert barra.disponible == Decimal("950.00")

    def test_acepta_importes_como_texto_o_numero(self):
        barra = calcular_barra("2026-08", 1500.5, [entrada("Casa", "500")])
        assert barra.ingresos == Decimal("1500.50")


class TestReasignar:
    def test_mueve_presupuesto_entre_tematicas(self):
        resultado = reasignar("ocio", "200", "comida", "300", "50")
        assert resultado.asignado_origen == Decimal("150.00")
        assert resultado.asignado_destino == Decimal("350.00")
        assert resultado.importe == Decimal("50.00")

    def test_no_permite_el_mismo_origen_y_destino(self):
        with pytest.raises(ErrorPresupuesto, match="misma temática"):
            reasignar("ocio", "200", "ocio", "200", "50")

    def test_no_permite_importes_no_positivos(self):
        with pytest.raises(ErrorPresupuesto, match="mayor que cero"):
            reasignar("ocio", "200", "comida", "300", "0")
        with pytest.raises(ErrorPresupuesto, match="mayor que cero"):
            reasignar("ocio", "200", "comida", "300", "-10")

    def test_no_permite_mover_mas_de_lo_asignado(self):
        with pytest.raises(ErrorPresupuesto, match="solo tiene"):
            reasignar("ocio", "200", "comida", "300", "250")

    def test_no_deja_el_origen_por_debajo_de_lo_ya_gastado(self):
        with pytest.raises(ErrorPresupuesto, match="Solo puedes mover 50.00"):
            reasignar("ocio", "200", "comida", "300", "100", gastado_origen="150")

    def test_permite_mover_justo_hasta_lo_gastado(self):
        resultado = reasignar("ocio", "200", "comida", "300", "50", gastado_origen="150")
        assert resultado.asignado_origen == Decimal("150.00")


class TestArrastre:
    def test_sin_arrastre_no_pasa_nada_al_mes_siguiente(self):
        assert calcular_arrastre("100", "60", permite_arrastre=False) == Decimal("0.00")

    def test_arrastra_el_sobrante(self):
        assert calcular_arrastre("100", "60", permite_arrastre=True) == Decimal("40.00")

    def test_acumula_el_arrastre_previo(self):
        assert calcular_arrastre("100", "60", "30", permite_arrastre=True) == Decimal("70.00")

    def test_arrastra_la_deuda_en_negativo(self):
        assert calcular_arrastre("100", "130", permite_arrastre=True) == Decimal("-30.00")

    def test_puede_no_arrastrar_la_deuda(self):
        arrastre = calcular_arrastre("100", "130", permite_arrastre=True, arrastrar_deuda=False)
        assert arrastre == Decimal("0.00")


class TestValidarAsignacion:
    def test_acepta_cero_y_positivos(self):
        assert validar_asignacion("0") == Decimal("0.00")
        assert validar_asignacion("125.5") == Decimal("125.50")

    def test_rechaza_negativos(self):
        with pytest.raises(ErrorPresupuesto, match="no puede ser negativo"):
            validar_asignacion("-1")


class TestRepartoSugerido:
    def test_respeta_la_media_si_cabe_en_los_ingresos(self):
        propuesta = reparto_sugerido("2000", {"vivienda": Decimal("800"), "comida": Decimal("400")})
        assert propuesta == {"vivienda": Decimal("800.00"), "comida": Decimal("400.00")}

    def test_escala_proporcionalmente_si_no_cabe(self):
        propuesta = reparto_sugerido("1000", {"vivienda": Decimal("800"), "comida": Decimal("400")})
        assert sum(propuesta.values()) == Decimal("1000.00")
        # Se mantiene la proporción 2:1 entre las dos temáticas.
        assert propuesta["vivienda"] == Decimal("666.67")
        assert propuesta["comida"] == Decimal("333.33")

    def test_sin_ingresos_no_propone_nada(self):
        propuesta = reparto_sugerido("0", {"vivienda": Decimal("800")})
        assert propuesta == {"vivienda": Decimal("0.00")}

    def test_sin_historico_devuelve_vacio(self):
        assert reparto_sugerido("1000", {}) == {}
