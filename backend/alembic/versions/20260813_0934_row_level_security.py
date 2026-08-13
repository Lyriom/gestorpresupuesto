"""Row Level Security: la tercera capa de la multi-tenencia.

Las dos primeras capas (el filtro del repositorio y las FK compuestas) bastan si el
código es correcto. Esta existe para cuando no lo sea: un endpoint escrito con
prisa, un `text()` a pelo, un script de mantenimiento.

**Dos cosas de la sección 7.4 quedan deliberadamente fuera**, y no por descuido:

1. `FORCE ROW LEVEL SECURITY`. Con `FORCE`, ni el propietario de la tabla se libra de
   sus políticas, y la aplicación se conecta hoy con el rol propietario y **sin**
   fijar `app.household_id` (eso vive en `app/db/session.py`, que aún no lo hace).
   Activarlo ahora dejaría toda consulta devolviendo cero filas. Se activa en la
   misma revisión en que la dependencia de sesión empiece a llamar a
   `set_config('app.household_id', :hh, true)`.
2. `CREATE ROLE app_rw`. Un rol es un objeto del clúster, no del esquema: exige
   `CREATEROLE` y una contraseña que no puede vivir en el repositorio. Lo crea el
   despliegue.

Lo que sí queda activo es la política: en cuanto la aplicación deje de conectarse
como propietaria, el aislamiento pasa a ser competencia de la base de datos.

Revision ID: 3f6b7dd10b1e
Revises: 3e816ac46606
Create Date: 2026-08-13 09:34:33.139502

"""

from collections.abc import Sequence

from alembic import op

revision: str = "3f6b7dd10b1e"
down_revision: str | None = "3e816ac46606"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tablas de dominio con `household_id NOT NULL`.
TABLAS_DOMINIO = (
    "account_valuations",
    "accounts",
    "alerts",
    "attachments",
    "budget_allocations",
    "budget_periods",
    "categories",
    "categorization_rules",
    "data_exports",
    "digest_runs",
    "goal_contributions",
    "goals",
    "import_batches",
    "import_rows",
    "invoice_lines",
    "invoices",
    "loan_terms",
    "merge_operation_changes",
    "merge_operations",
    "net_worth_snapshots",
    "payees",
    "product_aliases",
    "product_prices",
    "products",
    "reconciliations",
    "recurring_occurrences",
    "recurring_rules",
    "saved_views",
    "tags",
    "transaction_splits",
    "transaction_tags",
    "transactions",
)

# Tablas donde `household_id` puede ser NULL y ese NULL significa «de la instalación,
# no de un hogar»: las plantillas de extracción de serie y los eventos de
# autenticación previos a tener hogar.
TABLAS_CON_FILAS_GLOBALES = ("audit_log", "extraction_templates")

# `household_members` y `users` quedan fuera a propósito: hay que poder leerlas
# **antes** de saber en qué hogar entra la sesión, que es justo lo que decide
# `app.household_id`.

POLITICA = """
CREATE POLICY tenant_isolation ON {tabla}
    USING      ({condicion})
    WITH CHECK ({condicion});
"""

# `USING` filtra lo que se puede leer; `WITH CHECK` impide **escribir** una fila de
# otro hogar. Con solo `USING`, un INSERT con `household_id` ajeno pasaría.
CONDICION = "household_id = current_setting('app.household_id', true)::uuid"
CONDICION_GLOBAL = (
    "household_id IS NULL OR household_id = current_setting('app.household_id', true)::uuid"
)


def upgrade() -> None:
    for tabla in TABLAS_DOMINIO:
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
        op.execute(POLITICA.format(tabla=tabla, condicion=CONDICION))
    for tabla in TABLAS_CON_FILAS_GLOBALES:
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
        op.execute(POLITICA.format(tabla=tabla, condicion=CONDICION_GLOBAL))


def downgrade() -> None:
    for tabla in (*TABLAS_DOMINIO, *TABLAS_CON_FILAS_GLOBALES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tabla}")
        op.execute(f"ALTER TABLE {tabla} DISABLE ROW LEVEL SECURITY")
