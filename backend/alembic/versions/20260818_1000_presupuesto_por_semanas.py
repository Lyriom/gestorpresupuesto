"""El presupuesto puede ir por semanas y no solo por meses.

Un `budget_periods` era siempre un mes: la columna se llamaba `period_month` y una
restricción exigía que fuera el día 1. Para presupuestar por semanas —quien cobra
cada semana no reparte el dinero del mes, reparte el de la paga— hace falta que un
periodo pueda ser también una semana.

Se resuelve **sin tocar el tipo de dato**, que ya era el bueno: el periodo siempre
ha sido una fecha, la de su primer día, no una cadena `AAAA-MM`. Basta con dejar
que ese primer día sea un lunes y con guardar de qué clase de periodo se trata.

La columna pasa a llamarse `period_start`, porque `period_month` conteniendo un
lunes sería una mentira de las que cuestan una tarde. Y la granularidad se guarda
**en cada fila**, no solo en el ajuste del hogar: el ajuste dice cómo se presupuesta
a partir de ahora, y la fila dice qué era ese periodo cuando se creó. Así, cambiar
de mensual a semanal no reinterpreta lo ya guardado, que es el error clásico de
meter la unidad en la configuración y no en el dato.

La semana es la ISO, de lunes a domingo, y quien lo garantiza es la propia base:
la restricción `date_trunc(granularity, period_start)` sirve igual para el día 1 de
un mes que para el lunes de una semana, porque `date_trunc('week', …)` de PostgreSQL
también es de lunes a domingo. Una sola expresión para los dos casos.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c7f3a92e6d18"
down_revision: str | None = "b2d4e7a19c05"
branch_labels: str | None = None
depends_on: str | None = None

GRANULARIDADES = "IN ('month', 'week')"

#: El primer día de un periodo es el 1 si es un mes y el lunes si es una semana.
#: `date_trunc` acepta la unidad como argumento, así que la misma expresión vale
#: para los dos y no hay que enumerar casos.
#:
#: El `::timestamp` explícito no es adorno: sin él, PostgreSQL resuelve la llamada
#: a la variante de `timestamptz`, que es STABLE porque depende del huso de la
#: sesión. Una restricción sobre una columna `date` no puede depender de eso, y con
#: el molde queda la variante IMMUTABLE, que es la que corresponde.
CHECK_INICIO = "period_start = date_trunc(granularity, period_start::timestamp)::date"


def upgrade() -> None:
    op.add_column(
        "households",
        sa.Column(
            "budget_granularity", sa.String(length=5), nullable=False, server_default="month"
        ),
    )
    op.create_check_constraint(
        op.f("ck_households_budget_granularity"),
        "households",
        f"budget_granularity {GRANULARIDADES}",
    )

    op.add_column(
        "budget_periods",
        sa.Column("granularity", sa.String(length=5), nullable=False, server_default="month"),
    )
    op.alter_column("budget_periods", "period_month", new_column_name="period_start")

    # PostgreSQL reescribe solo las restricciones al renombrar la columna, pero no
    # sus nombres: esta se sigue llamando `first_of_month` y ya no habla solo de meses.
    op.drop_constraint(op.f("ck_budget_periods_first_of_month"), "budget_periods", type_="check")
    op.create_check_constraint(
        op.f("ck_budget_periods_granularity"), "budget_periods", f"granularity {GRANULARIDADES}"
    )
    op.create_check_constraint(
        op.f("ck_budget_periods_period_start"), "budget_periods", CHECK_INICIO
    )

    # La unicidad tiene que incluir la granularidad: el 1 de junio de 2026 es lunes,
    # así que el mes de junio y la semana 23 empiezan el mismo día y son dos periodos
    # distintos que deben poder convivir.
    op.drop_constraint(
        op.f("uq_budget_periods_household_id_period_month"), "budget_periods", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_budget_periods_household_id_granularity_period_start"),
        "budget_periods",
        ["household_id", "granularity", "period_start"],
    )

    op.drop_index("ix_budget_periods_household_id_period_month", table_name="budget_periods")
    op.create_index(
        "ix_budget_periods_household_id_granularity_period_start",
        "budget_periods",
        ["household_id", "granularity", sa.literal_column("period_start DESC")],
        unique=False,
    )


def downgrade() -> None:
    # Un periodo semanal no cabe en el esquema anterior y no hay ningún mes al que
    # convertirlo sin inventarse el reparto, así que se borra con sus asignaciones.
    op.execute("DELETE FROM budget_periods WHERE granularity = 'week'")

    op.drop_index(
        "ix_budget_periods_household_id_granularity_period_start", table_name="budget_periods"
    )
    op.drop_constraint(
        op.f("uq_budget_periods_household_id_granularity_period_start"),
        "budget_periods",
        type_="unique",
    )
    op.drop_constraint(op.f("ck_budget_periods_period_start"), "budget_periods", type_="check")
    op.drop_constraint(op.f("ck_budget_periods_granularity"), "budget_periods", type_="check")
    op.alter_column("budget_periods", "period_start", new_column_name="period_month")
    op.drop_column("budget_periods", "granularity")

    op.create_check_constraint(
        op.f("ck_budget_periods_first_of_month"),
        "budget_periods",
        "period_month = date_trunc('month', period_month)::date",
    )
    op.create_unique_constraint(
        op.f("uq_budget_periods_household_id_period_month"),
        "budget_periods",
        ["household_id", "period_month"],
    )
    op.create_index(
        "ix_budget_periods_household_id_period_month",
        "budget_periods",
        ["household_id", sa.literal_column("period_month DESC")],
        unique=False,
    )

    op.drop_constraint(op.f("ck_households_budget_granularity"), "households", type_="check")
    op.drop_column("households", "budget_granularity")
