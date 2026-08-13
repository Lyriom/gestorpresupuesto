"""Vistas, vista materializada, funciones y disparadores.

Va en una revisión aparte porque todo esto es **invisible** para `autogenerate`: si
estuviera mezclado con el esquema inicial, cualquier `--autogenerate` posterior
propondría borrarlo. Aislado y escrito con `op.execute()`, se versiona como
cualquier otro cambio y se rehace con un `CREATE OR REPLACE`.

Revision ID: 3e816ac46606
Revises: 43df3534d034
Create Date: 2026-08-13 09:34:32.998989

"""

from collections.abc import Sequence

from alembic import op

revision: str = "3e816ac46606"
down_revision: str | None = "43df3534d034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Todas las tablas llevan `updated_at`, así que todas llevan disparador.
TABLAS = (
    "account_valuations",
    "accounts",
    "alerts",
    "attachments",
    "audit_log",
    "budget_allocations",
    "budget_periods",
    "categories",
    "categorization_rules",
    "category_templates",
    "data_exports",
    "digest_runs",
    "extraction_templates",
    "goal_contributions",
    "goals",
    "household_members",
    "households",
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
    "refresh_tokens",
    "saved_views",
    "tags",
    "transaction_splits",
    "transaction_tags",
    "transactions",
    "users",
)

# `Timestamps.updated_at` usa `onupdate=func.now()`, que SQLAlchemy resuelve en el
# cliente al emitir un UPDATE por el ORM. La fusión y los trabajos programados
# escriben con SQL crudo, donde ese `onupdate` no interviene: este disparador es la
# red de seguridad para todo lo que no pasa por el ORM.
FUNCION_UPDATED_AT = """
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
"""

# Mantiene las columnas derivadas que sostienen `ck_transactions_split_invariant`.
FUNCION_SPLIT_TOTALS = """
CREATE OR REPLACE FUNCTION refresh_transaction_split_totals() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target uuid := COALESCE(NEW.transaction_id, OLD.transaction_id);
BEGIN
    UPDATE transactions t
       SET split_count = agg.n,
           split_total = agg.total,
           category_id = CASE WHEN agg.n > 0 THEN NULL ELSE t.category_id END,
           updated_at  = now()
      FROM (SELECT count(*)::smallint AS n,
                   COALESCE(sum(amount), 0)::numeric(14,2) AS total
              FROM transaction_splits WHERE transaction_id = target) AS agg
     WHERE t.id = target;
    RETURN NULL;
END;
$$;
"""

# La única función autorizada a escribir `depth`, `path_ids` y `sort_key`. Se
# recalcula el hogar completo: con 120 filas es más barato que razonar sobre qué
# parte hace falta, y elimina la posibilidad de dejar una rama sin actualizar. El
# `IS DISTINCT FROM` evita escribir filas que no cambian, lo que mantiene pequeño el
# diario de deshacer y no dispara `updated_at` de media tabla.
FUNCION_CATEGORY_PATHS = """
CREATE OR REPLACE FUNCTION refresh_category_paths(p_household_id uuid)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
    affected integer;
BEGIN
    WITH RECURSIVE walk AS (
        SELECT c.id,
               0::smallint                             AS depth,
               ARRAY[c.id]                             AS path_ids,
               lpad(c.sort_order::text, 4, '0')        AS sort_key
          FROM categories c
         WHERE c.household_id = p_household_id
           AND c.parent_id IS NULL
        UNION ALL
        SELECT c.id,
               (w.depth + 1)::smallint,
               w.path_ids || c.id,
               w.sort_key || '.' || lpad(c.sort_order::text, 4, '0')
          FROM categories c
          JOIN walk w ON c.parent_id = w.id
         WHERE c.household_id = p_household_id
    )
    UPDATE categories c
       SET depth = w.depth, path_ids = w.path_ids, sort_key = w.sort_key
      FROM walk w
     WHERE c.id = w.id
       AND (c.depth, c.path_ids, c.sort_key)
           IS DISTINCT FROM (w.depth, w.path_ids, w.sort_key);

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END;
$$;
"""

# Todo informe de gasto parte de aquí: la disyunción «simple o repartida» y la
# inversión del signo están escritas una sola vez en todo el sistema. Las dos ramas
# son disjuntas por `ck_transactions_split_invariant`, que es lo que hace correcto
# un UNION ALL sin deduplicar.
VISTA_MOVIMIENTOS = """
CREATE VIEW vw_movement_lines AS
SELECT t.id                                     AS transaction_id,
       s.id                                     AS split_id,
       t.household_id,
       t.account_id,
       t.payee_id,
       t.kind,
       t.booked_on,
       date_trunc('month', t.booked_on)::date   AS period_month,
       s.category_id,
       s.amount,
       (-s.amount)                              AS spent,
       t.status,
       t.excluded_from_reports,
       t.currency,
       s.invoice_line_id
  FROM transactions t
  JOIN transaction_splits s ON s.transaction_id = t.id
 WHERE t.split_count > 0
UNION ALL
SELECT t.id,
       NULL::uuid,
       t.household_id,
       t.account_id,
       t.payee_id,
       t.kind,
       t.booked_on,
       date_trunc('month', t.booked_on)::date,
       t.category_id,
       t.amount,
       (-t.amount),
       t.status,
       t.excluded_from_reports,
       t.currency,
       NULL::uuid
  FROM transactions t
 WHERE t.split_count = 0;
"""

