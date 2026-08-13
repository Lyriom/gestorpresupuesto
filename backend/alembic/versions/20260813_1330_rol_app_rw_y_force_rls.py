"""Rol `app_rw` y `FORCE ROW LEVEL SECURITY`: la tercera capa deja de ser decorativa.

La revisión `3f6b7dd10b1e` creó 34 políticas de tenencia y las dejó **inertes**: sin
`FORCE`, y con la aplicación conectada como propietaria de las tablas, que en
PostgreSQL está exenta de sus propias políticas. El aislamiento lo sostenían solo las
otras dos capas (el filtro de cada repositorio y las claves ajenas compuestas).

Aquí se cierra, y se cierra **sin pedir un segundo usuario de base de datos**: en
EasyPanel solo hay uno. En lugar de conectarse con otro rol, la aplicación se
*cambia* a uno con `SET LOCAL ROLE` en cada petición:

* `app_rw` es `NOLOGIN` y no tiene contraseña: nadie se conecta con él, solo se llega
  desde el propietario, que es miembro suyo. No tiene `BYPASSRLS` ni es superusuario,
  así que las políticas **sí** le aplican aunque no hubiera `FORCE`.
* Al ser `LOCAL`, el cambio se deshace al terminar la transacción. Las migraciones y
  cualquier tarea de mantenimiento siguen corriendo como propietario.

Tres cosas que no estaban previstas y sin las cuales esto no funciona:

1. **La condición de las políticas se reescribe.** `current_setting('app.household_id',
   true)` devuelve `NULL` solo la primera vez; en cuanto una transacción la ha fijado
   con `set_config(..., true)` y ha terminado, la variable se queda en la **cadena
   vacía**, y `''::uuid` no es NULL: es `ERROR: invalid input syntax for type uuid`.
   Con el pool de conexiones eso significa que la segunda petición de cada conexión
   reventaría antes de fijar el hogar, en lugar de no ver nada. `nullif(..., '')` lo
   convierte en el `NULL` que la comparación necesita para filtrar todo.
2. **Las tres vistas pasan a `security_invoker = true`.** Una vista normal consulta
   sus tablas con los permisos —y las políticas— de **su propietario**, que aquí es el
   dueño de las tablas. `vw_movement_lines` es de donde salen presupuestos, informes,
   temáticas y comercios: sin esto, todo el gasto se seguiría leyendo sin filtrar por
   mucho `SET ROLE` que hiciera la aplicación.
3. **`mv_product_price_monthly` se queda sin permiso a propósito.** Una vista
   materializada es una tabla física con datos ya calculados: no admite
   `security_invoker` y no hay política que la filtre, así que concederle `SELECT`
   sería abrir la puerta que se acaba de cerrar. Hoy no la lee nadie (`grep` en
   `app/`); el día que haga falta, o lleva su propia política, o se consulta desde un
   endpoint que filtre por hogar y se le conceda entonces.

`users`, `households`, `refresh_tokens` y `household_members` siguen **sin política de
hogar**, igual que en `3f6b7dd10b1e`: hay que poder leerlas y escribirlas *antes* de
saber en qué hogar entra la sesión, que es justo lo que decide `app.household_id`. El
registro y el inicio de sesión solo tocan esas cuatro, así que ese camino no lo puede
bloquear ninguna política. `category_templates` es el catálogo de la instalación: la
aplicación solo lo lee.

Revision ID: 9a1c4f27b8d5
Revises: e6b5a0f2a8c3
Create Date: 2026-08-13 13:30:11.402118

"""

from collections.abc import Sequence

from alembic import op

revision: str = "9a1c4f27b8d5"
down_revision: str | None = "e6b5a0f2a8c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Debe coincidir con `app.db.session.ROL_APLICACION`.
ROL = "app_rw"

# Tablas de dominio con `household_id NOT NULL`. Copiadas tal cual de la revisión que
# creó las políticas: una migración no importa las listas del código de la aplicación,
# que cambia, sino que congela el esquema del día en que se escribió.
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

# `household_id` puede ser NULL y ese NULL significa «de la instalación, no de un
# hogar»: las plantillas de extracción de serie y los eventos de autenticación
# anteriores a tener hogar.
TABLAS_CON_FILAS_GLOBALES = ("audit_log", "extraction_templates")

# Sin política de hogar, pero la aplicación las escribe: invitaciones, ajustes del
# hogar, cambio de contraseña, cierre de sesión, borrado de cuenta.
TABLAS_SIN_POLITICA = ("household_members", "households", "refresh_tokens", "users")

#: Catálogo de la instalación: lo escriben las migraciones, la aplicación solo lee.
TABLAS_DE_SOLO_LECTURA = ("category_templates",)

#: Vistas normales. Pasan a `security_invoker` para que el RLS sea el de quien
#: consulta y no el de su propietario.
VISTAS = ("vw_account_balances", "vw_category_tree", "vw_movement_lines")

CONDICION = "household_id = nullif(current_setting('app.household_id', true), '')::uuid"
CONDICION_GLOBAL = f"household_id IS NULL OR {CONDICION}"

# La condición que tenían antes, para que el `downgrade` devuelva la base al estado
# exacto de `3f6b7dd10b1e` y no a una versión mejorada de él.
CONDICION_ANTERIOR = "household_id = current_setting('app.household_id', true)::uuid"
CONDICION_GLOBAL_ANTERIOR = f"household_id IS NULL OR {CONDICION_ANTERIOR}"

