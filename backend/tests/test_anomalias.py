"""Pruebas de la detección de gasto inusual (F-48).

La mayoría son casos límite a propósito: una detección de anomalías que avisa de
lo que no toca es peor que no tenerla, porque el usuario aprende a ignorar la
bandeja de avisos. Aquí se fija exactamente cuándo **no** se avisa.
"""

from decimal import Decimal

from app.services import anomalias
from app.services.anomalias import Ambito, Gasto, Grupo

ALIMENTACION = Grupo(ambito=Ambito.TEMATICA, clave="c-1", nombre="Alimentación")
HOGAR = Grupo(ambito=Ambito.TEMATICA, clave="c-2", nombre="Hogar")
SUPERMERCADO = Grupo(ambito=Ambito.COMERCIO, clave="p-1", nombre="Mercadona")
MUEBLES = Grupo(ambito=Ambito.COMERCIO, clave="p-2", nombre="Muebles del Norte")
NOMINA = Grupo(ambito=Ambito.TEMATICA, clave="c-9", nombre="Nómina")


def euros(cantidad: str) -> Decimal:
    return Decimal(cantidad)


def serie(importes: list[str], grupo: Grupo = ALIMENTACION, **extra) -> list[Gasto]:
    """Un historial de gastos en un mismo grupo, con identificadores distintos."""
    return [
        Gasto(identificador=f"g{indice}", importe=euros(importe), tematica=grupo, **extra)
        for indice, importe in enumerate(importes)
    ]


# --------------------------------------------------------------------------- #
# Estadística robusta
# --------------------------------------------------------------------------- #


class TestEstadistica:
    def test_la_mediana_impar_es_el_valor_central(self):
        assert anomalias.mediana([euros("1"), euros("50"), euros("3")]) == euros("3")

    def test_la_mediana_par_es_la_media_de_los_dos_centrales(self):
        valores = [euros("10"), euros("20"), euros("30"), euros("40")]
        assert anomalias.mediana(valores) == euros("25")

    def test_la_mediana_de_una_lista_vacia_es_cero(self):
        assert anomalias.mediana([]) == Decimal("0")
        assert anomalias.desviacion_absoluta_mediana([]) == Decimal("0")

    def test_la_mad_es_la_mediana_de_las_distancias(self):
        # Mediana 30; distancias 20, 10, 0, 10, 20 -> mediana 10.
        valores = [euros("10"), euros("20"), euros("30"), euros("40"), euros("50")]
        assert anomalias.desviacion_absoluta_mediana(valores) == euros("10")

    def test_la_mad_aguanta_el_valor_extremo_y_la_desviacion_tipica_no(self):
        """La razón de ser del módulo, comprobada con números.

        Veinte compras de 40 € y un televisor de 900 €: la desviación típica se
        dispara por culpa del propio valor que hay que detectar, así que deja de
        detectarlo; la MAD ni se mueve.
        """
        importes = [euros("40")] * 20 + [euros("900")]
        referencia = anomalias.referencia_de(ALIMENTACION, importes)

        assert referencia.mediana == euros("40.00")
        assert referencia.mad == euros("0.00")
        # La media y la desviación típica están arrastradas por el televisor.
        assert referencia.media > euros("70")
        assert referencia.desviacion_tipica > euros("150")
        # Con la desviación típica el televisor sale a menos de media sigma: no
        # habría avisado. Con la dispersión robusta, a muchísimas más.
        z_clasico = (euros("900") - referencia.media) / referencia.desviacion_tipica
        z_robusto = (euros("900") - referencia.mediana) / referencia.dispersion
        assert z_clasico < Decimal("5")
        assert z_robusto > Decimal("100")


# --------------------------------------------------------------------------- #
# Referencias
# --------------------------------------------------------------------------- #


