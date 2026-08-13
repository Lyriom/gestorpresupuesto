"""Cuentas, valoraciones, préstamos, reconciliaciones y patrimonio neto."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Money, Rate
from app.models.mixins import CHECK_MONEDA, DomainBase, columna_moneda, fk_tenencia, uuid_fk

TIPOS_CUENTA = ("checking", "cash", "savings", "credit_card", "investment", "loan")
CLASES_CUENTA = ("asset", "liability")


class Account(DomainBase):
    """Cada bolsa de dinero del hogar (F-10).

    El saldo **no se almacena**: es `opening_balance + SUM(amount)`. Una compra con
    tarjeta es un gasto en la cuenta `credit_card` (saldo negativo = deuda) y el
    pago del extracto es una transferencia; así no existe la temática «Pago de
    tarjeta» ni el gasto se cuenta en el mes equivocado.
    """

    __tablename__ = "accounts"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    account_class: Mapped[str] = mapped_column(String(9), nullable=False)
    currency: Mapped[str] = columna_moneda()
    opening_balance: Mapped[Decimal] = mapped_column(
        Money, nullable=False, server_default=text("0")
    )
    opened_on: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    institution: Mapped[str | None] = mapped_column(Text)
    # Solo los cuatro últimos dígitos. Nunca el IBAN completo.
    iban_last4: Mapped[str | None] = mapped_column(CHAR(4))
    credit_limit: Mapped[Decimal | None] = mapped_column(Money)
    statement_day: Mapped[int | None] = mapped_column(SmallInteger)
    is_off_budget: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    include_in_net_worth: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    color_slot: Mapped[int | None] = mapped_column(SmallInteger)
    icon: Mapped[str] = mapped_column(Text, nullable=False, server_default="wallet")
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text)
    last_reconciled_on: Mapped[date | None] = mapped_column(Date)
    archived_at: Mapped[datetime | None]

    valuations: Mapped[list[AccountValuation]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="AccountValuation.account_id",
    )
    loan_terms: Mapped[LoanTerms | None] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        foreign_keys="LoanTerms.account_id",
    )

    __table_args__ = (
        Index(
            "uq_accounts_household_id_name",
            "household_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        Index(
            "ix_accounts_household_id_sort_order",
            "household_id",
            "sort_order",
            postgresql_where=text("archived_at IS NULL"),
        ),
        UniqueConstraint("household_id", "id"),
        CheckConstraint(
            "type IN ('checking', 'cash', 'savings', 'credit_card', 'investment', 'loan')",
            name="type",
        ),
        CheckConstraint("account_class IN ('asset', 'liability')", name="account_class"),
        # El tipo determina el lado del balance: no existe forma de dar de alta una
        # tarjeta de crédito como activo, así que el patrimonio neto no puede mentir.
        CheckConstraint(
            "(type IN ('credit_card', 'loan') AND account_class = 'liability') "
            "OR (type IN ('checking', 'cash', 'savings', 'investment') "
            "AND account_class = 'asset')",
            name="class_matches_type",
        ),
        CheckConstraint(CHECK_MONEDA, name="currency"),
        CheckConstraint(
            "statement_day IS NULL OR statement_day BETWEEN 1 AND 31", name="statement_day"
        ),
        CheckConstraint("credit_limit IS NULL OR credit_limit >= 0", name="credit_limit"),
        CheckConstraint("iban_last4 IS NULL OR iban_last4 ~ '^[0-9]{4}$'", name="iban_last4"),
    )


class AccountValuation(DomainBase):
    """Valor de mercado de las cuentas de inversión (F-11).

    Una cartera sube y baja sin que haya ninguna transacción; sin esta tabla el
    patrimonio neto de quien tiene fondos sería sistemáticamente falso.
    """

    __tablename__ = "account_valuations"

    account_id: Mapped[uuid.UUID] = uuid_fk("accounts.id", ondelete="CASCADE", nullable=False)
    valued_on: Mapped[date] = mapped_column(Date, nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Money, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="manual")
    note: Mapped[str | None] = mapped_column(Text)

    account: Mapped[Account] = relationship(back_populates="valuations", foreign_keys=[account_id])

    __table_args__ = (
        fk_tenencia("account_valuations", "account_id", "accounts", ondelete="CASCADE"),
        UniqueConstraint("account_id", "valued_on"),
        Index(
            "ix_account_valuations_account_id_valued_on",
            "account_id",
            text("valued_on DESC"),
            postgresql_include=["market_value"],
        ),
        CheckConstraint("source IN ('manual', 'import')", name="source"),
    )


class LoanTerms(DomainBase):
    """Condiciones del préstamo de una cuenta `type = 'loan'` (F-41).

    El cuadro de amortización se calcula: es función pura de estas columnas y
    guardarlo generaría filas que se contradirían al cambiar el Euríbor.
    """

    __tablename__ = "loan_terms"

    account_id: Mapped[uuid.UUID] = uuid_fk("accounts.id", ondelete="CASCADE", nullable=False)
    principal: Mapped[Decimal] = mapped_column(Money, nullable=False)
    annual_rate: Mapped[Decimal] = mapped_column(Rate, nullable=False)
    rate_type: Mapped[str] = mapped_column(String(8), nullable=False, server_default="fixed")
    reference_index: Mapped[str | None] = mapped_column(String(20))
    spread: Mapped[Decimal | None] = mapped_column(Rate)
    review_months: Mapped[int | None] = mapped_column(SmallInteger)
    payment_amount: Mapped[Decimal | None] = mapped_column(Money)
    payment_day: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    first_payment_on: Mapped[date] = mapped_column(Date, nullable=False)
    term_months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Borrar la regla de la cuota no debe borrar las condiciones del préstamo.
    recurring_rule_id: Mapped[uuid.UUID | None] = uuid_fk("recurring_rules.id", ondelete="SET NULL")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="active")

    account: Mapped[Account] = relationship(back_populates="loan_terms", foreign_keys=[account_id])

    __table_args__ = (
        fk_tenencia("loan_terms", "account_id", "accounts", ondelete="CASCADE"),
        UniqueConstraint("account_id"),
        CheckConstraint("rate_type IN ('fixed', 'variable', 'mixed')", name="rate_type"),
        CheckConstraint("status IN ('active', 'settled', 'cancelled')", name="status"),
        CheckConstraint(
            "principal > 0 AND (payment_amount IS NULL OR payment_amount > 0)", name="amounts"
        ),
        CheckConstraint("annual_rate >= 0 AND annual_rate < 100", name="rate"),
        CheckConstraint(
            "term_months BETWEEN 1 AND 720 AND payment_day BETWEEN 1 AND 28", name="term"
        ),
        CheckConstraint(
            "rate_type = 'fixed' OR reference_index IS NOT NULL", name="variable_needs_index"
        ),
    )


class Reconciliation(DomainBase):
    """Cuadre del saldo real del banco con el registrado (F-32)."""

    __tablename__ = "reconciliations"

    account_id: Mapped[uuid.UUID] = uuid_fk("accounts.id", ondelete="RESTRICT", nullable=False)
    statement_on: Mapped[date] = mapped_column(Date, nullable=False)
    statement_balance: Mapped[Decimal] = mapped_column(Money, nullable=False)
    computed_balance: Mapped[Decimal] = mapped_column(Money, nullable=False)
    difference: Mapped[Decimal] = mapped_column(Money, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    adjustment_transaction_id: Mapped[uuid.UUID | None] = uuid_fk(
        "transactions.id", ondelete="SET NULL"
    )
    reconciled_through: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[datetime | None]
    closed_by_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", ondelete="SET NULL")
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        fk_tenencia("reconciliations", "account_id", "accounts", ondelete="RESTRICT"),
        fk_tenencia(
            "reconciliations",
            "adjustment_transaction_id",
            "transactions",
            ondelete="SET NULL",
        ),
        Index(
            "uq_reconciliations_account_id_statement_on",
            "account_id",
            "statement_on",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
        Index(
            "ix_reconciliations_household_id_account_id_statement_on",
            "household_id",
            "account_id",
            text("statement_on DESC"),
        ),
        CheckConstraint("status IN ('open', 'closed', 'cancelled')", name="status"),
        # Mantiene la columna derivada coherente sin disparador.
        CheckConstraint("difference = statement_balance - computed_balance", name="difference"),
        CheckConstraint("(status = 'closed') = (closed_at IS NOT NULL)", name="closed"),
        # Impide el error clásico: cerrar descuadrado y descubrir tres meses después
        # que faltaban 40 € sin rastro.
        CheckConstraint(
            "status <> 'closed' OR difference = 0 OR adjustment_transaction_id IS NOT NULL",
            name="closed_needs_square",
        ),
    )


class NetWorthSnapshot(DomainBase):
    """Foto mensual del patrimonio neto (F-11).

    Se materializa porque la curva a 60 meses exigiría, en consulta directa, sumar
    todas las transacciones anteriores a cada corte, y porque el valor de una
    cuenta de inversión depende de la valoración vigente en cada fecha.
    """

    __tablename__ = "net_worth_snapshots"

    snapshot_on: Mapped[date] = mapped_column(Date, nullable=False)
    assets: Mapped[Decimal] = mapped_column(Money, nullable=False)
    liabilities: Mapped[Decimal] = mapped_column(Money, nullable=False)
    net_worth: Mapped[Decimal] = mapped_column(Money, nullable=False)
    by_account: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    currency: Mapped[str] = columna_moneda()
    source: Mapped[str] = mapped_column(String(10), nullable=False, server_default="scheduled")

    __table_args__ = (
        # Hace idempotente el trabajo nocturno vía INSERT ... ON CONFLICT DO UPDATE.
        UniqueConstraint("household_id", "snapshot_on"),
        Index(
            "ix_net_worth_snapshots_household_id_snapshot_on",
            "household_id",
            text("snapshot_on DESC"),
            postgresql_include=["assets", "liabilities", "net_worth"],
        ),
        CheckConstraint("net_worth = assets - liabilities", name="net"),
        CheckConstraint("liabilities >= 0", name="liabilities"),
        CheckConstraint("source IN ('scheduled', 'manual', 'backfill')", name="source"),
    )
