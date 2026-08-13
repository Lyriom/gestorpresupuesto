"""Pruebas de las reglas de repetición."""

from datetime import date

import pytest

from app.services.recurrencia import (
    ErrorRecurrencia,
    Frecuencia,
    ReglaRepeticion,
    esta_proximo,
    generar_fechas,
    proximas_ocurrencias,
    siguiente_fecha,
)


class TestValidacion:
    def test_intervalo_minimo(self):
        with pytest.raises(ErrorRecurrencia, match="al menos 1"):
            ReglaRepeticion(Frecuencia.MENSUAL, intervalo=0)

    @pytest.mark.parametrize("dia", [0, 32, -2])
    def test_dia_del_mes_fuera_de_rango(self, dia):
        with pytest.raises(ErrorRecurrencia, match="día del mes"):
            ReglaRepeticion(Frecuencia.MENSUAL, dia_del_mes=dia)

    def test_dia_del_mes_ultimo_es_valido(self):
        assert ReglaRepeticion(Frecuencia.MENSUAL, dia_del_mes=-1).dia_del_mes == -1

    def test_dia_de_la_semana_fuera_de_rango(self):
        with pytest.raises(ErrorRecurrencia, match="día de la semana"):
            ReglaRepeticion(Frecuencia.SEMANAL, dia_de_la_semana=7)

    def test_fecha_fin_anterior_al_inicio(self):
        with pytest.raises(ErrorRecurrencia, match="fecha de fin"):
            ReglaRepeticion(
                Frecuencia.MENSUAL,
                fecha_inicio=date(2026, 8, 1),
                fecha_fin=date(2026, 7, 1),
            )

    def test_repeticiones_minimas(self):
        with pytest.raises(ErrorRecurrencia, match="repeticiones"):
            ReglaRepeticion(Frecuencia.MENSUAL, repeticiones_max=0)


class TestSiguienteFecha:
    def test_alquiler_el_dia_uno(self):
        regla = ReglaRepeticion(Frecuencia.MENSUAL, dia_del_mes=1, fecha_inicio=date(2026, 1, 1))
        assert siguiente_fecha(regla, date(2026, 8, 13)) == date(2026, 9, 1)

    def test_nomina_el_ultimo_dia_del_mes(self):
        regla = ReglaRepeticion(Frecuencia.MENSUAL, dia_del_mes=-1, fecha_inicio=date(2026, 1, 31))
        assert siguiente_fecha(regla, date(2026, 8, 13)) == date(2026, 8, 31)
        assert siguiente_fecha(regla, date(2026, 8, 31)) == date(2026, 9, 30)

    def test_dia_31_en_un_mes_de_30(self):
        regla = ReglaRepeticion(Frecuencia.MENSUAL, dia_del_mes=31, fecha_inicio=date(2026, 1, 31))
        # Abril tiene 30 días: se usa el último disponible, no se salta el mes.
        assert siguiente_fecha(regla, date(2026, 3, 31)) == date(2026, 4, 30)

    def test_dia_29_en_febrero_no_bisiesto(self):
        regla = ReglaRepeticion(Frecuencia.MENSUAL, dia_del_mes=29, fecha_inicio=date(2026, 1, 29))
        assert siguiente_fecha(regla, date(2026, 1, 29)) == date(2026, 2, 28)

    def test_suscripcion_semanal(self):
        regla = ReglaRepeticion(Frecuencia.SEMANAL, fecha_inicio=date(2026, 8, 3))
        assert siguiente_fecha(regla, date(2026, 8, 5)) == date(2026, 8, 10)

    def test_quincenal(self):
        regla = ReglaRepeticion(Frecuencia.QUINCENAL, fecha_inicio=date(2026, 8, 1))
        assert siguiente_fecha(regla, date(2026, 8, 1)) == date(2026, 8, 15)

    def test_intervalo_de_dos_meses(self):
        regla = ReglaRepeticion(
            Frecuencia.MENSUAL, intervalo=2, dia_del_mes=10, fecha_inicio=date(2026, 1, 10)
        )
        assert siguiente_fecha(regla, date(2026, 1, 10)) == date(2026, 3, 10)

    def test_seguro_semestral(self):
        regla = ReglaRepeticion(Frecuencia.SEMESTRAL, fecha_inicio=date(2026, 3, 15))
        assert siguiente_fecha(regla, date(2026, 3, 15)) == date(2026, 9, 15)

    def test_anual_cruza_el_anyo(self):
        regla = ReglaRepeticion(Frecuencia.ANUAL, fecha_inicio=date(2026, 12, 20))
        assert siguiente_fecha(regla, date(2026, 12, 20)) == date(2027, 12, 20)

    def test_devuelve_none_si_la_regla_ha_terminado(self):
        regla = ReglaRepeticion(
            Frecuencia.MENSUAL,
            dia_del_mes=1,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 6, 30),
        )
        assert siguiente_fecha(regla, date(2026, 7, 1)) is None

    def test_devuelve_none_si_la_siguiente_supera_el_fin(self):
        regla = ReglaRepeticion(
            Frecuencia.MENSUAL,
            dia_del_mes=15,
            fecha_inicio=date(2026, 1, 15),
            fecha_fin=date(2026, 8, 20),
        )
        assert siguiente_fecha(regla, date(2026, 8, 15)) is None