# El LEFT JOIN LATERAL con las tres agregaciones en un solo escaneo hace que la
# vista cueste *un* index-only scan por cuenta, no tres.
VISTA_SALDOS = """
CREATE VIEW vw_account_balances AS
SELECT a.id                                                        AS account_id,
       a.household_id,
       a.type,
       a.account_class,
       a.currency,
       a.opening_balance,
       (a.opening_balance + COALESCE(m.total, 0))::numeric(14,2)    AS working_balance,
       (a.opening_balance + COALESCE(m.cleared_total, 0))::numeric(14,2)
                                                                    AS cleared_balance,
       (a.opening_balance + COALESCE(m.reconciled_total, 0))::numeric(14,2)
                                                                    AS reconciled_balance,
       COALESCE(v.market_value, a.opening_balance + COALESCE(m.total, 0))::numeric(14,2)
                                                                    AS net_worth_value,
       m.movement_count,
       m.last_booked_on
  FROM accounts a
  LEFT JOIN LATERAL (
      SELECT sum(t.amount)                                          AS total,
             sum(t.amount) FILTER (WHERE t.status IN ('cleared', 'reconciled'))
                                                                    AS cleared_total,
             sum(t.amount) FILTER (WHERE t.status = 'reconciled')    AS reconciled_total,
             count(*)                                               AS movement_count,
             max(t.booked_on)                                       AS last_booked_on
        FROM transactions t
       WHERE t.account_id = a.id
  ) m ON true
  LEFT JOIN LATERAL (
      SELECT av.market_value
        FROM account_valuations av
       WHERE av.account_id = a.id
       ORDER BY av.valued_on DESC
       LIMIT 1
  ) v ON a.type = 'investment';
"""

# `full_path` («Vivienda › Suministros › Luz») evita que el cliente tenga que
# reconstruir el árbol para etiquetar una fila de informe.
VISTA_ARBOL = """
CREATE VIEW vw_category_tree AS
SELECT c.household_id,
       c.id,
       c.parent_id,
       c.name,
       c.kind,
       c.depth,
       c.sort_key,
       c.path_ids,
       repeat('  ', c.depth) || c.name                        AS indented_name,
       (SELECT string_agg(a.name, ' › ' ORDER BY p.ord)
          FROM unnest(c.path_ids) WITH ORDINALITY AS p(id, ord)
          JOIN categories a ON a.id = p.id)                   AS full_path,
       NOT EXISTS (SELECT 1 FROM categories ch
                    WHERE ch.parent_id = c.id
                      AND ch.archived_at IS NULL)             AS is_leaf,
       c.archived_at,
       c.merged_into_id
  FROM categories c;
"""

# La única vista materializada: se calcula sobre la tabla más grande, agrupa por mes
# lo que ya es historia inmutable y nadie espera que el gráfico de evolución del
# precio del aceite cambie en el mismo segundo en que sube una factura.
VISTA_PRECIOS_MENSUAL = """
CREATE MATERIALIZED VIEW mv_product_price_monthly AS
SELECT pp.household_id,
       pp.product_id,
       pp.payee_id,
       date_trunc('month', pp.priced_on)::date                   AS period_month,
       min(pp.unit_price)                                        AS min_price,
       max(pp.unit_price)                                        AS max_price,
       avg(pp.unit_price)::numeric(14,4)                         AS avg_price,
       (array_agg(pp.unit_price ORDER BY pp.priced_on DESC))[1]  AS last_price,
       count(*)                                                  AS observations
  FROM product_prices pp
 WHERE NOT pp.is_promotion
 GROUP BY pp.household_id, pp.product_id, pp.payee_id,
          date_trunc('month', pp.priced_on)
WITH DATA;
"""


def upgrade() -> None:
    op.execute(FUNCION_UPDATED_AT)
    for tabla in TABLAS:
        op.execute(
            f"CREATE TRIGGER trg_{tabla}_updated_at "
            f"BEFORE UPDATE ON {tabla} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )

    op.execute(FUNCION_SPLIT_TOTALS)
    op.execute(
        "CREATE TRIGGER trg_transaction_splits_totals "
        "AFTER INSERT OR UPDATE OR DELETE ON transaction_splits "
        "FOR EACH ROW EXECUTE FUNCTION refresh_transaction_split_totals()"
    )

    op.execute(FUNCION_CATEGORY_PATHS)

    op.execute(VISTA_MOVIMIENTOS)
    op.execute(VISTA_SALDOS)
    op.execute(VISTA_ARBOL)
    op.execute(VISTA_PRECIOS_MENSUAL)
    # El índice único es requisito de REFRESH ... CONCURRENTLY, que es como se
    # refresca de noche sin bloquear lecturas.
    op.execute(
        "CREATE UNIQUE INDEX uq_mv_product_price_monthly "
        "ON mv_product_price_monthly (household_id, product_id, payee_id, period_month)"
    )
    op.execute(
        "CREATE INDEX ix_mv_product_price_monthly_product "
        "ON mv_product_price_monthly (household_id, product_id, period_month DESC)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_product_price_monthly")
    op.execute("DROP VIEW IF EXISTS vw_category_tree")
    op.execute("DROP VIEW IF EXISTS vw_account_balances")
    op.execute("DROP VIEW IF EXISTS vw_movement_lines")

    op.execute("DROP FUNCTION IF EXISTS refresh_category_paths(uuid)")
    op.execute("DROP TRIGGER IF EXISTS trg_transaction_splits_totals ON transaction_splits")
    op.execute("DROP FUNCTION IF EXISTS refresh_transaction_split_totals()")

    for tabla in TABLAS:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tabla}_updated_at ON {tabla}")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
