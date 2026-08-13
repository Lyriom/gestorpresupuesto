"""Pruebas de la importación de extractos bancarios en CSV."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.importacion import (
    ErrorImportacion,
    MapeoColumnas,
    calcular_huella,
    detectar_mapeo,
    importar_csv,
    previsualizar,
)

# --- Extractos de ejemplo, con el estilo de cada banco ----------------------

BBVA = """Fecha;Fecha valor;Concepto;Importe;Divisa;Saldo
05/08/2026;05/08/2026;COMPRA MERCADONA 4021;-42,35;EUR;1.850,20
03/08/2026;03/08/2026;NOMINA AGOSTO;2.100,00;EUR;1.892,55
01/08/2026;01/08/2026;RECIBO ALQUILER;-750,00;EUR;-207,45
"""

SANTANDER_DEBE_HABER = """Fecha operacion,Concepto,Debe,Haber,Saldo
05/08/2026,PAGO TARJETA REPSOL,55.20,,1200.00
04/08/2026,TRANSFERENCIA RECIBIDA,,350.00,1255.20
"""

CON_METADATOS = """Titular: LYRIOM
IBAN: ES91 2100 0418 4502 0005 1332
Periodo: 01/08/2026 - 31/08/2026

Fecha;Concepto;Importe
05/08/2026;COMPRA CARREFOUR;-30,15
04/08/2026;FARMACIA;-12,40
"""

CON_FILAS_MALAS = """Fecha;Concepto;Importe
05/08/2026;COMPRA VALIDA;-30,15
fecha rara;OTRA COMPRA;-10,00
04/08/2026;;-5,00
03/08/2026;SIN IMPORTE;
02/08/2026;IMPORTE CERO;0,00
"""

TABULADO = "Fecha\tDescripcion\tImporte\n05/08/2026\tCOMPRA\t-30,15\n"


class TestDetectarMapeo:
    def test_reconoce_las_cabeceras_de_bbva(self):
        mapeo = detectar_mapeo(["Fecha", "Fecha valor", "Concepto", "Importe", "Divisa", "Saldo"])
        assert mapeo.fecha == 0
        assert mapeo.concepto == 2
        assert mapeo.importe == 3
        assert mapeo.saldo == 5
        assert mapeo.completo

    def test_reconoce_debe_y_haber(self):
        mapeo = detectar_mapeo(["Fecha operacion", "Concepto", "Debe", "Haber", "Saldo"])
        assert mapeo.cargo == 2
        assert mapeo.abono == 3
        assert mapeo.importe is None
        assert mapeo.completo

    def test_reconoce_cabeceras_en_ingles(self):
        mapeo = detectar_mapeo(["Date", "Description", "Amount", "Currency"])
        assert mapeo.completo

    def test_ignora_tildes_y_mayusculas(self):
        mapeo = detectar_mapeo(["FECHA", "DESCRIPCIÓN", "IMPORTE"])
        assert mapeo.completo

    def test_informa_de_lo_que_falta(self):
        mapeo = detectar_mapeo(["Columna A", "Columna B"])
        assert not mapeo.completo
        assert set(mapeo.campos_que_faltan) == {"fecha", "concepto", "importe"}


class TestImportarCsv:
    def test_extracto_de_bbva(self):
        resultado = importar_csv(BBVA.encode("utf-8"))
        assert len(resultado.validas) == 3
        assert resultado.delimitador == ";"

        primera = resultado.filas[0]
        assert primera.fecha == date(2026, 8, 5)
        assert primera.concepto == "COMPRA MERCADONA 4021"
        assert primera.importe == Decimal("-42.35")
        assert primera.saldo == Decimal("1850.20")
        assert primera.divisa == "EUR"

    def test_conserva_el_signo_del_ingreso(self):
        resultado = importar_csv(BBVA.encode("utf-8"))
        nomina = next(f for f in resultado.filas if "NOMINA" in f.concepto)
        assert nomina.importe == Decimal("2100.00")

    def test_saldo_negativo(self):
        resultado = importar_csv(BBVA.encode("utf-8"))
        alquiler = next(f for f in resultado.filas if "ALQUILER" in f.concepto)
        assert alquiler.saldo == Decimal("-207.45")

    def test_formato_debe_haber(self):
        resultado = importar_csv(SANTANDER_DEBE_HABER.encode("utf-8"))
        assert resultado.delimitador == ","
        cargo = resultado.filas[0]
        abono = resultado.filas[1]
        # El cargo es un gasto: se guarda en negativo aunque venga sin signo.
        assert cargo.importe == Decimal("-55.20")
        assert abono.importe == Decimal("350.00")

    def test_se_salta_los_metadatos_de_cabecera(self):
        resultado = importar_csv(CON_METADATOS.encode("utf-8"))
        assert resultado.fila_cabecera == 3
        assert len(resultado.validas) == 2
        assert any("ignorado" in aviso for aviso in resultado.avisos)

    def test_delimitador_tabulador(self):
        resultado = importar_csv(TABULADO.encode("utf-8"))
        assert resultado.delimitador == "\t"
        assert len(resultado.validas) == 1

    def test_codificacion_cp1252(self):
        contenido = "Fecha;Concepto;Importe\n05/08/2026;GESTIÓN CAFÉ;-3,50\n"
        resultado = importar_csv(contenido.encode("cp1252"))
        assert resultado.codificacion in ("cp1252", "iso-8859-15", "latin-1")
        assert "GESTIÓN CAFÉ" in resultado.filas[0].concepto

    def test_codificacion_utf8_con_bom(self):
        contenido = "Fecha;Concepto;Importe\n05/08/2026;CAFÉ;-3,50\n"
        resultado = importar_csv(contenido.encode("utf-8-sig"))
        assert resultado.mapeo.completo
        assert resultado.filas[0].concepto == "CAFÉ"


class TestFilasProblematicas:
    def test_marca_las_filas_malas_sin_abortar(self):
        resultado = importar_csv(CON_FILAS_MALAS.encode("utf-8"))
        assert len(resultado.validas) == 1
        assert len(resultado.con_error) == 4

    def test_explica_cada_error(self):
        resultado = importar_csv(CON_FILAS_MALAS.encode("utf-8"))
        errores = {f.numero: f.error for f in resultado.con_error}
        assert any("fecha" in e.lower() for e in errores.values())
        assert any("concepto" in e.lower() for e in errores.values())
        assert any("importe" in e.lower() for e in errores.values())

    def test_numera_las_filas_como_las_ve_el_usuario(self):
        resultado = importar_csv(CON_FILAS_MALAS.encode("utf-8"))
        # La cabecera es la línea 1, así que el primer movimiento es la 2.
        assert resultado.filas[0].numero == 2

    def test_rechaza_un_fichero_vacio(self):
        with pytest.raises(ErrorImportacion, match="vacío"):
            importar_csv(b"")

    def test_rechaza_solo_espacios(self):
        with pytest.raises(ErrorImportacion, match="vacío"):
            importar_csv(b"   \n  \n")

    def test_falla_si_no_reconoce_las_columnas(self):
        contenido = b"ColA;ColB;ColC\n1;2;3\n"
        with pytest.raises(ErrorImportacion, match="No se han reconocido"):
            importar_csv(contenido)

    def test_el_mapeo_manual_permite_importar_un_csv_sin_cabecera(self):
        contenido = b"05/08/2026;COMPRA SIN CABECERA;-30,15\n04/08/2026;OTRA COMPRA;-10,00\n"
        mapeo = MapeoColumnas(fecha=0, concepto=1, importe=2)
        resultado = importar_csv(contenido, mapeo_manual=mapeo, sin_cabecera=True)
        # Sin cabecera no se pierde el primer movimiento y la numeración empieza en 1.
        assert len(resultado.validas) == 2
        assert resultado.filas[0].numero == 1
        assert resultado.filas[0].concepto == "COMPRA SIN CABECERA"
        assert resultado.filas[0].importe == Decimal("-30.15")

    def test_el_mapeo_manual_con_cabecera_la_descarta(self):
        contenido = b"Col1;Col2;Col3\n05/08/2026;COMPRA;-30,15\n"
        mapeo = MapeoColumnas(fecha=0, concepto=1, importe=2)
        resultado = importar_csv(contenido, mapeo_manual=mapeo)
        assert len(resultado.validas) == 1
        assert resultado.filas[0].concepto == "COMPRA"

    def test_respeta_el_limite_de_filas(self):
        lineas = ["Fecha;Concepto;Importe"]
        lineas += [f"0{(i % 9) + 1}/08/2026;COMPRA {i};-{i + 1},00" for i in range(20)]
        resultado = importar_csv("\n".join(lineas).encode("utf-8"), max_filas=5)
        assert len(resultado.filas) == 5
        assert any("máximo por importación" in aviso for aviso in resultado.avisos)


class TestDuplicados:
    def test_detecta_duplicados_dentro_del_mismo_fichero(self):
        contenido = (
            "Fecha;Concepto;Importe\n"
            "05/08/2026;COMPRA MERCADONA;-42,35\n"
            "05/08/2026;COMPRA MERCADONA;-42,35\n"
        )
        resultado = importar_csv(contenido.encode("utf-8"))
        assert len(resultado.validas) == 1
        assert len(resultado.duplicadas) == 1

    def test_detecta_duplicados_de_importaciones_anteriores(self):
        huella = calcular_huella(date(2026, 8, 5), Decimal("-42.35"), "COMPRA MERCADONA 4021")
        resultado = importar_csv(BBVA.encode("utf-8"), huellas_existentes={huella})
        assert len(resultado.duplicadas) == 1
        assert len(resultado.validas) == 2

    def test_la_huella_ignora_el_espaciado(self):
        a = calcular_huella(date(2026, 8, 5), Decimal("-42.35"), "COMPRA   MERCADONA")
        b = calcular_huella(date(2026, 8, 5), Decimal("-42.35"), "compra mercadona")
        assert a == b

    def test_la_huella_distingue_importes_distintos(self):
        a = calcular_huella(date(2026, 8, 5), Decimal("-42.35"), "COMPRA")
        b = calcular_huella(date(2026, 8, 5), Decimal("-42.36"), "COMPRA")
        assert a != b

    def test_dos_compras_iguales_en_dias_distintos_no_son_duplicado(self):
        a = calcular_huella(date(2026, 8, 5), Decimal("-42.35"), "COMPRA")
        b = calcular_huella(date(2026, 8, 6), Decimal("-42.35"), "COMPRA")
        assert a != b


class TestResumen:
    def test_suma_lo_que_se_va_a_importar(self):
        resultado = importar_csv(BBVA.encode("utf-8"))
        # -42,35 + 2100 - 750
        assert resultado.total_importado == Decimal("1307.65")

    def test_avisa_si_no_hay_nada_nuevo(self):
        contenido = "Fecha;Concepto;Importe\n05/08/2026;COMPRA;-1,00\n"
        huella = calcular_huella(date(2026, 8, 5), Decimal("-1.00"), "COMPRA")
        resultado = importar_csv(contenido.encode("utf-8"), huellas_existentes={huella})
        assert any("ningún movimiento nuevo" in aviso for aviso in resultado.avisos)


class TestPrevisualizar:
    def test_devuelve_la_cabecera_y_una_muestra(self):
        vista = previsualizar(BBVA.encode("utf-8"), filas=2)
        assert vista["delimitador"] == ";"
        assert vista["cabecera"][0] == "Fecha"
        assert len(vista["muestra"]) == 2
        assert vista["total_filas"] == 3
        assert vista["campos_que_faltan"] == []

    def test_informa_de_las_columnas_no_reconocidas(self):
        vista = previsualizar(b"ColA;ColB\n1;2\n")
        assert set(vista["campos_que_faltan"]) == {"fecha", "concepto", "importe"}
