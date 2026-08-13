"""Transacciones, splits, transferencias, adjuntos y operaciones en lote.

§3.5, §3.6 y §4.5 del contrato. Las reglas de forma que se imponen aquí son
RN-15 y RN-16 (splits), RN-22 y RN-23 (transferencias) y RN-26 y RN-27 (importe
y fecha).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comercio import ComercioRefRespuesta
from app.schemas.comun import (
    Actualizacion,
    FechaMovimiento,
    ImporteStr,
    Moneda,
    ParametrosBusqueda,
    Peticion,
    Respuesta,
    RespuestaSellada,
    fallo,
    sin_repetidos,
    suma,
)
from app.schemas.cuenta import CuentaRefRespuesta
from app.schemas.etiqueta import EtiquetaRefRespuesta

#: RN-15: un desglose no pasa de cien líneas.
SPLITS_MAXIMOS = 100

#: Tope de un borrado en bloque, para que una llamada no bloquee la tabla.
LOTE_MAXIMO = 500


class TipoMovimiento(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"  # no cuenta como gasto ni como ingreso (RN-21)


class EstadoMovimiento(StrEnum):
    PENDING = "pending"
    CLEARED = "cleared"
    RECONCILED = "reconciled"


class OrigenMovimiento(StrEnum):
    """De dónde salió la transacción. Solo se lee, nunca se envía."""

    MANUAL = "manual"
    IMPORT = "import"
    INVOICE = "invoice"
    RECURRING = "recurring"
    RECONCILIATION = "reconciliation"


def _validar_importe_movimiento(importe: Decimal, kind: TipoMovimiento) -> None:
    """RN-26 y §1.7: nunca cero, y negativo solo para un gasto.

    El caso normal se teclea en positivo y el `kind` expresa la intención. El
    negativo existe para devoluciones, reembolsos y abonos, que deben **reducir
    el gastado de su temática** en lugar de inflar los ingresos del mes.
    """
    if importe == 0:
        fallo("datos_invalidos", "El importe no puede ser cero.")
    if importe < 0 and kind is not TipoMovimiento.EXPENSE:
        fallo(
            "datos_invalidos",
            "Solo un gasto puede ser negativo: una devolución es un gasto en negativo, "
            "no un ingreso.",
        )


class SplitCrear(Peticion):
    """Una línea del desglose (F-08).

    RN-15 pide importes positivos, que es el caso normal; en una devolución
    —transacción en negativo— los splits van en negativo para que sumen el
    importe. Lo que se comprueba siempre es que el signo sea el mismo que el de
    la transacción y que ninguno sea cero.
    """

    category_id: UUID
    amount: ImporteStr
    note: str | None = Field(default=None, max_length=280)

    @model_validator(mode="after")
    def _no_cero(self) -> SplitCrear:
        if self.amount == 0:
            fallo("splits_no_cuadran", "Un split no puede ser de cero euros.")
        return self


class SplitRespuesta(Respuesta):
    id: UUID
    category_id: UUID
    category: CategoriaRefRespuesta | None = None
    amount: ImporteStr
    note: str | None = None
    invoice_line_id: UUID | None = Field(
        default=None, description="Split generado al confirmar una factura."
    )


def _validar_splits(splits: list[SplitCrear], importe: Decimal | None) -> None:
    """RN-15: suman exactamente el importe, sin tolerancia y en `Decimal`."""
    if not splits:
        return
    if not sin_repetidos([split.category_id for split in splits]):
        fallo("splits_no_cuadran", "Hay dos splits con la misma temática: únelos en uno.")
    if importe is None:
        return
    if any((split.amount < 0) != (importe < 0) for split in splits):
        fallo("splits_no_cuadran", "Todos los splits deben tener el mismo signo que el importe.")
    total = suma(split.amount for split in splits)
    if total != importe:
        fallo(
            "splits_no_cuadran",
            f"Los splits suman {total} y la transacción es de {importe}.",
        )


class TransaccionCrear(Peticion):
    """Alta rápida de gasto o ingreso (F-07). Las transferencias van por `/transfers`."""

    kind: TipoMovimiento = TipoMovimiento.EXPENSE
    account_id: UUID
    date: FechaMovimiento
    amount: ImporteStr
    currency: Moneda = "EUR"
    category_id: UUID | None = Field(
        default=None, description="Nulo si hay splits o si se dejan actuar las reglas."
    )
    payee_id: UUID | None = None
    payee_name: str | None = Field(
        default=None, max_length=120, description="Crea el comercio si no existe."
    )
    description: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    tag_ids: list[UUID] = Field(default_factory=list, max_length=20)
    splits: list[SplitCrear] = Field(default_factory=list, max_length=SPLITS_MAXIMOS)
    apply_rules: bool = Field(default=True, description="Auto-categorización (F-27).")
    status: EstadoMovimiento = EstadoMovimiento.CLEARED
    invoice_id: UUID | None = None
    recurring_id: UUID | None = None

    @model_validator(mode="after")
    def _validar(self) -> TransaccionCrear:
        if self.kind is TipoMovimiento.TRANSFER:
            fallo(
                "transferencia_invalida",
                "Las transferencias se crean con POST /transfers, no aquí.",
            )
        _validar_importe_movimiento(self.amount, self.kind)
        if self.splits and self.category_id is not None:
            fallo(
                "splits_no_cuadran",
                "Con splits no se envía category_id: la temática va en cada split.",
            )
        _validar_splits(self.splits, self.amount)
        return self


class TransaccionActualizar(Actualizacion):
    """Edición parcial. Cambiar el importe con splits obliga a reenviarlos (RN-16)."""

    date: FechaMovimiento | None = None
    amount: ImporteStr | None = None
    kind: TipoMovimiento | None = None
    account_id: UUID | None = None
    category_id: UUID | None = None
    payee_id: UUID | None = None
    payee_name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    tag_ids: list[UUID] | None = Field(default=None, max_length=20)
    splits: list[SplitCrear] | None = Field(default=None, max_length=SPLITS_MAXIMOS)
    status: EstadoMovimiento | None = None

    @model_validator(mode="after")
    def _validar(self) -> TransaccionActualizar:
        if self.kind is TipoMovimiento.TRANSFER:
            fallo("transferencia_invalida", "Una transacción no se convierte en transferencia.")
        if self.amount is not None:
            _validar_importe_movimiento(self.amount, self.kind or TipoMovimiento.EXPENSE)
        if self.splits is not None:
            if self.category_id is not None:
                fallo(
                    "splits_no_cuadran",
                    "Con splits no se envía category_id: la temática va en cada split.",
                )
            # Sin `amount` en el cuerpo el que manda es el guardado, así que la
            # suma solo se puede comprobar en el servicio (RN-16).
            _validar_splits(self.splits, self.amount)
        return self


class SplitsSustituirCrear(Peticion):
    """`PUT /transactions/{id}/splits`: sustituye el conjunto completo. Idempotente."""

    splits: list[SplitCrear] = Field(min_length=1, max_length=SPLITS_MAXIMOS)

    @model_validator(mode="after")
    def _validar(self) -> SplitsSustituirCrear:
        _validar_splits(self.splits, None)
        return self


class TransaccionRespuesta(RespuestaSellada):
    kind: TipoMovimiento
    account_id: UUID
    account: CuentaRefRespuesta | None = None
    date: date
    amount: ImporteStr = Field(description="Como se capturó, con el signo que tecleó el usuario.")
    signed_amount: ImporteStr = Field(
        description="Efecto sobre el saldo, ya firmado. Comodidad para gráficos."
    )
    currency: str
    category_id: UUID | None
    category: CategoriaRefRespuesta | None = None
    payee_id: UUID | None
    payee: ComercioRefRespuesta | None = None
    description: str | None
    note: str | None
    is_split: bool
    splits: list[SplitRespuesta] = Field(default_factory=list)
    tags: list[EtiquetaRefRespuesta] = Field(default_factory=list)
    attachments_count: int = 0
    attachments: list[AdjuntoRespuesta] = Field(default_factory=list)
    invoice_id: UUID | None = None
    recurring_id: UUID | None = None
    transfer_group_id: UUID | None = None
    transfer_counterpart_id: UUID | None = None
    status: EstadoMovimiento
    is_reconciled: bool = Field(description="Derivado: status == 'reconciled'.")
    is_anomaly: bool = Field(default=False, description="Gasto inusual detectado (F-48).")
    source: OrigenMovimiento = OrigenMovimiento.MANUAL
    categorized_by: Literal["user", "rule", "invoice", "import"] | None = Field(
        default=None, description="RN-56: las reglas no pisan una categorización manual."
    )


class TransferenciaCrear(Peticion):
    """Dos patas enlazadas por `transfer_group_id`, sin temática (RN-21 a RN-23)."""

    from_account_id: UUID
    to_account_id: UUID
    date: FechaMovimiento
    amount: ImporteStr = Field(gt=0)
    currency: Moneda = "EUR"
    fee: ImporteStr | None = Field(default=None, ge=0, description="Comisión, si la hubo.")
    fee_category_id: UUID | None = None
    description: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    goal_id: UUID | None = Field(default=None, description="Aportación a un fondo objetivo.")

    @model_validator(mode="after")
    def _cuentas_distintas(self) -> TransferenciaCrear:
        if self.from_account_id == self.to_account_id:
            fallo(
                "transferencia_invalida",
                "La cuenta de origen y la de destino no pueden ser la misma.",
            )
        # La comisión sí es un gasto real y se registra aparte, con su temática.
        if self.fee and not self.fee_category_id:
            fallo("transferencia_invalida", "Indica la temática de la comisión.")
        return self


class TransferenciaActualizar(Actualizacion):
    """Las dos patas se modifican siempre juntas (RN-24)."""

    from_account_id: UUID | None = None
    to_account_id: UUID | None = None
    date: FechaMovimiento | None = None
    amount: ImporteStr | None = Field(default=None, gt=0)
    fee: ImporteStr | None = Field(default=None, ge=0)
    fee_category_id: UUID | None = None
    description: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _cuentas_distintas(self) -> TransferenciaActualizar:
        if (
            self.from_account_id is not None
            and self.to_account_id is not None
            and self.from_account_id == self.to_account_id
        ):
            fallo(
                "transferencia_invalida",
                "La cuenta de origen y la de destino no pueden ser la misma.",
            )
        return self


class TransferenciaRespuesta(Respuesta):
    """La transferencia como un solo objeto de dos patas (F-09)."""

    transfer_group_id: UUID
    date: date
    amount: ImporteStr
    currency: str = "EUR"
    fee: ImporteStr | None = None
    from_account: CuentaRefRespuesta
    to_account: CuentaRefRespuesta
    description: str | None
    note: str | None
    goal_id: UUID | None = None
    out_transaction_id: UUID
    in_transaction_id: UUID
    fee_transaction_id: UUID | None = None
    created_at: datetime


class GrupoDuplicadoRespuesta(Respuesta):
    """Candidatos a duplicado (F-34): se marcan, nunca se borran solos (RN-68)."""

    key: str
    score: float = Field(ge=0, le=1)
    reason: Literal["mismo_importe_y_fecha", "mismo_comercio", "importacion"]
    transactions: list[TransaccionRespuesta]


class TransaccionFusionCrear(Peticion):
    """Fusiona un duplicado en esta transacción: se queda lo mejor de cada una."""

    duplicate_id: UUID
    keep: dict[str, str | None] = Field(
        default_factory=dict,
        description="Campo → de cuál de las dos se conserva: 'this' o 'duplicate'.",
    )


class AdjuntoRespuesta(RespuestaSellada):
    transaction_id: UUID | None = None
    invoice_id: UUID | None = None
    filename: str = Field(description="Nombre original saneado, solo informativo (RN-77).")
    content_type: str
    size_bytes: int
    pages: int | None = None
    checksum: str = Field(description="SHA-256 en hexadecimal.")
    download_url: str


class LoteCategorizarCrear(Peticion):
    ids: list[UUID] = Field(min_length=1, max_length=LOTE_MAXIMO)
    category_id: UUID


class LoteEtiquetarCrear(Peticion):
    ids: list[UUID] = Field(min_length=1, max_length=LOTE_MAXIMO)
    add: list[UUID] = Field(default_factory=list, max_length=20)
    remove: list[UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _algo_que_hacer(self) -> LoteEtiquetarCrear:
        if not self.add and not self.remove:
            fallo("datos_invalidos", "Indica al menos una etiqueta que añadir o quitar.")
        if set(self.add) & set(self.remove):
            fallo("datos_invalidos", "Una misma etiqueta no se puede añadir y quitar a la vez.")
        return self


class LoteBorrarCrear(Peticion):
    ids: list[UUID] = Field(min_length=1, max_length=LOTE_MAXIMO)
    force: bool = Field(
        default=False, description="Necesario si alguna procede de una factura confirmada."
    )


class TransaccionFiltro(ParametrosBusqueda):
    """Todos los filtros combinables de F-42."""

    CAMPOS_ORDENABLES = frozenset(
        {"date", "amount", "created_at", "description", "payee", "category", "account"}
    )
    ORDEN_POR_DEFECTO = "-date,-created_at"

    date_from: date | None = None
    date_to: date | None = None
    account_id: list[UUID] = Field(default=[])
    category_id: list[UUID] = Field(default=[])
    include_children: bool = Field(
        default=True, description="El filtro por temática es jerárquico por defecto (§7.3)."
    )
    kind: list[TipoMovimiento] = Field(default=[])
    status: list[EstadoMovimiento] = Field(default=[])
    min_amount: ImporteStr | None = None
    max_amount: ImporteStr | None = None
    tag_id: list[UUID] = Field(default=[])
    payee_id: list[UUID] = Field(default=[])
    has_invoice: bool | None = None
    has_attachments: bool | None = None
    only_recurring: bool = False
    only_uncategorized: bool = False
    only_anomalies: bool = False
    invoice_id: UUID | None = None
    recurring_id: UUID | None = None
    include: list[Literal["splits", "tags", "payee", "attachments", "account", "category"]] = Field(
        default=[]
    )


class DuplicadoFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset({"date", "amount", "score"})
    ORDEN_POR_DEFECTO = "-score"

    days: int = Field(default=3, ge=0, le=30)
    account_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


class TransferenciaFiltro(ParametrosBusqueda):
    CAMPOS_ORDENABLES = frozenset({"date", "amount", "created_at"})
    ORDEN_POR_DEFECTO = "-date"

    date_from: date | None = None
    date_to: date | None = None
    account_id: list[UUID] = Field(default=[])
    goal_id: UUID | None = None


# `TransaccionRespuesta` cita a `AdjuntoRespuesta`, que se declara después.
TransaccionRespuesta.model_rebuild()
