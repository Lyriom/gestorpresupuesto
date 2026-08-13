"""Piezas que se repiten en casi todas las tablas de dominio."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CHAR, ForeignKey, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey

# Divisa por defecto de toda la instalación. El multidivisa (F-52) es P2, pero la
# columna existe desde el día uno para no tener que rellenarla a posteriori.
MONEDA_POR_DEFECTO = "EUR"

# Se repite en seis tablas; escrito una vez para que no se escriba mal en ninguna.
CHECK_MONEDA = "currency ~ '^[A-Z]{3}$'"


class HouseholdScoped:
    """`household_id` con su índice y su cascada, idéntico en 34 tablas.

    Se declara una sola vez para que ninguna tabla de dominio pueda olvidarse de
    la columna que sostiene la multi-tenencia.
    """

    @declared_attr
    def household_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            UUID(as_uuid=True),
            ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


class DomainBase(UUIDPrimaryKey, Timestamps, HouseholdScoped, Base):
    """Base de las tablas de dominio: id UUID, marcas de tiempo y tenencia."""

    __abstract__ = True


class GlobalBase(UUIDPrimaryKey, Timestamps, Base):
    """Base de las tablas que no pertenecen a un hogar (`users`, plantillas...)."""

    __abstract__ = True


def columna_moneda() -> Mapped[str]:
    """Divisa ISO 4217 en `CHAR(3)`; el `CHECK` se añade en cada tabla."""
    return mapped_column(CHAR(3), nullable=False, server_default=MONEDA_POR_DEFECTO)


def uuid_fk(objetivo: str, *, ondelete: str, nullable: bool = True, **kwargs: Any) -> Any:
    """Clave ajena UUID. `ondelete` es obligatorio para que se decida siempre."""
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey(objetivo, ondelete=ondelete),
        nullable=nullable,
        **kwargs,
    )


# Tablas que declaran UNIQUE (household_id, id) y por tanto pueden ser destino de
# una clave ajena compuesta (secciones 2.5, 2.7, 2.10, 2.11, 2.16, 2.22 y 2.24).
DESTINOS_COMPUESTOS = (
    "categories",
    "accounts",
    "payees",
    "transactions",
    "budget_periods",
    "invoices",
    "products",
)


def fk_tenencia(tabla: str, columna: str, destino: str, *, ondelete: str) -> ForeignKeyConstraint:
    """FK compuesta `(household_id, columna)` → `destino(household_id, id)`.

    Es la capa que hace **imposible** que una fila referencie a otra de un hogar
    distinto: el filtro del repositorio protege las lecturas, pero solo esto
    protege las escrituras.

    Con `MATCH SIMPLE` (el comportamiento por omisión) la restricción no se
    comprueba si alguna de sus columnas es `NULL`, así que se aplica exactamente
    cuando hay referencia. En `SET NULL` se nombra la columna a vaciar, porque
    `household_id` es `NOT NULL` y anularla haría fallar el borrado.
    """
    if destino not in DESTINOS_COMPUESTOS:
        raise ValueError(
            f"{destino} no declara UNIQUE (household_id, id): no puede ser destino de "
            "una clave ajena compuesta."
        )
    accion = f"SET NULL ({columna})" if ondelete.upper() == "SET NULL" else ondelete
    return ForeignKeyConstraint(
        ["household_id", columna],
        [f"{destino}.household_id", f"{destino}.id"],
        ondelete=accion,
        name=f"fk_{tabla}_household_id_{columna}",
    )