class TestReferencias:
    def test_se_calcula_una_referencia_por_tematica_y_otra_por_comercio(self):
        gastos = [
            Gasto("a", euros("10"), tematica=ALIMENTACION, comercio=SUPERMERCADO),
            Gasto("b", euros("20"), tematica=ALIMENTACION, comercio=SUPERMERCADO),
            Gasto("c", euros("30"), tematica=ALIMENTACION),
        ]
        catalogo = anomalias.referencias(gastos)

        assert catalogo[(Ambito.TEMATICA, "c-1")].observaciones == 3
        assert catalogo[(Ambito.COMERCIO, "p-1")].observaciones == 2

    def test_los_ingresos_no_entran_en_la_referencia_de_gasto(self):
        gastos = [
            *serie(["10", "12", "11"]),
            Gasto("nomina", euros("2000"), tematica=ALIMENTACION, es_ingreso=True),
        ]
        catalogo = anomalias.referencias(gastos)

        assert catalogo[(Ambito.TEMATICA, "c-1")].observaciones == 3
        assert catalogo[(Ambito.TEMATICA, "c-1")].maximo == euros("12.00")

    def test_las_devoluciones_no_entran_en_la_referencia(self):
        gastos = [*serie(["10", "12", "11"]), Gasto("abono", euros("-40"), tematica=ALIMENTACION)]
        assert anomalias.referencias(gastos)[(Ambito.TEMATICA, "c-1")].observaciones == 3

    def test_un_gasto_recurrente_si_cuenta_para_la_referencia(self):
        """No es una anomalía, pero es gasto real de la temática."""
        gastos = [*serie(["10", "12", "11"]), Gasto("seguro", euros("600"), tematica=ALIMENTACION)]
        assert anomalias.referencias(gastos)[(Ambito.TEMATICA, "c-1")].observaciones == 4

    def test_manda_la_referencia_mas_especifica_el_comercio(self):
        gastos = [
            *serie(["10"] * 6, ALIMENTACION),
            *[Gasto(f"m{i}", euros("300"), tematica=HOGAR, comercio=MUEBLES) for i in range(6)],
        ]
        catalogo = anomalias.referencias(gastos)
        candidato = Gasto("nuevo", euros("300"), tematica=HOGAR, comercio=MUEBLES)

        referencia = anomalias.referencia_aplicable(candidato, catalogo)
        assert referencia is not None
        assert referencia.grupo == MUEBLES

    def test_sin_comercio_se_usa_la_tematica(self):
        catalogo = anomalias.referencias(serie(["10"] * 6))
        candidato = Gasto("nuevo", euros("10"), tematica=ALIMENTACION)

        referencia = anomalias.referencia_aplicable(candidato, catalogo)
        assert referencia is not None
        assert referencia.grupo == ALIMENTACION

    def test_un_grupo_con_pocas_observaciones_no_sirve_de_referencia(self):
        catalogo = anomalias.referencias(serie(["10", "11"]))
        candidato = Gasto("nuevo", euros("500"), tematica=ALIMENTACION)

        assert anomalias.referencia_aplicable(candidato, catalogo) is None


# --------------------------------------------------------------------------- #
# Los casos que hacen inútil la funcionalidad si están mal
# --------------------------------------------------------------------------- #


