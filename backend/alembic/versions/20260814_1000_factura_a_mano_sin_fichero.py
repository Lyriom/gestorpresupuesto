"""Una factura metida a mano no tiene fichero.

Hasta ahora una `invoices` **siempre** venía de un PDF subido, y las cuatro columnas
del documento (`file_name`, `storage_key`, `byte_size`, `content_sha256`) eran
`NOT NULL`. Para meter una factura a mano —un ticket de papel, una compra de la que
no hay PDF— hacía falta o inventarse esos valores o no poder hacerlo.

Inventárselos era la salida fácil y la mala: un `storage_key` vacío o de mentira deja
al endpoint de descarga y al de reprocesar apuntando a un fichero que no existe, y el
fallo aparece meses después, al pulsar «ver original» de una factura de hace un año.

Así que en lugar de **aflojar** la invariante se **cambia**: antes era «toda factura
tiene fichero» y ahora es «tiene fichero si y solo si vino de un fichero». Las cuatro
columnas pasan a admitir nulo, pero una restricción nueva exige que estén las cuatro
cuando el origen es `upload`, `email` o `api`, y que no esté ninguna cuando es
`manual`. Una factura subida sin su documento sigue siendo imposible, que es lo que la
regla original protegía de verdad.

`source` gana el valor `manual`. `extraction_method` no se toca: `ninguno` ya
describe exactamente lo que ha pasado, que es que nadie ha extraído nada.
"""

from __future__ import annotations

from alembic import op

revision: str = "b2d4e7a19c05"
down_revision: str | None = "9a1c4f27b8d5"
branch_labels: str | None = None
depends_on: str | None = None

COLUMNAS_DEL_FICHERO = ("file_name", "storage_key", "byte_size", "content_sha256")

#: Las cuatro van juntas o no va ninguna, y cuál de los dos casos toca lo decide el
#: origen. Se escribe con `num_nulls` en vez de con cuatro `IS NULL` encadenados
#: porque así la condición dice lo que se quiere decir: «las cuatro o ninguna».
CHECK_FICHERO = """
    (source = 'manual' AND num_nulls(file_name, storage_key, byte_size, content_sha256) = 4)
    OR
    (source <> 'manual' AND num_nulls(file_name, storage_key, byte_size, content_sha256) = 0)
"""


def upgrade() -> None:
    for columna in COLUMNAS_DEL_FICHERO:
        op.alter_column("invoices", columna, nullable=True)

    # El CHECK de `source` es el que impide guardar 'manual', así que se rehace antes
    # de añadir el nuevo; si no, la primera factura a mano fallaría por el viejo.
    op.drop_constraint(op.f("ck_invoices_source"), "invoices", type_="check")
    op.create_check_constraint(
        op.f("ck_invoices_source"), "invoices", "source IN ('upload', 'email', 'api', 'manual')"
    )
    op.create_check_constraint(
        op.f("ck_invoices_fichero_si_y_solo_si_subida"), "invoices", CHECK_FICHERO
    )


def downgrade() -> None:
    # Las facturas metidas a mano no caben en el esquema anterior: no tienen fichero
    # y no hay ninguno que inventarles. Se borran, que es lo único honesto, y el
    # `CASCADE` de `invoice_lines` se lleva sus líneas.
    op.execute("DELETE FROM invoices WHERE source = 'manual'")

    op.drop_constraint(op.f("ck_invoices_fichero_si_y_solo_si_subida"), "invoices", type_="check")
    op.drop_constraint(op.f("ck_invoices_source"), "invoices", type_="check")
    op.create_check_constraint(
        op.f("ck_invoices_source"), "invoices", "source IN ('upload', 'email', 'api')"
    )

    for columna in COLUMNAS_DEL_FICHERO:
        op.alter_column("invoices", columna, nullable=False)
