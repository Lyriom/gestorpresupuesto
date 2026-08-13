"""Clase base declarativa y mixins comunes a todos los modelos."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, MetaData, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Convención de nombres para que Alembic genere migraciones deterministas y las
# restricciones tengan nombres estables (imprescindible para poder borrarlas).
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Todo importe monetario usa este tipo: nunca float, para no arrastrar errores
# de redondeo en los saldos.
Money = Numeric(14, 2)


class Base(DeclarativeBase):
    """Base declarativa con la convención de nombres aplicada."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {  # noqa: RUF012
        Decimal: Money,
        datetime: DateTime(timezone=True),
    }


class UUIDPrimaryKey:
    """Clave primaria UUID generada en la aplicación.

    Se usa UUID en lugar de un entero secuencial para que los identificadores no
    sean adivinables desde la URL y para poder crear entidades relacionadas sin
    ida y vuelta a la base de datos.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class Timestamps:
    """Marcas de tiempo de creación y última modificación."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
