"""Modelos de la base de datos.

`alembic/env.py` hace `import app.models` para poblar `Base.metadata`: un modelo
que no se importe aquí **no existe** para `autogenerate`, y el síntoma es una
migración que omite una tabla en silencio. Por eso se importan todos, y por eso
`__all__` los enumera uno a uno.
"""

from __future__ import annotations

from app.models.alerta import Alert, DigestRun
from app.models.auditoria import AuditLog
from app.models.categoria import Category, CategoryTemplate
from app.models.comercio import Payee
from app.models.cuenta import (
    Account,
    AccountValuation,
    LoanTerms,
    NetWorthSnapshot,
    Reconciliation,
)
from app.models.factura import ExtractionTemplate, Invoice, InvoiceLine
from app.models.fusion import MergeOperation, MergeOperationChange
from app.models.hogar import Household, HouseholdMember
from app.models.importacion import ImportBatch, ImportRow
from app.models.mixins import DomainBase, GlobalBase
from app.models.objetivo import Goal, GoalContribution
from app.models.presupuesto import BudgetAllocation, BudgetPeriod
from app.models.producto import Product, ProductAlias, ProductPrice
from app.models.recurrente import RecurringOccurrence, RecurringRule
from app.models.regla import CategorizationRule
from app.models.sistema import DataExport, SavedView
from app.models.transaccion import (
    Attachment,
    Tag,
    Transaction,
    TransactionSplit,
    TransactionTag,
)
from app.models.usuario import RefreshToken, User

__all__ = [
    "Account",
    "AccountValuation",
    "Alert",
    "Attachment",
    "AuditLog",
    "BudgetAllocation",
    "BudgetPeriod",
    "CategorizationRule",
    "Category",
    "CategoryTemplate",
    "DataExport",
    "DigestRun",
    "DomainBase",
    "ExtractionTemplate",
    "GlobalBase",
    "Goal",
    "GoalContribution",
    "Household",
    "HouseholdMember",
    "ImportBatch",
    "ImportRow",
    "Invoice",
    "InvoiceLine",
    "LoanTerms",
    "MergeOperation",
    "MergeOperationChange",
    "NetWorthSnapshot",
    "Payee",
    "Product",
    "ProductAlias",
    "ProductPrice",
    "Reconciliation",
    "RecurringOccurrence",
    "RecurringRule",
    "RefreshToken",
    "SavedView",
    "Tag",
    "Transaction",
    "TransactionSplit",
    "TransactionTag",
    "User",
]