class TestDiasLaborables:
    def test_adelanta_el_sabado_al_viernes(self):
        # El 1 de agosto de 2026 es sábado.
        regla = ReglaRepeticion(
            Frecuencia.MENSUAL,
            dia_del_mes=1,
            fecha_inicio=date(2026, 8, 1),
            solo_dias_laborables=True,
        )
        assert date(2026, 8, 1).weekday() == 5
        assert siguiente_fecha(regla, date(2026, 7, 20)) == date(2026, 7, 31)

    def test_adelanta_el_domingo_al_viernes(self):
        # El 1 de noviembre de 2026 es domingo.
        regla = ReglaRepeticion(
            Frecuencia.MENSUAL,
            dia_del_mes=1,
            fecha_inicio=date(2026, 11, 1),
            solo_dias_laborables=True,
        )
        assert date(2026, 11, 1).weekday() == 6
        assert siguiente_fecha(regla, date(2026, 10, 20)) == date(2026, 10, 30)

    def test_deja_los_laborables_intactos(self):
        regla = ReglaRepeticion(
            Frecuencia.MENSUAL,
            dia_del_mes=10,
            fecha_inicio=date(2026, 8, 10),
            solo_dias_laborables=True,
        )
        # El 10 de septiembre de 2026 es jueves.
        assert siguiente_fecha(regla, date(2026, 8, 10)) == date(2026, 9, 10)


class TestGenerarFechas:
    def test_todas_las_ocurrencias_del_intervalo(self):
        regla = ReglaRepeticion(Frecuencia.MENSUAL, dia_del_mes=1, fecha_inicio=date(2026, 1, 1))
        fechas = generar_fechas(regla, date(2026, 1, 1), date(2026, 6, 30))
        assert fechas == [
            date(2026, 2, 1),
            date(2026, 3, 1),
            date(2026, 4, 1),
            date(2026, 5, 1),
            date(2026, 6, 1),
        ]

    def test_respeta_el_maximo_de_repeticiones(self):
        regla = ReglaRepeticion(
            Frecuencia.MENSUAL,
            dia_del_mes=1,
            fecha_inicio=date(2026, 1, 1),
            repeticiones_max=2,
        )
        assert len(generar_fechas(regla, date(2026, 1, 1), date(2026, 12, 31))) == 2

    def test_respeta_el_limite_de_seguridad(self):
        regla = ReglaRepeticion(Frecuencia.DIARIA, fecha_inicio=date(2026, 1, 1))
        fechas = generar_fechas(regla, date(2026, 1, 1), date(2030, 1, 1), limite=10)
        assert len(fechas) == 10

    def test_intervalo_invertido_devuelve_vacio(self):
        regla = ReglaRepeticion(Frecuencia.MENSUAL, fecha_inicio=date(2026, 1, 1))
        assert generar_fechas(regla, date(2026, 6, 1), date(2026, 1, 1)) == []


class TestProximasOcurrencias:
    def test_incluye_la_de_hoy(self):
        regla = ReglaRepeticion(Frecuencia.MENSUAL, dia_del_mes=13, fecha_inicio=date(2026, 1, 13))
        proximas = proximas_ocurrencias(regla, date(2026, 8, 13), cuantas=3)
        assert proximas == [date(2026, 8, 13), date(2026, 9, 13), date(2026, 10, 13)]

    def test_se_detiene_al_terminar_la_regla(self):
        regla = ReglaRepeticion(
            Frecuencia.MENSUAL,
            dia_del_mes=1,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 10, 5),
        )
        assert proximas_ocurrencias(regla, date(2026, 8, 13), cuantas=5) == [
            date(2026, 9, 1),
            date(2026, 10, 1),
        ]


class TestAvisos:
    def test_avisa_de_un_cargo_cercano(self):
        assert esta_proximo(date(2026, 8, 15), date(2026, 8, 13))

    def test_no_avisa_de_uno_lejano(self):
        assert not esta_proximo(date(2026, 8, 25), date(2026, 8, 13))

    def test_no_avisa_de_uno_pasado(self):
        assert not esta_proximo(date(2026, 8, 10), date(2026, 8, 13))

    def test_avisa_el_mismo_dia(self):
        assert esta_proximo(date(2026, 8, 13), date(2026, 8, 13))


class TestDescripcion:
    def test_mensual_con_dia(self):
        regla = ReglaRepeticion(Frecuencia.MENSUAL, dia_del_mes=1)
        assert regla.descripcion == "cada mes, el día 1"

    def test_ultimo_dia_laborable(self):
        regla = ReglaRepeticion(Frecuencia.MENSUAL, dia_del_mes=-1, solo_dias_laborables=True)
        assert "último día del mes" in regla.descripcion
        assert "fin de semana" in regla.descripcion

    def test_con_intervalo(self):
        regla = ReglaRepeticion(Frecuencia.MENSUAL, intervalo=3)
        assert regla.descripcion == "cada 3 meses"