class TestCasosLimite:
    def test_con_dos_gastos_no_se_puede_hablar_de_lo_habitual(self):
        """Caso 1: pocas observaciones. Nada de veredictos con una muestra."""
        historial = [
            Gasto("a", euros("10"), tematica=ALIMENTACION),
            Gasto("b", euros("900"), tematica=ALIMENTACION),
        ]
        assert anomalias.detectar(historial) == []

    def test_a_partir_del_minimo_de_observaciones_ya_se_detecta(self):
        historial = serie(["45", "44", "46", "45", "47", "180"])
        detectadas = anomalias.detectar(historial)

        assert [una.identificador for una in detectadas] == ["g5"]
        assert detectadas[0].referencia.observaciones == 6

    def test_todos_los_recibos_iguales_no_convierten_un_euro_de_mas_en_anomalia(self):
        """Caso 2: dispersión cero. Sin suelo, 30,01 € saldría a infinitas sigmas."""
        historial = serie(["30"] * 10 + ["31"])
        assert anomalias.detectar(historial) == []

    def test_con_dispersion_cero_una_desviacion_de_verdad_si_se_detecta(self):
        historial = serie(["30"] * 10 + ["300"])
        detectadas = anomalias.detectar(historial)

        assert [una.identificador for una in detectadas] == ["g10"]
        assert detectadas[0].referencia.mad == euros("0.00")
        # El suelo de la dispersión es el 10 % de la mediana: 3,00 €.
        assert detectadas[0].referencia.dispersion == euros("3.00")

    def test_un_gasto_recurrente_nunca_se_marca(self):
        """Caso 3: el seguro anual entre las compras del mes es un cargo previsto."""
        historial = serie(["40"] * 10)
        seguro = Gasto("seguro", euros("600"), tematica=ALIMENTACION, es_recurrente=True)

        assert anomalias.detectar([*historial, seguro], candidatos=[seguro]) == []
        # Y sin la marca de recurrente, el mismo importe sí salta: la diferencia
        # está en la marca y no en el importe.
        suelto = Gasto("suelto", euros("600"), tematica=ALIMENTACION)
        assert len(anomalias.detectar([*historial, suelto], candidatos=[suelto])) == 1

    def test_un_ingreso_no_se_compara_con_los_gastos(self):
        """Caso 4: la nómina no es un gasto inusual de su temática."""
        historial = serie(["40"] * 10)
        nomina = Gasto("nomina", euros("2000"), tematica=NOMINA, es_ingreso=True)

        assert anomalias.detectar([*historial, nomina], candidatos=[nomina]) == []

    def test_gastar_menos_de_lo_habitual_no_es_una_alarma(self):
        historial = serie(["100"] * 10 + ["1"])
        assert anomalias.detectar(historial) == []

    def test_una_devolucion_no_es_una_anomalia(self):
        historial = serie(["40"] * 10)
        abono = Gasto("abono", euros("-500"), tematica=ALIMENTACION)
        assert anomalias.detectar([*historial, abono], candidatos=[abono]) == []

    def test_un_cafe_de_seis_euros_entre_cafes_de_tres_no_merece_un_aviso(self):
        """Es el 200 %, pero son tres euros: avisar de esto es ruido."""
        historial = serie(["3", "3", "3.20", "2.80", "3", "6"])
        assert anomalias.detectar(historial) == []

    def test_el_comercio_evita_el_falso_positivo_de_la_tematica(self):
        """En Hogar la mediana es de 30 €, pero en esa tienda siempre son 300 €."""
        historial = [
            *[Gasto(f"h{i}", euros("30"), tematica=HOGAR) for i in range(10)],
            *[Gasto(f"m{i}", euros("300"), tematica=HOGAR, comercio=MUEBLES) for i in range(6)],
        ]
        candidato = Gasto("nuevo", euros("305"), tematica=HOGAR, comercio=MUEBLES)

        assert anomalias.detectar([*historial, candidato], candidatos=[candidato]) == []

    def test_el_umbral_del_hogar_se_respeta(self):
        historial = serie(["45", "44", "46", "45", "47", "75"])

        assert anomalias.detectar(historial, sigma=Decimal("2.5"))
        assert anomalias.detectar(historial, sigma=Decimal("50")) == []

    def test_se_puede_endurecer_el_minimo_de_observaciones(self):
        historial = serie(["45", "44", "46", "45", "47", "180"])
        assert anomalias.detectar(historial, minimo_observaciones=20) == []


# --------------------------------------------------------------------------- #
# Lo que se le cuenta al usuario
# --------------------------------------------------------------------------- #


