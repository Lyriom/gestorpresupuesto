"""Pruebas de la capa de esquemas.

Se prueba lo que de verdad puede romperse y lo que el contrato promete por
escrito: que un importe nunca llega como número JSON ni con coma decimal, que
sale siempre con dos decimales, que los splits cuadran al céntimo, que un
periodo mal formado se rechaza, que los esquemas de actualización admiten
cambios parciales y que la traducción a las estructuras de `app/services` no se
ha duplicado por el camino.
"""

from __future__ import annotations

import pkgutil
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError

import app.schemas as esquemas
from app.core.errors import ReglaDeNegocio
from app.schemas import (
    AjustesActualizar,
    AsignacionCrear,
    CategoriaFusionCrear,
    CategoriaRefRespuesta,
    CondicionRegla,
    CuentaActualizar,
    CuentaRespuesta,
    EtiquetaFusionCrear,
    ExportacionCrear,
    ImporteStr,
    LineasFacturaRespuesta,
    MapeoImportacionCrear,
    ObjetivoCrear,
    Pagina,
    Periodo,
    Peticion,
    PrecioCrear,
    PrecioStr,
    PresupuestoReasignarCrear,
    ProductoCrear,
    RecurrenteCrear,
    Respuesta,
    SplitCrear,
    SplitsSustituirCrear,
    TransaccionActualizar,
    TransaccionCrear,
    TransferenciaCrear,
    VincularProductoCrear,
)
from app.schemas.factura import EstadoFactura
from app.schemas.recurrente import Frecuencia
from app.schemas.regla import CampoRegla, OperadorRegla
from app.services.extraccion_pdf import TOLERANCIA
from app.services.importacion import EstadoFila
from app.services.recurrencia import Frecuencia as FrecuenciaServicio
from app.services.reglas import Campo, Operador

CUENTA = uuid4()
TEMATICA = uuid4()
OTRA_TEMATICA = uuid4()
HOY = date.today()


class ModeloDinero(Peticion):
    """Modelo mínimo para probar los tipos de importe en aislamiento."""

    amount: ImporteStr
    unit_price: PrecioStr | None = None
    period: Periodo | None = None


def _codigos(error: ValidationError) -> list[str]:
    return [detalle["type"] for detalle in error.errors()]


def _mensajes(error: ValidationError) -> str:
    return " ".join(detalle["msg"] for detalle in error.errors())


def _transaccion(**cambios: object) -> dict[str, object]:
    base: dict[str, object] = {
        "account_id": CUENTA,
        "date": HOY.isoformat(),
        "amount": "48.50",
    }
    base.update(cambios)
    return base


# --------------------------------------------------------------------------- #
# §1.7 — Importes como cadena decimal
# --------------------------------------------------------------------------- #


