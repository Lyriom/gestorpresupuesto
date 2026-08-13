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

# Precios unitarios: las facturas de luz, gas y telefonía traen 4-6 decimales.
# Redondear a céntimos falsearía el histórico de precios (F-15, F-16, F-38).
UnitPrice = Numeric(14, 4)

# Cantidades: 3,472 kWh, 0,850 kg, 12 uds.
Quantity = Numeric(14, 4)

# Confianza del parser y puntuaciones de similitud, 0..1 y 0..100.
Confidence = Numeric(4, 3)
Score = Numeric(5, 2)

# Porcentajes de variación: ±99999,99 % cubre cualquier subida sin desbordar.
Percentage = Numeric(7, 2)

# Tipos de interés nominales: 3,4500 % se guarda con cuatro decimales.
Rate = Numeric(7, 4)


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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


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