class TestExplicacion:
    def test_dice_lo_habitual_y_lo_de_esta_vez_en_euros_de_es_es(self):
        historial = serie(["45", "45", "45", "45", "45", "180"])
        anomalia = anomalias.detectar(historial)[0]

        assert "suele rondar los 45,00 €" in anomalia.motivo
        assert "esta vez han sido 180,00 €" in anomalia.motivo
        assert "Alimentación" in anomalia.motivo
        # Sin punto decimal a la inglesa por ningún lado.
        assert "45.00" not in anomalia.motivo

    def test_cuando_multiplica_lo_habitual_lo_dice_en_veces(self):
        anomalia = anomalias.detectar(serie(["45"] * 5 + ["180"]))[0]

        assert anomalia.veces == Decimal("4.00")
        assert "4,0 veces lo habitual" in anomalia.motivo

    def test_cuando_no_llega_al_doble_lo_dice_en_euros(self):
        anomalia = anomalias.detectar(serie(["45"] * 5 + ["70"]))[0]

        assert anomalia.veces is not None
        assert anomalia.veces < Decimal("2")
        assert "25,00 € más de lo habitual" in anomalia.motivo

    def test_el_motivo_da_tambien_la_media_y_el_maximo(self):
        anomalia = anomalias.detectar(serie(["45"] * 5 + ["180"]))[0]

        assert "media de" in anomalia.motivo
        assert "máximo de 180,00 €" in anomalia.motivo

    def test_el_comercio_se_nombra_cuando_es_el_que_decide(self):
        historial = [
            Gasto(f"s{i}", euros("45"), tematica=ALIMENTACION, comercio=SUPERMERCADO)
            for i in range(6)
        ]
        candidato = Gasto("caro", euros("180"), tematica=ALIMENTACION, comercio=SUPERMERCADO)
        anomalia = anomalias.detectar([*historial, candidato], candidatos=[candidato])[0]

        assert anomalia.referencia.grupo.ambito is Ambito.COMERCIO
        assert "Mercadona" in anomalia.motivo


# --------------------------------------------------------------------------- #
# Salida del punto de entrada
# --------------------------------------------------------------------------- #


class TestDetectar:
    def test_salen_ordenadas_de_mas_rara_a_menos(self):
        historial = serie(["50"] * 10 + ["120", "400"])
        detectadas = anomalias.detectar(historial)

        assert [una.identificador for una in detectadas] == ["g11", "g10"]
        assert detectadas[0].z > detectadas[1].z

    def test_solo_se_juzgan_los_candidatos_pero_la_referencia_es_todo(self):
        historial = serie(["50"] * 10 + ["400"])
        candidato = historial[-1]

        # Con el mismo historial, restringir los candidatos no cambia el veredicto
        # del que sí se juzga, pero silencia a los demás.
        assert len(anomalias.detectar(historial, candidatos=[candidato])) == 1
        assert anomalias.detectar(historial, candidatos=historial[:3]) == []

    def test_el_importe_y_el_z_se_publican_con_dos_decimales(self):
        anomalia = anomalias.detectar(serie(["45"] * 5 + ["180"]))[0]

        assert anomalia.importe == euros("180.00")
        assert anomalia.z == anomalia.z.quantize(Decimal("0.01"))

    def test_un_historial_vacio_no_revienta(self):
        assert anomalias.detectar([]) == []

    def test_se_pueden_agrupar_por_ambito_para_el_resumen(self):
        historial = [
            *serie(["50"] * 10 + ["400"]),
            *[Gasto(f"m{i}", euros("300"), tematica=HOGAR, comercio=MUEBLES) for i in range(10)],
            Gasto("mueble-caro", euros("2000"), tematica=HOGAR, comercio=MUEBLES),
        ]
        agrupadas = anomalias.por_ambito(anomalias.detectar(historial))

        assert [una.identificador for una in agrupadas[Ambito.TEMATICA]] == ["g10"]
        assert [una.identificador for una in agrupadas[Ambito.COMERCIO]] == ["mueble-caro"]
