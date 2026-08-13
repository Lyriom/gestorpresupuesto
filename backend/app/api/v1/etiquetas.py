"""Etiquetas libres (§3.10, F-35).

La etiqueta es transversal a la temática: «viaje a Roma» cruza transporte,
alojamiento y restaurantes. Por eso el borrado de una etiqueta desvincula pero
nunca toca el dinero, al contrario que una temática.

El esquema guarda el color como `color_slot` (1 a 12), no como hexadecimal,
porque la paleta categórica del design system es cerrada y accesible en los dos
temas. El contrato habla en hexadecimal, así que aquí se traduce en los dos
sentidos con la paleta documentada en `docs/ux/design-system.md` §2.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import delete, func, select, text, update

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, verificar_csrf
from app.api.v1.transacciones import contar, del_hogar, texto_plano
from app.core.config import settings
from app.core.errors import Conflicto
from app.models.transaccion import Tag, TransactionTag
from app.schemas.comun import Pagina
from app.schemas.etiqueta import (
    EtiquetaActualizar,
    EtiquetaCrear,
    EtiquetaFiltro,
    EtiquetaFusionCrear,
    EtiquetaRespuesta,
)
from app.services.normalizacion import sin_acentos

# Las rutas llevan su prefijo completo (`/tags`), así que el agregador
# incluye este router sin `prefix`. `verificar_csrf` va en el router porque no
# hace nada en GET, HEAD ni OPTIONS: así no se puede olvidar en un endpoint.
router = APIRouter(tags=["tags"], dependencies=[Depends(verificar_csrf)])

CERO = Decimal("0.00")
DIAS_PARA_DESHACER = 30

#: Paleta categórica del design system (§2, tema oscuro), en orden de slot.
PALETA: tuple[str, ...] = (
    "#568ef9",
    "#c2520b",
    "#02a6ad",
    "#ce3344",
    "#3fac4a",
    "#b343ad",
    "#ac9008",
    "#6f5ddf",
    "#20a888",
    "#9d6000",
    "#d36c9d",
    "#026fb9",
)


def _color_de(slot: int | None) -> str | None:
    return PALETA[slot - 1] if slot and 1 <= slot <= len(PALETA) else None


def _slot_de(color: str | None) -> int | None:
    """El slot cuyo color está más cerca del hexadecimal pedido.

    Se compara en RGB porque la interfaz manda un color libre y el esquema solo
    admite uno de los doce; elegir el más parecido conserva la intención sin
    inventar una columna nueva.
    """
    if not color:
        return None
    objetivo = tuple(int(color[indice : indice + 2], 16) for indice in (1, 3, 5))
    mejor, distancia_minima = 1, None
    for indice, candidato in enumerate(PALETA, start=1):
        rgb = tuple(int(candidato[posicion : posicion + 2], 16) for posicion in (1, 3, 5))
        distancia = sum((a - b) ** 2 for a, b in zip(objetivo, rgb, strict=True))
        if distancia_minima is None or distancia < distancia_minima:
            mejor, distancia_minima = indice, distancia
    return mejor


def _normalizar(nombre: str) -> str:
    return sin_acentos(nombre).lower().strip()


async def _nombre_libre(alcance: AlcanceHogar, nombre: str, excluir: uuid.UUID | None) -> None:
    consulta = select(Tag.id).where(
        Tag.household_id == alcance.household_id,
        Tag.normalized_name == _normalizar(nombre),
        Tag.archived_at.is_(None),
    )
    if excluir is not None:
        consulta = consulta.where(Tag.id != excluir)
    if (await alcance.sesion.scalar(consulta)) is not None:
        raise Conflicto(f"Ya tienes una etiqueta «{nombre}».", codigo="nombre_duplicado")


def _respuesta(etiqueta: Tag, estadisticas: tuple[int, Decimal] | None = None) -> EtiquetaRespuesta:
    return EtiquetaRespuesta(
        id=etiqueta.id,
        name=etiqueta.name,
        color=_color_de(etiqueta.color_slot),
        created_at=etiqueta.created_at,
        transactions_count=estadisticas[0] if estadisticas else None,
        total_amount=estadisticas[1] if estadisticas else None,
    )


async def _estadisticas_de(
    alcance: AlcanceHogar, ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, Decimal]]:
    """Movimientos y gasto por etiqueta: «cuánto me ha costado el viaje a Roma»."""
    if not ids:
        return {}
    filas = await alcance.sesion.execute(
        text(
            """
            SELECT tt.tag_id,
                   COUNT(DISTINCT m.transaction_id)       AS movimientos,
                   COALESCE(SUM(m.spent), 0)::numeric(14,2) AS gastado
              FROM transaction_tags tt
              JOIN vw_movement_lines m ON m.transaction_id = tt.transaction_id
             WHERE tt.household_id = :hogar
               AND tt.tag_id = ANY(:etiquetas)
               AND m.kind <> 'transfer'
               AND NOT m.excluded_from_reports
             GROUP BY tt.tag_id
            """
        ),
        {"hogar": alcance.household_id, "etiquetas": ids},
    )
    return {fila.tag_id: (fila.movimientos, Decimal(fila.gastado)) for fila in filas}


@router.get("/tags", summary="Etiquetas con contador de uso")
async def listar_etiquetas(
    alcance: Alcance,
    filtro: Annotated[EtiquetaFiltro, Query()],
) -> Pagina[EtiquetaRespuesta]:
    consulta = select(Tag).where(
        Tag.household_id == alcance.household_id, Tag.archived_at.is_(None)
    )
    if filtro.q:
        consulta = consulta.where(texto_plano(Tag.name).like(f"%{_normalizar(filtro.q)}%"))

    total = await contar(alcance, consulta)
    columnas = {
        "name": Tag.name,
        "transactions_count": Tag.usage_count,
        "total_amount": Tag.usage_count,
        "created_at": Tag.created_at,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is not None:
            consulta = consulta.order_by(columna.desc() if descendente else columna.asc())
    consulta = consulta.order_by(Tag.id.desc())

    filas = list(
        (await alcance.sesion.execute(consulta.offset(filtro.desplazamiento).limit(filtro.size)))
        .scalars()
        .all()
    )
    estadisticas = (
        await _estadisticas_de(alcance, [fila.id for fila in filas])
        if "stats" in filtro.include
        else {}
    )
    items = [_respuesta(fila, estadisticas.get(fila.id)) for fila in filas]
    return Pagina.crear(items, page=filtro.page, size=filtro.size, total=total)


@router.post("/tags", status_code=status.HTTP_201_CREATED, summary="Crea una etiqueta")
async def crear_etiqueta(
    alcance: AlcanceEscritura, datos: EtiquetaCrear, respuesta: Response
) -> EtiquetaRespuesta:
    await _nombre_libre(alcance, datos.name, None)
    etiqueta = Tag(
        household_id=alcance.household_id,
        name=datos.name,
        normalized_name=_normalizar(datos.name),
        color_slot=_slot_de(datos.color),
    )
    alcance.sesion.add(etiqueta)
    await alcance.sesion.commit()
    await alcance.sesion.refresh(etiqueta)
    respuesta.headers["Location"] = f"{settings.api_prefix}/tags/{etiqueta.id}"
    return _respuesta(etiqueta)


@router.post("/tags/merge", summary="Fusiona etiquetas duplicadas")
async def fusionar_etiquetas(
    alcance: AlcanceEscritura, datos: EtiquetaFusionCrear
) -> EtiquetaRespuesta:
    destino = await del_hogar(alcance, Tag, datos.target_id, mensaje="La etiqueta no existe.")
    origenes = [
        await del_hogar(alcance, Tag, identificador, mensaje="La etiqueta no existe.")
        for identificador in datos.source_ids
    ]
    ids = [origen.id for origen in origenes]

    # Las transacciones que ya tienen la destino solo pierden la de origen; las
    # demás se reasignan. El orden importa: al revés, el UNIQUE saltaría.
    ya = select(TransactionTag.transaction_id).where(TransactionTag.tag_id == destino.id)
    await alcance.sesion.execute(
        delete(TransactionTag).where(
            TransactionTag.household_id == alcance.household_id,
            TransactionTag.tag_id.in_(ids),
            TransactionTag.transaction_id.in_(ya),
        )
    )
    await alcance.sesion.execute(
        update(TransactionTag)
        .where(
            TransactionTag.household_id == alcance.household_id,
            TransactionTag.tag_id.in_(ids),
        )
        .values(tag_id=destino.id)
    )

    # No se registra la fusión en `merge_operations`: su `entity_type` solo admite
    # `category`, `payee` y `product`, y forzar uno ajeno haría ilegible la
    # bitácora. La fusión de etiquetas, además, no reasigna dinero.
    for origen in origenes:
        await alcance.sesion.delete(origen)

    destino.usage_count = int(
        await alcance.sesion.scalar(
            select(func.count())
            .select_from(TransactionTag)
            .where(TransactionTag.tag_id == destino.id)
        )
        or 0
    )
    await alcance.sesion.commit()
    await alcance.sesion.refresh(destino)
    return _respuesta(destino)


@router.patch("/tags/{etiqueta_id}", summary="Renombra o cambia el color")
async def editar_etiqueta(
    alcance: AlcanceEscritura, etiqueta_id: uuid.UUID, datos: EtiquetaActualizar
) -> EtiquetaRespuesta:
    etiqueta = await del_hogar(alcance, Tag, etiqueta_id, mensaje="La etiqueta no existe.")
    campos = datos.model_dump(exclude_unset=True)
    if datos.name:
        await _nombre_libre(alcance, datos.name, etiqueta.id)
        etiqueta.name = datos.name
        etiqueta.normalized_name = _normalizar(datos.name)
    if "color" in campos:
        etiqueta.color_slot = _slot_de(datos.color)
    await alcance.sesion.commit()
    await alcance.sesion.refresh(etiqueta)
    return _respuesta(etiqueta)


@router.delete(
    "/tags/{etiqueta_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra la etiqueta y sus vínculos",
)
async def borrar_etiqueta(alcance: AlcanceEscritura, etiqueta_id: uuid.UUID) -> Response:
    """No borra transacciones: una etiqueta es metadato, no dinero."""
    etiqueta = (
        await alcance.sesion.execute(
            select(Tag).where(Tag.household_id == alcance.household_id, Tag.id == etiqueta_id)
        )
    ).scalar_one_or_none()
    if etiqueta is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await alcance.sesion.delete(etiqueta)
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
