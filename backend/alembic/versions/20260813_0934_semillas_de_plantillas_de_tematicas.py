"""Semillas: el árbol de temáticas por defecto en `category_templates`.

Va aparte porque es una migración de **datos**, no de esquema: tiene que poder
repetirse sin duplicar y tiene que poder revertirse sin llevarse por delante datos
del usuario.

El catálogo se importa de `app.db.semillas` en lugar de copiarse aquí: son 102 filas
y tenerlas en dos sitios garantiza que un día divergirían. El precio es que esta
revisión escribe el catálogo *vigente*, no el que existía el día en que se escribió;
se acepta porque `ON CONFLICT DO UPDATE` está pensado precisamente para que una
versión posterior corrija un icono o un nombre.

Revision ID: e6b5a0f2a8c3
Revises: 3f6b7dd10b1e
Create Date: 2026-08-13 09:34:33.278863

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.semillas import VERSION_CATALOGO, filas_de_plantillas
from app.models.categoria import CategoryTemplate

revision: str = "e6b5a0f2a8c3"
down_revision: str | None = "3f6b7dd10b1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conexion = op.get_bind()
    filas = filas_de_plantillas()
    tabla = CategoryTemplate.__table__
    # Por niveles: `parent_key` es una FK a `template_key` con RESTRICT, así que las
    # raíces tienen que existir antes que sus hijas.
    for profundidad in sorted({fila["depth"] for fila in filas}):
        nivel = [fila for fila in filas if fila["depth"] == profundidad]
        sentencia = sa.dialects.postgresql.insert(tabla).values(nivel)
        conexion.execute(
            sentencia.on_conflict_do_update(
                index_elements=["template_key"],
                set_={
                    "parent_key": sentencia.excluded.parent_key,
                    "name": sentencia.excluded.name,
                    "kind": sentencia.excluded.kind,
                    "icon": sentencia.excluded.icon,
                    "color_slot": sentencia.excluded.color_slot,
                    "sort_order": sentencia.excluded.sort_order,
                    "depth": sentencia.excluded.depth,
                    "updated_at": sa.func.now(),
                },
            )
        )


def downgrade() -> None:
    # Solo se borran las plantillas, **nunca** las temáticas copiadas a un hogar: las
    # temáticas de un hogar son datos del usuario y una migración a la baja no puede
    # borrarle su historia. Las hijas primero, por la FK con RESTRICT.
    op.execute(
        f"DELETE FROM category_templates "
        f"WHERE version = {VERSION_CATALOGO} AND parent_key IS NOT NULL"
    )
    op.execute(
        f"DELETE FROM category_templates WHERE version = {VERSION_CATALOGO} AND parent_key IS NULL"
    )