# `USING` filtra lo que se puede leer; `WITH CHECK` impide **escribir** una fila de
# otro hogar. Con solo `USING`, un INSERT con `household_id` ajeno pasaría.
POLITICA = """
CREATE POLICY tenant_isolation ON {tabla}
    USING      ({condicion})
    WITH CHECK ({condicion});
"""

# `CREATE ROLE` no admite `IF NOT EXISTS`, y el rol puede existir ya: es un objeto del
# clúster, así que sobrevive a un `downgrade` en otra base de datos del mismo servidor.
CREAR_ROL = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROL}') THEN
        CREATE ROLE {ROL} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                          NOBYPASSRLS NOREPLICATION NOINHERIT;
    END IF;
END
$$;
"""

# `DROP OWNED BY` es lo que quita de verdad los permisos concedidos al rol, y solo los
# de **esta** base de datos: sin él `DROP ROLE` falla en cuanto queda una concesión.
#
# Y ahí está el detalle que hay que tratar con cuidado: un rol es un objeto del
# *clúster*, mientras que la migración es de una base de datos. En un servidor con
# varias bases migradas por el mismo usuario —el portátil de desarrollo, con la de
# desarrollo y las dos efímeras de las pruebas— `DROP ROLE` sigue fallando después del
# `DROP OWNED BY` porque el rol conserva permisos en las otras. Ese caso no puede tumbar
# el `downgrade`: se deja el rol, ya sin nada concedido aquí, y se avisa. En un
# despliegue de una sola base (el caso real) el borrado sí se completa.
#
# La pertenencia (`GRANT app_rw TO CURRENT_USER`) no se revoca aparte a propósito:
# `DROP ROLE` se la lleva sola cuando funciona, y cuando no, revocarla dejaría sin poder
# hacer `SET ROLE` a la aplicación de la otra base de datos que sigue usando el rol.
BORRAR_ROL = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROL}') THEN
        RETURN;
    END IF;

    EXECUTE 'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {ROL}';
    EXECUTE 'REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {ROL}';
    EXECUTE 'REVOKE ALL PRIVILEGES ON SCHEMA public FROM {ROL}';
    EXECUTE 'DROP OWNED BY {ROL}';

    BEGIN
        EXECUTE 'DROP ROLE {ROL}';
    EXCEPTION WHEN dependent_objects_still_exist THEN
        RAISE NOTICE
            'El rol {ROL} se queda: conserva permisos en otra base de datos del mismo '
            'servidor. En esta ya no tiene ninguno.';
    END;
END
$$;
"""

TABLAS_CON_POLITICA = (*TABLAS_DOMINIO, *TABLAS_CON_FILAS_GLOBALES)
TABLAS_ESCRIBIBLES = (*TABLAS_CON_POLITICA, *TABLAS_SIN_POLITICA)


def upgrade() -> None:
    op.execute(CREAR_ROL)
    # Sin esto el propietario no puede hacer `SET ROLE`. Un superusuario podría de
    # todas formas, pero en producción el usuario único de EasyPanel no lo es.
    op.execute(f"GRANT {ROL} TO CURRENT_USER")

    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROL}")
    for tabla in TABLAS_ESCRIBIBLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tabla} TO {ROL}")
    for tabla in TABLAS_DE_SOLO_LECTURA:
        op.execute(f"GRANT SELECT ON {tabla} TO {ROL}")
    # La única secuencia es `merge_operation_changes_seq` (el resto de claves son
    # UUID). Se concede por lote para no volver aquí si mañana hay otra.
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROL}")

    for vista in VISTAS:
        op.execute(f"ALTER VIEW {vista} SET (security_invoker = true)")
        op.execute(f"GRANT SELECT ON {vista} TO {ROL}")

    # Las políticas se rehacen con `nullif`: ver el punto 1 de la cabecera.
    for tabla in TABLAS_DOMINIO:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tabla}")
        op.execute(POLITICA.format(tabla=tabla, condicion=CONDICION))
    for tabla in TABLAS_CON_FILAS_GLOBALES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tabla}")
        op.execute(POLITICA.format(tabla=tabla, condicion=CONDICION_GLOBAL))

    # Con `FORCE` tampoco se libra el propietario. Es un cinturón por si algún día
    # una tarea suelta escribe sin haber hecho `SET ROLE`: lo que aísla de verdad a
    # la aplicación es ser `app_rw`, que no es dueño de nada.
    for tabla in TABLAS_CON_POLITICA:
        op.execute(f"ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for tabla in TABLAS_CON_POLITICA:
        op.execute(f"ALTER TABLE {tabla} NO FORCE ROW LEVEL SECURITY")

    for tabla in TABLAS_DOMINIO:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tabla}")
        op.execute(POLITICA.format(tabla=tabla, condicion=CONDICION_ANTERIOR))
    for tabla in TABLAS_CON_FILAS_GLOBALES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tabla}")
        op.execute(POLITICA.format(tabla=tabla, condicion=CONDICION_GLOBAL_ANTERIOR))

    for vista in VISTAS:
        op.execute(f"ALTER VIEW {vista} RESET (security_invoker)")

    op.execute(BORRAR_ROL)