class TestImporteStr:
    def test_acepta_cadena_con_punto(self) -> None:
        assert ModeloDinero(amount="12.50").amount == Decimal("12.50")

    @pytest.mark.parametrize("valor", ["45", "45.0", "45.00", "-45.00", "0.01"])
    def test_acepta_las_formas_equivalentes(self, valor: str) -> None:
        assert ModeloDinero(amount=valor).amount == Decimal(valor)

    def test_rechaza_el_numero_json_de_coma_flotante(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            ModeloDinero(amount=12.5)
        assert _codigos(fallo.value) == ["importe_no_es_cadena"]
        assert "cadena de texto" in _mensajes(fallo.value)

    def test_rechaza_la_coma_decimal(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            ModeloDinero(amount="12,50")
        assert _codigos(fallo.value) == ["importe_con_coma"]
        assert "punto como separador decimal" in _mensajes(fallo.value)

    @pytest.mark.parametrize(
        ("valor", "codigo"),
        [
            ("1.234,56", "importe_con_coma"),
            ("12,50 €", "importe_con_coma"),
            ("12.50 €", "importe_con_simbolos"),
            ("1 234.56", "importe_con_simbolos"),
            ("1e5", "importe_notacion_cientifica"),
            ("1E-4", "importe_notacion_cientifica"),
        ],
    )
    def test_rechaza_moneda_miles_y_notacion_cientifica(self, valor: str, codigo: str) -> None:
        with pytest.raises(ValidationError) as fallo:
            ModeloDinero(amount=valor)
        assert _codigos(fallo.value) == [codigo]

    def test_rechaza_el_booleano(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            ModeloDinero(amount=True)
        assert _codigos(fallo.value) == ["importe_invalido"]

    def test_rechaza_mas_de_dos_decimales(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            ModeloDinero(amount="12.505")
        # `errors.py` ya traduce este tipo: «Como máximo dos decimales».
        assert _codigos(fallo.value) == ["decimal_max_places"]

    def test_acepta_el_entero_json_porque_no_pierde_precision(self) -> None:
        assert ModeloDinero(amount=45).amount == Decimal("45")


class TestSerializacionDeImportes:
    @pytest.mark.parametrize(
        ("entrada", "salida"),
        [("45", "45.00"), ("45.0", "45.00"), ("45.5", "45.50"), ("-8.4", "-8.40"), ("0", "0.00")],
    )
    def test_el_dinero_sale_siempre_con_dos_decimales(self, entrada: str, salida: str) -> None:
        assert ModeloDinero(amount=entrada).model_dump(mode="json")["amount"] == salida

    def test_tambien_en_json_serializado(self) -> None:
        assert '"amount":"45.00"' in ModeloDinero(amount="45").model_dump_json()

    def test_el_modo_python_conserva_el_decimal(self) -> None:
        assert ModeloDinero(amount="45").model_dump()["amount"] == Decimal("45")


class TestPrecioStr:
    def test_conserva_cuatro_decimales(self) -> None:
        modelo = ModeloDinero(amount="22.04", unit_price="0.1487")
        assert modelo.unit_price == Decimal("0.1487")
        assert modelo.model_dump(mode="json")["unit_price"] == "0.1487"

    def test_rechaza_cinco_decimales(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            ModeloDinero(amount="1.00", unit_price="0.14875")
        assert _codigos(fallo.value) == ["decimal_max_places"]

    def test_no_rellena_decimales_que_no_significan_nada(self) -> None:
        modelo = ModeloDinero(amount="1.00", unit_price="1.5000")
        assert modelo.model_dump(mode="json")["unit_price"] == "1.5"

    def test_rechaza_el_flotante_igual_que_el_dinero(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            ModeloDinero(amount="1.00", unit_price=0.1487)
        assert _codigos(fallo.value) == ["importe_no_es_cadena"]

    def test_el_precio_de_una_observacion_debe_ser_positivo(self) -> None:
        with pytest.raises(ValidationError):
            PrecioCrear(product_id=uuid4(), observed_at=HOY, unit_price="0")


# --------------------------------------------------------------------------- #
# RN-30 — Periodos
# --------------------------------------------------------------------------- #


class TestPeriodo:
    def test_acepta_el_formato_del_contrato(self) -> None:
        assert ModeloDinero(amount="1.00", period="2026-08").period == "2026-08"

    @pytest.mark.parametrize(
        "valor", ["2026-8", "2026/08", "08-2026", "2026-13", "2026-00", "26-08", "2026", ""]
    )
    def test_rechaza_lo_que_no_es_aaaa_mm(self, valor: str) -> None:
        with pytest.raises(ValidationError) as fallo:
            ModeloDinero(amount="1.00", period=valor)
        assert "periodo_invalido" in _codigos(fallo.value)

    @pytest.mark.parametrize("valor", ["1800-01", "3000-01"])
    def test_rechaza_los_anyos_fuera_de_rango(self, valor: str) -> None:
        with pytest.raises(ValidationError) as fallo:
            ModeloDinero(amount="1.00", period=valor)
        assert _codigos(fallo.value) == ["periodo_invalido"]
        assert "1970" in _mensajes(fallo.value)

    def test_rechaza_un_periodo_que_no_es_texto(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            ModeloDinero(amount="1.00", period=202608)
        assert _codigos(fallo.value) == ["periodo_invalido"]


# --------------------------------------------------------------------------- #
# RN-15 y RN-16 — Splits
# --------------------------------------------------------------------------- #


class TestSplits:
    def test_la_suma_exacta_es_valida(self) -> None:
        transaccion = TransaccionCrear(
            **_transaccion(
                splits=[
                    {"category_id": TEMATICA, "amount": "45.00"},
                    {"category_id": OTRA_TEMATICA, "amount": "3.50"},
                ]
            )
        )
        assert len(transaccion.splits) == 2

    def test_rechaza_los_splits_que_no_cuadran(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransaccionCrear(**_transaccion(splits=[{"category_id": TEMATICA, "amount": "45.00"}]))
        assert _codigos(fallo.value) == ["splits_no_cuadran"]
        assert "45.00" in _mensajes(fallo.value) and "48.50" in _mensajes(fallo.value)

    def test_no_hay_tolerancia_ni_de_un_centimo(self) -> None:
        with pytest.raises(ValidationError):
            TransaccionCrear(**_transaccion(splits=[{"category_id": TEMATICA, "amount": "48.49"}]))

    def test_rechaza_dos_splits_de_la_misma_tematica(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransaccionCrear(
                **_transaccion(
                    splits=[
                        {"category_id": TEMATICA, "amount": "24.25"},
                        {"category_id": TEMATICA, "amount": "24.25"},
                    ]
                )
            )
        assert _codigos(fallo.value) == ["splits_no_cuadran"]
        assert "misma temática" in _mensajes(fallo.value)

    def test_con_splits_no_se_envia_tematica_en_la_transaccion(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransaccionCrear(
                **_transaccion(
                    category_id=TEMATICA,
                    splits=[{"category_id": TEMATICA, "amount": "48.50"}],
                )
            )
        assert _codigos(fallo.value) == ["splits_no_cuadran"]

    def test_una_devolucion_se_desglosa_en_negativo(self) -> None:
        transaccion = TransaccionCrear(
            **_transaccion(
                amount="-48.50",
                splits=[
                    {"category_id": TEMATICA, "amount": "-45.00"},
                    {"category_id": OTRA_TEMATICA, "amount": "-3.50"},
                ],
            )
        )
        assert transaccion.amount == Decimal("-48.50")

    def test_rechaza_mezclar_signos(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransaccionCrear(
                **_transaccion(
                    splits=[
                        {"category_id": TEMATICA, "amount": "50.00"},
                        {"category_id": OTRA_TEMATICA, "amount": "-1.50"},
                    ]
                )
            )
        assert _codigos(fallo.value) == ["splits_no_cuadran"]

    def test_un_split_de_cero_no_es_un_split(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            SplitCrear(category_id=TEMATICA, amount="0.00")
        assert _codigos(fallo.value) == ["splits_no_cuadran"]

    def test_el_put_de_splits_exige_al_menos_uno(self) -> None:
        with pytest.raises(ValidationError):
            SplitsSustituirCrear(splits=[])

    def test_el_put_de_splits_no_puede_comprobar_la_suma(self) -> None:
        """Sin el importe de la transacción, la suma la valida el servicio (RN-16)."""
        sustitucion = SplitsSustituirCrear(splits=[{"category_id": TEMATICA, "amount": "10.00"}])
        assert sustitucion.splits[0].amount == Decimal("10.00")


# --------------------------------------------------------------------------- #
# RN-26, RN-27 y RN-22 — Importe, fecha y transferencias
# --------------------------------------------------------------------------- #


class TestTransaccion:
    def test_el_importe_no_puede_ser_cero(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransaccionCrear(**_transaccion(amount="0.00"))
        assert "no puede ser cero" in _mensajes(fallo.value)

    def test_un_ingreso_no_puede_ser_negativo(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransaccionCrear(**_transaccion(kind="income", amount="-10.00"))
        assert "devolución" in _mensajes(fallo.value)

    def test_una_transferencia_no_se_crea_aqui(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransaccionCrear(**_transaccion(kind="transfer"))
        assert _codigos(fallo.value) == ["transferencia_invalida"]

    def test_rechaza_una_fecha_muy_en_el_futuro(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransaccionCrear(**_transaccion(date=(HOY + timedelta(days=400)).isoformat()))
        assert _codigos(fallo.value) == ["fecha_invalida"]

    def test_rechaza_una_fecha_anterior_a_1970(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransaccionCrear(**_transaccion(date="1969-12-31"))
        assert _codigos(fallo.value) == ["fecha_invalida"]

    def test_rechaza_un_campo_desconocido(self) -> None:
        """RN-01: un `user_id` en el cuerpo no se ignora, se rechaza."""
        with pytest.raises(ValidationError) as fallo:
            TransaccionCrear(**_transaccion(user_id=str(uuid4())))
        assert _codigos(fallo.value) == ["extra_forbidden"]


class TestTransferencia:
    def test_origen_y_destino_distintos(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransferenciaCrear(
                from_account_id=CUENTA, to_account_id=CUENTA, date=HOY, amount="100.00"
            )
        assert _codigos(fallo.value) == ["transferencia_invalida"]

    def test_la_comision_necesita_tematica(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransferenciaCrear(
                from_account_id=CUENTA,
                to_account_id=uuid4(),
                date=HOY,
                amount="100.00",
                fee="1.50",
            )
        assert "temática de la comisión" in _mensajes(fallo.value)


# --------------------------------------------------------------------------- #
# Actualizaciones parciales
# --------------------------------------------------------------------------- #


class TestActualizaciones:
    def test_admite_un_solo_campo(self) -> None:
        actualizacion = TransaccionActualizar(note="Pagado a medias")
        assert actualizacion.model_dump(exclude_unset=True) == {"note": "Pagado a medias"}

    def test_todos_los_campos_son_opcionales(self) -> None:
        assert CuentaActualizar().model_dump(exclude_unset=True) == {}

    def test_la_cadena_vacia_borra_el_campo(self) -> None:
        actualizacion = TransaccionActualizar(description="")
        assert actualizacion.model_dump(exclude_unset=True) == {"description": None}

    def test_valida_los_campos_que_si_llegan(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            TransaccionActualizar(amount="12,50")
        assert _codigos(fallo.value) == ["importe_con_coma"]

    def test_no_se_puede_editar_un_saldo_a_mano(self) -> None:
        """RN-08: el saldo es derivado; no hay campo que lo edite."""
        with pytest.raises(ValidationError) as fallo:
            CuentaActualizar(current_balance="1000.00")
        assert _codigos(fallo.value) == ["extra_forbidden"]

    def test_los_ajustes_admiten_un_umbral_suelto(self) -> None:
        assert AjustesActualizar(budget_alert_pct=0.9).model_dump(exclude_unset=True) == {
            "budget_alert_pct": 0.9
        }


# --------------------------------------------------------------------------- #
# Presupuesto, fusiones y objetivos
# --------------------------------------------------------------------------- #


class TestPresupuestoYFusiones:
    def test_una_asignacion_no_puede_ser_negativa(self) -> None:
        with pytest.raises(ValidationError):
            AsignacionCrear(category_id=TEMATICA, amount="-1.00")

    def test_la_reasignacion_necesita_dos_tematicas_distintas(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            PresupuestoReasignarCrear(
                from_category_id=TEMATICA, to_category_id=TEMATICA, amount="10.00"
            )
        assert "dos temáticas distintas" in _mensajes(fallo.value)

    def test_no_se_fusiona_una_tematica_consigo_misma(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            CategoriaFusionCrear(source_ids=[TEMATICA], target_id=TEMATICA)
        assert _codigos(fallo.value) == ["fusion_invalida"]

    def test_no_se_repiten_los_origenes_de_una_fusion(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            EtiquetaFusionCrear(source_ids=[TEMATICA, TEMATICA], target_id=OTRA_TEMATICA)
        assert _codigos(fallo.value) == ["fusion_invalida"]

    def test_un_objetivo_no_puede_vencer_en_el_pasado(self) -> None:
        with pytest.raises(ValidationError):
            ObjetivoCrear(
                name="Vacaciones", target_amount="2000.00", target_date=HOY - timedelta(days=1)
            )


# --------------------------------------------------------------------------- #
# Reutilización de las estructuras de `app/services`
# --------------------------------------------------------------------------- #


class TestPuentesConLosServicios:
    def test_la_condicion_se_traduce_al_vocabulario_del_motor(self) -> None:
        condicion = CondicionRegla(
            field=CampoRegla.PAYEE, operator=OperadorRegla.CONTAINS, value="mercadona"
        ).a_condicion()
        assert (condicion.campo, condicion.operador) == (Campo.COMERCIO, Operador.CONTIENE)

    def test_un_campo_sin_equivalente_avisa_en_vez_de_reventar(self) -> None:
        """Fuera de la validación el aviso viaja como `AppError`, no como 500."""
        with pytest.raises(ReglaDeNegocio) as fallo:
            CondicionRegla(
                field=CampoRegla.NOTE, operator=OperadorRegla.CONTAINS, value="x"
            ).a_condicion()
        assert fallo.value.estado == 422
        assert "note" in fallo.value.mensaje

    def test_el_regex_debe_compilar(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            CondicionRegla(field=CampoRegla.DESCRIPTION, operator=OperadorRegla.REGEX, value="[a-")
        assert "expresión regular" in _mensajes(fallo.value)

    def test_entre_necesita_el_segundo_valor(self) -> None:
        with pytest.raises(ValidationError):
            CondicionRegla(field=CampoRegla.AMOUNT, operator=OperadorRegla.BETWEEN, value="10")

    def test_no_se_compara_un_texto_con_mayor_que(self) -> None:
        with pytest.raises(ValidationError):
            CondicionRegla(field=CampoRegla.DESCRIPTION, operator=OperadorRegla.GT, value="10")

    @pytest.mark.parametrize(
        ("frecuencia", "esperada"),
        [
            (Frecuencia.MONTHLY, FrecuenciaServicio.MENSUAL),
            (Frecuencia.BIWEEKLY, FrecuenciaServicio.QUINCENAL),
            (Frecuencia.QUARTERLY, FrecuenciaServicio.TRIMESTRAL),
            (Frecuencia.EVERY_N_DAYS, FrecuenciaServicio.DIARIA),
        ],
    )
    def test_la_frecuencia_se_traduce_al_motor_de_recurrencia(
        self, frecuencia: Frecuencia, esperada: FrecuenciaServicio
    ) -> None:
        recurrente = RecurrenteCrear(
            name="Netflix",
            account_id=CUENTA,
            amount="13.99",
            frequency=frecuencia,
            interval=3,
            starts_on=HOY,
        )
        assert recurrente.a_regla_repeticion().frecuencia is esperada

    def test_el_ultimo_dia_laborable_es_una_mensual_ajustada(self) -> None:
        regla = RecurrenteCrear(
            name="Nómina",
            kind="income",
            account_id=CUENTA,
            amount="1800.00",
            frequency=Frecuencia.LAST_WEEKDAY_OF_MONTH,
            starts_on=HOY,
        ).a_regla_repeticion()
        assert regla.frecuencia is FrecuenciaServicio.MENSUAL
        assert regla.dia_del_mes == -1
        assert regla.solo_dias_laborables is True

    def test_el_recurrente_rechaza_un_rango_invertido(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            RecurrenteCrear(
                name="Seguro",
                account_id=CUENTA,
                amount="30.00",
                frequency=Frecuencia.YEARLY,
                starts_on=HOY,
                ends_on=HOY - timedelta(days=1),
            )
        assert "anterior a la de inicio" in _mensajes(fallo.value)

    def test_el_mapeo_traduce_nombres_de_columna_a_indices(self) -> None:
        mapeo = MapeoImportacionCrear(
            date_column="Fecha", amount_column="Importe", description_column="Concepto"
        ).a_mapeo_columnas(["Fecha ", "CONCEPTO", "Importe", "Saldo"])
        assert (mapeo.fecha, mapeo.concepto, mapeo.importe) == (0, 1, 2)
        assert mapeo.completo is True

    def test_una_columna_que_no_existe_es_un_mapeo_incompleto(self) -> None:
        with pytest.raises(ReglaDeNegocio) as fallo:
            MapeoImportacionCrear(date_column="Fecha", amount_column="Importe").a_mapeo_columnas(
                ["Fecha", "Concepto"]
            )
        assert fallo.value.codigo == "mapeo_incompleto"

    def test_el_mapeo_exige_columna_de_importe(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            MapeoImportacionCrear(date_column="Fecha")
        assert _codigos(fallo.value) == ["mapeo_incompleto"]

    def test_el_estado_de_fila_es_el_del_servicio(self) -> None:
        fila = esquemas.FilaImportacionRespuesta(id=uuid4(), row_number=1)
        assert fila.status is EstadoFila.VALIDA

    def test_la_tolerancia_de_la_revision_es_la_del_extractor(self) -> None:
        lineas = LineasFacturaRespuesta(
            invoice_id=uuid4(),
            status=EstadoFactura.PENDING_REVIEW,
            lines_sum="32.08",
            can_confirm=True,
        )
        assert lineas.tolerance == TOLERANCIA
        assert lineas.model_dump(mode="json")["tolerance"] == "0.02"


# --------------------------------------------------------------------------- #
# Facturas y productos
# --------------------------------------------------------------------------- #


class TestFacturaYProducto:
    def test_vincular_exige_uno_de_los_dos_caminos(self) -> None:
        with pytest.raises(ValidationError):
            VincularProductoCrear()
        with pytest.raises(ValidationError):
            VincularProductoCrear(product_id=uuid4(), new_product={"name": "Leche"})

    def test_vincular_a_un_producto_nuevo(self) -> None:
        enlace = VincularProductoCrear(new_product={"name": "Leche entera 1 l"})
        assert enlace.new_product is not None

    def test_un_tamanyo_sin_unidad_no_sirve_para_comparar(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            ProductoCrear(name="Aceite", size_value="1")
        assert "tamaño y su unidad" in _mensajes(fallo.value)

    def test_los_ficheros_originales_solo_caben_en_un_zip(self) -> None:
        with pytest.raises(ValidationError):
            ExportacionCrear(format="json", include_files=True)


# --------------------------------------------------------------------------- #
# §1.4 y §1.6 — Paginación y ordenación
# --------------------------------------------------------------------------- #


class TestPaginacionYOrden:
    def test_calcula_las_paginas(self) -> None:
        pagina = Pagina[str].crear(["a"], page=1, size=50, total=1284)
        assert pagina.pages == 26

    def test_el_tamanyo_maximo_es_200(self) -> None:
        with pytest.raises(ValidationError):
            esquemas.TransaccionFiltro(size=500)

    def test_solo_se_ordena_por_los_campos_declarados(self) -> None:
        with pytest.raises(ValidationError) as fallo:
            esquemas.TransaccionFiltro(sort="-password")
        assert _codigos(fallo.value) == ["datos_invalidos"]

    def test_traduce_el_parametro_sort(self) -> None:
        filtro = esquemas.TransaccionFiltro(sort="-date,amount")
        assert filtro.orden == [("date", True), ("amount", False)]

    def test_el_orden_por_defecto_es_el_del_contrato(self) -> None:
        assert esquemas.TransaccionFiltro().orden == [("date", True), ("created_at", True)]

    def test_una_busqueda_vacia_es_como_no_buscar(self) -> None:
        assert esquemas.TransaccionFiltro(q="  ").q is None

    def test_un_filtro_desconocido_se_ignora(self) -> None:
        filtro = esquemas.TransaccionFiltro(filtro_retirado="x")
        assert not hasattr(filtro, "filtro_retirado")


# --------------------------------------------------------------------------- #
# Garantías estructurales de toda la capa
# --------------------------------------------------------------------------- #


def _clases_de_esquema() -> list[type[BaseModel]]:
    return [
        valor
        for nombre in esquemas.__all__
        if isinstance(valor := getattr(esquemas, nombre), type) and issubclass(valor, BaseModel)
    ]


class TestGarantiasDeLaCapa:
    def test_las_respuestas_se_construyen_desde_el_orm(self) -> None:
        for clase in _clases_de_esquema():
            if issubclass(clase, Respuesta):
                assert clase.model_config.get("from_attributes") is True, clase.__name__

    def test_las_peticiones_rechazan_campos_desconocidos(self) -> None:
        for clase in _clases_de_esquema():
            if issubclass(clase, Peticion):
                assert clase.model_config.get("extra") == "forbid", clase.__name__

    def test_una_respuesta_se_construye_desde_un_objeto_con_atributos(self) -> None:
        fila = SimpleNamespace(id=uuid4(), name="Alimentación", color="#1e88e5", extra="ignorado")
        referencia = CategoriaRefRespuesta.model_validate(fila)
        assert referencia.name == "Alimentación"

    def test_una_cuenta_se_serializa_con_los_importes_en_cadena(self) -> None:
        ahora = date.today()
        fila = SimpleNamespace(
            id=uuid4(),
            created_at=ahora,
            updated_at=ahora,
            name="Cuenta corriente",
            type="checking",
            currency="EUR",
            initial_balance=Decimal("0"),
            current_balance=Decimal("1234.5"),
            available_balance=None,
            is_liability=False,
            is_archived=False,
            is_excluded_from_net_worth=False,
            color=None,
            icon=None,
            last_transaction_on=None,
            transactions_count=3,
            reconciled_through=None,
        )
        datos = CuentaRespuesta.model_validate(fila).model_dump(mode="json")
        assert datos["current_balance"] == "1234.50"
        assert datos["initial_balance"] == "0.00"

    def test_ningun_esquema_depende_del_orm(self) -> None:
        """Los esquemas no importan `app.models`: el contrato no depende de la persistencia."""
        for modulo in pkgutil.iter_modules(esquemas.__path__):
            fuente = (esquemas.__path__[0] + f"/{modulo.name}.py",)
            with open(fuente[0], encoding="utf-8") as fichero:
                assert "app.models" not in fichero.read(), modulo.name

    def test_todo_lo_exportado_existe(self) -> None:
        assert len(esquemas.__all__) == len(set(esquemas.__all__))
        for nombre in esquemas.__all__:
            assert hasattr(esquemas, nombre), nombre

    def test_los_identificadores_son_uuid(self) -> None:
        transaccion = TransaccionCrear(**_transaccion(account_id=str(CUENTA)))
        assert isinstance(transaccion.account_id, UUID)
