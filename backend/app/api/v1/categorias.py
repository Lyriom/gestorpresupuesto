"""Temáticas jerárquicas y su fusión: §3.4 del contrato.

El árbol usa lista de adyacencia (`parent_id`) como única fuente de verdad más tres
columnas derivadas (`depth`, `path_ids`, `sort_key`) que son caché reconstruible.
La única función autorizada a escribir esa caché es `refresh_category_paths()`, así
que todo endpoint que cambie la forma del árbol la llama al final y ninguno calcula
rutas por su cuenta.

`ck_categories_path_consistent` no es diferible, de modo que el `INSERT` de una
temática nueva ya tiene que traer su ruta correcta: se calcula en Python a partir
de la de la madre, igual que hace `app/db/semillas.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import func, select, text

from app.api.deps import (
    Alcance,
    AlcanceEscritura,
    AlcanceHogar,
    PaginacionActual,
    verificar_csrf,
)
from app.core.config import settings
from app.core.errors import Conflicto, NoEncontrado, ReglaDeNegocio, SinPermiso
from app.models.categoria import Category
from app.models.fusion import MergeOperation
from app.models.presupuesto import BudgetAllocation, BudgetPeriod
from app.schemas.categoria import (
    PROFUNDIDAD_MAXIMA,
    CategoriaActualizar,
    CategoriaCrear,
    CategoriaFiltro,
    CategoriaFusionCrear,
    CategoriaFusionPreviaRespuesta,
    CategoriaFusionRespuesta,
    CategoriaFusionResultadoRespuesta,
    CategoriaMoverCrear,
    CategoriaNodoRespuesta,
    CategoriaRefRespuesta,
    CategoriaReordenarCrear,
    CategoriaRespuesta,
    CategoriaUsoRespuesta,
    TipoTematica,
)
from app.schemas.comun import Pagina
from app.services.fusion import (
    OpcionesFusion,
    ResumenFusion,
    deshacer,
    fusionar,
    previsualizar,
)
from app.services.normalizacion import sin_acentos

router = APIRouter(tags=["categories"])

CERO = Decimal("0.00")

#: Doce ranuras de la paleta categórica (sistema de diseño §2.4).
RANURAS = 12


def _clave_de_nombre(nombre: str) -> str:
    """RN-12: la unicidad entre hermanas ignora acentos y mayúsculas."""
    return sin_acentos(nombre).casefold().strip()


def _ruta(tematica: Category) -> str:
    return "/".join(str(identificador) for identificador in tematica.path_ids or [tematica.id])


def _rollover(tematica: Category) -> bool:
    return tematica.default_rollover_mode not in (None, "none")


# --------------------------------------------------------------------------- #
# Lectura del árbol
# --------------------------------------------------------------------------- #


async def _arbol_del_hogar(
    alcance: AlcanceHogar, *, incluir_archivadas: bool = False
) -> list[Category]:
    """Todas las temáticas vivas del hogar, en orden de recorrido del árbol.

    Las lápidas de fusión (`merged_into_id`) quedan siempre fuera: son invisibles
    en cualquier flujo de alta, que es justo lo que las hace inocuas.
    """
    condiciones = [
        Category.household_id == alcance.household_id,
        Category.merged_into_id.is_(None),
    ]
    if not incluir_archivadas:
        condiciones.append(Category.archived_at.is_(None))
    return list(
        (
            await alcance.sesion.execute(
                select(Category)
                .where(*condiciones)
                .order_by(Category.sort_key, Category.id)
                # El archivado y la fusión escriben con SQL crudo: sin esto el mapa
                # de identidad devolvería la versión anterior de la fila.
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def _estadisticas(
    alcance: AlcanceHogar, periodo: str | None
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, Decimal], dict[uuid.UUID, Decimal]]:
    """Movimientos, gastado y asignado por temática, opcionalmente de un mes.

    Se leen de `vw_movement_lines`, que es donde está escrita una sola vez la
    disyunción «transacción simple o repartida» y la inversión del signo.
    """
    # asyncpg exige un `date` de verdad: el parámetro se compara con una columna
    # `date`, así que una cadena ISO no le sirve.
    mes = date.fromisoformat(f"{periodo}-01") if periodo else None
    filas = await alcance.sesion.execute(
        text(
            """
            SELECT category_id, count(*) AS cuantas, COALESCE(sum(spent), 0) AS gastado
              FROM vw_movement_lines
             WHERE household_id = :hogar
               AND category_id IS NOT NULL
               AND kind <> 'transfer'
               AND NOT excluded_from_reports
               AND (cast(:mes as date) IS NULL OR period_month = cast(:mes as date))
             GROUP BY category_id
            """
        ),
        {"hogar": alcance.household_id, "mes": mes},
    )
    cuantas: dict[uuid.UUID, int] = {}
    gastado: dict[uuid.UUID, Decimal] = {}
    for fila in filas:
        cuantas[fila.category_id] = fila.cuantas
        gastado[fila.category_id] = Decimal(str(fila.gastado))

    consulta = select(
        BudgetAllocation.category_id, func.sum(BudgetAllocation.allocated_amount)
    ).where(BudgetAllocation.household_id == alcance.household_id)
    if periodo:
        consulta = consulta.join(
            BudgetPeriod, BudgetPeriod.id == BudgetAllocation.budget_period_id
        ).where(BudgetPeriod.period_month == date.fromisoformat(f"{periodo}-01"))
    consulta = consulta.group_by(BudgetAllocation.category_id)
    asignado = {
        fila[0]: Decimal(str(fila[1])) for fila in (await alcance.sesion.execute(consulta)).all()
    }
    return cuantas, gastado, asignado


def _respuesta(
    tematica: Category,
    *,
    por_id: dict[uuid.UUID, Category],
    hijas: dict[uuid.UUID | None, list[Category]],
    descendientes: dict[uuid.UUID, int],
    estadisticas: tuple[dict[uuid.UUID, int], dict[uuid.UUID, Decimal], dict[uuid.UUID, Decimal]]
    | None = None,
) -> CategoriaRespuesta:
    antepasados = [
        CategoriaRefRespuesta(
            id=identificador,
            name=por_id[identificador].name,
            color=por_id[identificador].color_hex,
        )
        for identificador in (tematica.path_ids or [])[:-1]
        if identificador in por_id
    ]
    extra: dict[str, Any] = {}
    if estadisticas is not None:
        cuantas, gastado, asignado = estadisticas
        extra = {
            "transactions_count": cuantas.get(tematica.id, 0),
            "spent": gastado.get(tematica.id, CERO),
            "allocated": asignado.get(tematica.id, CERO),
        }
    return CategoriaRespuesta(
        id=tematica.id,
        created_at=tematica.created_at,
        updated_at=tematica.updated_at,
        name=tematica.name,
        parent_id=tematica.parent_id,
        kind=TipoTematica(tematica.kind),
        path=_ruta(tematica),
        depth=tematica.depth,
        position=tematica.sort_order,
        color=tematica.color_hex,
        icon=tematica.icon,
        rollover_enabled=_rollover(tematica),
        is_locked=tematica.is_locked,
        is_archived=tematica.archived_at is not None,
        is_default=tematica.is_system,
        monthly_target=tematica.monthly_target,
        children_count=len(hijas.get(tematica.id, ())),
        descendants_count=descendientes.get(tematica.id, 0),
        ancestors=antepasados,
        **extra,
    )


def _indices(
    tematicas: list[Category],
) -> tuple[dict[uuid.UUID, Category], dict[uuid.UUID | None, list[Category]], dict[uuid.UUID, int]]:
    por_id = {t.id: t for t in tematicas}
    hijas: dict[uuid.UUID | None, list[Category]] = {}
    for tematica in tematicas:
        hijas.setdefault(tematica.parent_id, []).append(tematica)
    # `path_ids` ya materializa el subárbol: contar descendientes es una pasada.
    descendientes: dict[uuid.UUID, int] = dict.fromkeys(por_id, 0)
    for tematica in tematicas:
        for antepasado in (tematica.path_ids or [])[:-1]:
            if antepasado in descendientes:
                descendientes[antepasado] += 1
    return por_id, hijas, descendientes


@router.get("/categories", response_model=Pagina[CategoriaRespuesta], summary="Listar temáticas")
async def listar(
    alcance: Alcance,
    paginacion: PaginacionActual,
    filtro: Annotated[CategoriaFiltro, Depends()],
) -> Pagina[CategoriaRespuesta]:
    """Lista plana con ruta, profundidad y —si se piden— contadores de uso."""
    todas = await _arbol_del_hogar(alcance, incluir_archivadas=True)
    por_id, hijas, descendientes = _indices(todas)

    visibles = [
        t
        for t in todas
        if (filtro.is_archived is None and t.archived_at is None)
        or (filtro.is_archived is True and t.archived_at is not None)
        or (filtro.is_archived is False and t.archived_at is None)
    ]
    if filtro.parent_id is not None:
        visibles = [t for t in visibles if t.parent_id == filtro.parent_id]
    if filtro.kind is not None:
        visibles = [t for t in visibles if t.kind == filtro.kind.value]
    if filtro.max_depth is not None:
        visibles = [t for t in visibles if t.depth < filtro.max_depth]
    if filtro.q:
        aguja = _clave_de_nombre(filtro.q)
        visibles = [t for t in visibles if aguja in _clave_de_nombre(t.name)]

    estadisticas = None
    if filtro.period or "stats" in filtro.include:
        estadisticas = await _estadisticas(alcance, filtro.period)

    trozo = visibles[paginacion.offset : paginacion.offset + paginacion.limit]
    return Pagina.crear(
        [
            _respuesta(
                t,
                por_id=por_id,
                hijas=hijas,
                descendientes=descendientes,
                estadisticas=estadisticas,
            )
            for t in trozo
        ],
        page=paginacion.page,
        size=paginacion.size,
        total=len(visibles),
    )


@router.get(
    "/categories/tree",
    response_model=list[CategoriaNodoRespuesta],
    summary="Árbol completo anidado",
)
async def arbol(
    alcance: Alcance,
    is_archived: Annotated[bool | None, Query()] = None,
    kind: Annotated[TipoTematica | None, Query()] = None,
    period: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> list[CategoriaNodoRespuesta]:
    """Lo que la SPA carga una vez y cachea, ya ordenado por `position`."""
    todas = await _arbol_del_hogar(alcance, incluir_archivadas=is_archived is not False)
    if is_archived is True:
        todas = [t for t in todas if t.archived_at is not None]
    elif is_archived is None:
        todas = [t for t in todas if t.archived_at is None]
    if kind is not None:
        todas = [t for t in todas if t.kind == kind.value]

    por_id, hijas, descendientes = _indices(todas)
    estadisticas = await _estadisticas(alcance, period) if period else None

    def nodo(tematica: Category) -> CategoriaNodoRespuesta:
        base = _respuesta(
            tematica,
            por_id=por_id,
            hijas=hijas,
            descendientes=descendientes,
            estadisticas=estadisticas,
        )
        return CategoriaNodoRespuesta(
            **base.model_dump(),
            children=[nodo(h) for h in hijas.get(tematica.id, ())],
        )

    return [nodo(t) for t in hijas.get(None, ())]


# --------------------------------------------------------------------------- #
# Alta, edición y árbol
# --------------------------------------------------------------------------- #


async def _tematica_o_404(alcance: AlcanceHogar, tematica_id: uuid.UUID) -> Category:
    tematica = (
        await alcance.sesion.execute(
            select(Category)
            .where(Category.id == tematica_id, Category.household_id == alcance.household_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if tematica is None:
        raise NoEncontrado("Esa temática no existe.")
    return tematica


async def _hermanas(
    alcance: AlcanceHogar, madre: uuid.UUID | None, excluir: uuid.UUID | None = None
) -> list[Category]:
    condiciones = [
        Category.household_id == alcance.household_id,
        Category.archived_at.is_(None),
        Category.merged_into_id.is_(None),
    ]
    condiciones.append(
        Category.parent_id.is_(None) if madre is None else Category.parent_id == madre
    )
    if excluir is not None:
        condiciones.append(Category.id != excluir)
    return list(
        (
            await alcance.sesion.execute(
                select(Category).where(*condiciones).order_by(Category.sort_order, Category.id)
            )
        )
        .scalars()
        .all()
    )


async def _exigir_nombre_libre(
    alcance: AlcanceHogar, madre: uuid.UUID | None, nombre: str, excluir: uuid.UUID | None = None
) -> None:
    clave = _clave_de_nombre(nombre)
    for hermana in await _hermanas(alcance, madre, excluir):
        if _clave_de_nombre(hermana.name) == clave:
            raise Conflicto(
                f"Ya existe «{hermana.name}» en el mismo nivel.", codigo="nombre_duplicado"
            )


async def _ranura_libre(alcance: AlcanceHogar) -> int:
    """Primera ranura de color libre en el orden 1→12; recicla al agotarlas."""
    usadas = set(
        (
            await alcance.sesion.execute(
                select(Category.color_slot).where(
                    Category.household_id == alcance.household_id,
                    Category.color_slot.is_not(None),
                    Category.archived_at.is_(None),
                    Category.merged_into_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for ranura in range(1, RANURAS + 1):
        if ranura not in usadas:
            return ranura
    return 1


async def _refrescar_rutas(alcance: AlcanceHogar) -> None:
    await alcance.sesion.execute(
        text("SELECT refresh_category_paths(cast(:hogar as uuid))"),
        {"hogar": alcance.household_id},
    )


@router.post(
    "/categories",
    response_model=CategoriaRespuesta,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verificar_csrf)],
    summary="Crear temática",
)
async def crear(
    datos: CategoriaCrear, alcance: AlcanceEscritura, respuesta: Response
) -> CategoriaRespuesta:
    """RN-11 (seis niveles), RN-12 (nombre único entre hermanas) y RN-13 (`kind`)."""
    madre: Category | None = None
    if datos.parent_id is not None:
        madre = await _tematica_o_404(alcance, datos.parent_id)
        if madre.archived_at is not None or madre.merged_into_id is not None:
            raise Conflicto("La temática madre está archivada o fusionada.")
        if madre.depth + 1 > PROFUNDIDAD_MAXIMA - 1:
            raise ReglaDeNegocio(
                f"El árbol admite {PROFUNDIDAD_MAXIMA} niveles como máximo.",
                codigo="profundidad_maxima",
            )
    await _exigir_nombre_libre(alcance, datos.parent_id, datos.name)

    hermanas = await _hermanas(alcance, datos.parent_id)
    posicion = (
        datos.position
        if datos.position is not None
        else (max((h.sort_order for h in hermanas), default=-1) + 1)
    )
    identificador = uuid.uuid4()
    ruta = [*(madre.path_ids if madre else []), identificador]
    tramo = f"{min(posicion, 9999):04d}"
    tematica = Category(
        id=identificador,
        household_id=alcance.household_id,
        parent_id=datos.parent_id,
        name=datos.name,
        # RN-13: el tipo se hereda de la madre; el del cuerpo solo manda en raíz.
        kind=madre.kind if madre else datos.kind.value,
        color_hex=datos.color,
        # Las subtemáticas no reciben ranura: heredan el hue de su madre y se
        # distinguen por luminosidad (sistema de diseño §2.4, regla 4).
        color_slot=None if madre else await _ranura_libre(alcance),
        icon=datos.icon or "circle",
        sort_order=posicion,
        depth=len(ruta) - 1,
        path_ids=ruta,
        sort_key=f"{madre.sort_key}.{tramo}" if madre else tramo,
        is_locked=datos.is_locked,
        default_rollover_mode="carry" if datos.rollover_enabled else "none",
        monthly_target=datos.monthly_target,
    )
    alcance.sesion.add(tematica)
    await alcance.sesion.flush()
    await _refrescar_rutas(alcance)
    await alcance.sesion.commit()
    respuesta.headers["Location"] = f"{settings.api_prefix}/categories/{tematica.id}"
    return await _detalle_de(alcance, tematica.id)


async def _detalle_de(alcance: AlcanceHogar, tematica_id: uuid.UUID) -> CategoriaRespuesta:
    todas = await _arbol_del_hogar(alcance, incluir_archivadas=True)
    por_id, hijas, descendientes = _indices(todas)
    tematica = por_id.get(tematica_id)
    if tematica is None:
        tematica = await _tematica_o_404(alcance, tematica_id)
        await alcance.sesion.refresh(tematica)
    return _respuesta(tematica, por_id=por_id, hijas=hijas, descendientes=descendientes)


def _etiqueta(tematica: Category) -> str:
    """`ETag` débil de §1.10: identifica una versión concreta de la fila."""
    return f'W/"{tematica.id}-{tematica.updated_at.timestamp():.6f}"'


# --------------------------------------------------------------------------- #
# Fusión (§3.4 y modelo de datos §4). Antes de `/categories/{id}` para que
# `merge`, `merges` y `tree` no se interpreten como identificadores.
# --------------------------------------------------------------------------- #


def _opciones(datos: CategoriaFusionCrear) -> OpcionesFusion:
    return OpcionesFusion(
        move_children=datos.move_children,
        keep_source_names_as_alias=datos.keep_source_names_as_alias,
        force=datos.force,
    )


def _previa(
    origenes: list[Category], destino: Category, resumen: ResumenFusion
) -> CategoriaFusionPreviaRespuesta:
    return CategoriaFusionPreviaRespuesta(
        target=CategoriaRefRespuesta(id=destino.id, name=destino.name, color=destino.color_hex),
        sources=[CategoriaRefRespuesta(id=o.id, name=o.name, color=o.color_hex) for o in origenes],
        transactions=resumen.transactions,
        splits=resumen.splits,
        invoice_lines=resumen.invoice_lines,
        rules=resumen.rules,
        recurring=resumen.recurring,
        products=resumen.products,
        payees=resumen.payees,
        goals=resumen.goals,
        budget_periods=resumen.budget_periods,
        allocations_merged=resumen.allocations_merged,
        children_moved=resumen.children_moved,
        conflicts=resumen.conflicts,
    )


@router.post(
    "/categories/merge/preview",
    response_model=CategoriaFusionPreviaRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Previsualizar una fusión",
)
async def previa_de_fusion(
    datos: CategoriaFusionCrear, alcance: Alcance
) -> CategoriaFusionPreviaRespuesta:
    """Las cifras exactas del diálogo de confirmación. No escribe nada."""
    origenes, destino, resumen = await previsualizar(
        alcance, datos.source_ids, datos.target_id, _opciones(datos)
    )
    return _previa(origenes, destino, resumen)


@router.post(
    "/categories/merge",
    response_model=CategoriaFusionResultadoRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Fusionar temáticas",
)
async def fusion(
    datos: CategoriaFusionCrear, alcance: AlcanceEscritura
) -> CategoriaFusionResultadoRespuesta:
    """F-04: reasigna todo el histórico en una única transacción (RN-19, RN-20)."""
    resultado = await fusionar(alcance, datos.source_ids, datos.target_id, _opciones(datos))
    await alcance.sesion.commit()
    operacion = resultado.operacion
    return CategoriaFusionResultadoRespuesta(
        **_previa(resultado.origenes, resultado.destino, resultado.resumen).model_dump(),
        merge_id=operacion.id,
        performed_at=operacion.finished_at or datetime.now(UTC),
        undo_available_until=operacion.undo_deadline or datetime.now(UTC),
    )


@router.get(
    "/categories/merges",
    response_model=Pagina[CategoriaFusionRespuesta],
    summary="Fusiones recientes",
)
async def fusiones(
    alcance: Alcance, paginacion: PaginacionActual
) -> Pagina[CategoriaFusionRespuesta]:
    """Solo las operaciones raíz: las hijas se deshacen con su madre."""
    condiciones = [
        MergeOperation.household_id == alcance.household_id,
        MergeOperation.entity_type == "category",
        MergeOperation.parent_merge_operation_id.is_(None),
    ]
    total = await alcance.sesion.scalar(
        select(func.count()).select_from(MergeOperation).where(*condiciones)
    )
    operaciones = list(
        (
            await alcance.sesion.execute(
                select(MergeOperation)
                .where(*condiciones)
                .order_by(MergeOperation.created_at.desc(), MergeOperation.id.desc())
                .offset(paginacion.offset)
                .limit(paginacion.limit)
            )
        )
        .scalars()
        .all()
    )

    ahora = datetime.now(UTC)
    items = []
    for operacion in operaciones:
        # Solo las hermanas de la misma fusión múltiple, no las fusiones recursivas
        # de subtemáticas homónimas, que tienen otro destino.
        hermanas = list(
            (
                await alcance.sesion.execute(
                    select(MergeOperation).where(
                        MergeOperation.parent_merge_operation_id == operacion.id,
                        MergeOperation.target_id == operacion.target_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        # Los nombres van congelados en la propia operación: el histórico se lee
        # sin resolver ninguna clave ajena, aunque la temática ya no exista.
        origenes = [
            CategoriaRefRespuesta(id=o.source_id, name=o.source_label)
            for o in (operacion, *hermanas)
        ]
        items.append(
            CategoriaFusionRespuesta(
                id=operacion.id,
                target=CategoriaRefRespuesta(id=operacion.target_id, name=operacion.target_label),
                sources=origenes,
                rows_changed=int(operacion.counts.get("rows", 0) or 0),
                performed_at=operacion.finished_at or operacion.created_at,
                undo_available_until=operacion.undo_deadline or operacion.created_at,
                undone_at=operacion.reverted_at,
                can_undo=(
                    operacion.status == "done"
                    and operacion.undo_deadline is not None
                    and operacion.undo_deadline > ahora
                ),
            )
        )
    return Pagina.crear(items, page=paginacion.page, size=paginacion.size, total=total or 0)


@router.post(
    "/categories/merges/{operacion_id}/undo",
    response_model=CategoriaFusionResultadoRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Deshacer una fusión",
)
async def deshacer_fusion(
    operacion_id: uuid.UUID, alcance: AlcanceEscritura
) -> CategoriaFusionResultadoRespuesta:
    """RN-20: reversible durante treinta días, y nunca a medias."""
    resultado = await deshacer(alcance, operacion_id)
    await alcance.sesion.commit()
    operacion = resultado.operacion
    return CategoriaFusionResultadoRespuesta(
        **_previa(resultado.origenes, resultado.destino, resultado.resumen).model_dump(),
        merge_id=operacion.id,
        performed_at=operacion.reverted_at or datetime.now(UTC),
        undo_available_until=operacion.undo_deadline or datetime.now(UTC),
    )


@router.post(
    "/categories/reorder",
    response_model=list[CategoriaRespuesta],
    dependencies=[Depends(verificar_csrf)],
    summary="Reordenar hermanas",
)
async def reordenar(
    datos: CategoriaReordenarCrear, alcance: AlcanceEscritura
) -> list[CategoriaRespuesta]:
    """Arrastrar y soltar varias de una vez, en una sola transacción."""
    tocadas: list[uuid.UUID] = []
    for item in datos.items:
        tematica = await _tematica_o_404(alcance, item.id)
        if item.parent_id != tematica.parent_id:
            await _mover_en_arbol(alcance, tematica, item.parent_id, item.position)
        else:
            tematica.sort_order = item.position
        tocadas.append(tematica.id)
    await alcance.sesion.flush()
    await _refrescar_rutas(alcance)
    await alcance.sesion.commit()

    todas = await _arbol_del_hogar(alcance, incluir_archivadas=True)
    por_id, hijas, descendientes = _indices(todas)
    return [
        _respuesta(por_id[t], por_id=por_id, hijas=hijas, descendientes=descendientes)
        for t in tocadas
        if t in por_id
    ]


# --------------------------------------------------------------------------- #
# Detalle, edición y movimiento
# --------------------------------------------------------------------------- #


@router.get(
    "/categories/{tematica_id}", response_model=CategoriaRespuesta, summary="Detalle de temática"
)
async def detalle(
    tematica_id: uuid.UUID, alcance: Alcance, respuesta: Response
) -> CategoriaRespuesta:
    tematica = await _tematica_o_404(alcance, tematica_id)
    # §1.10: el cliente lo devuelve en `If-Match` al guardar, y así una edición
    # desde otra pestaña no se pisa en silencio.
    respuesta.headers["ETag"] = _etiqueta(tematica)
    return await _detalle_de(alcance, tematica_id)


@router.patch(
    "/categories/{tematica_id}",
    response_model=CategoriaRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Renombrar o editar temática",
)
async def editar(
    tematica_id: uuid.UUID,
    datos: CategoriaActualizar,
    alcance: AlcanceEscritura,
    respuesta: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CategoriaRespuesta:
    """Renombrar no rompe el histórico (F-05): el identificador no cambia."""
    tematica = await _tematica_o_404(alcance, tematica_id)
    if if_match and if_match != _etiqueta(tematica):
        raise SinPermiso(
            "Alguien ha cambiado esta temática mientras la editabas. Recarga y vuelve a "
            "intentarlo.",
            codigo="precondicion_fallida",
            estado=status.HTTP_412_PRECONDITION_FAILED,
        )

    cambios = datos.model_dump(exclude_unset=True)
    if cambios.get("name") and cambios["name"] != tematica.name:
        if tematica.is_system:
            raise Conflicto("«Sin clasificar» es del sistema: no se puede renombrar.")
        await _exigir_nombre_libre(alcance, tematica.parent_id, cambios["name"], tematica.id)
        tematica.name = cambios["name"]
    if "color" in cambios:
        tematica.color_hex = cambios["color"]
    if "icon" in cambios:
        tematica.icon = cambios["icon"] or "circle"
    if cambios.get("rollover_enabled") is not None:
        tematica.default_rollover_mode = "carry" if cambios["rollover_enabled"] else "none"
    if cambios.get("is_locked") is not None:
        tematica.is_locked = cambios["is_locked"]
    if "monthly_target" in cambios:
        tematica.monthly_target = cambios["monthly_target"]
    if cambios.get("is_default") is not None:
        await _marcar_por_defecto(alcance, tematica, es_por_defecto=cambios["is_default"])

    await alcance.sesion.commit()
    await alcance.sesion.refresh(tematica)
    respuesta.headers["ETag"] = _etiqueta(tematica)
    return await _detalle_de(alcance, tematica.id)


async def _marcar_por_defecto(
    alcance: AlcanceHogar, tematica: Category, *, es_por_defecto: bool
) -> None:
    """Solo una temática por defecto y por tipo: es el destino de lo sin clasificar."""
    if not es_por_defecto:
        tematica.is_system = False
        return
    await alcance.sesion.execute(
        text(
            "UPDATE categories SET is_system = false "
            " WHERE household_id = :hogar AND kind = cast(:tipo as text) "
            "   AND id <> :tematica"
        ),
        {"hogar": alcance.household_id, "tipo": tematica.kind, "tematica": tematica.id},
    )
    tematica.is_system = True


async def _mover_en_arbol(
    alcance: AlcanceHogar, tematica: Category, madre_id: uuid.UUID | None, posicion: int
) -> None:
    """Cambia de madre comprobando ciclo y profundidad con `path_ids` (RN-11)."""
    if madre_id is not None:
        madre = await _tematica_o_404(alcance, madre_id)
        if tematica.id in (madre.path_ids or []):
            raise ReglaDeNegocio(
                "No se puede mover una temática dentro de su propio subárbol.",
                codigo="ciclo_en_arbol",
            )
        if madre.kind != tematica.kind:
            raise ReglaDeNegocio(
                "Una temática de gasto no puede colgar de una de ingreso, ni al revés.",
            )
        profundidad_nueva = madre.depth + 1
    else:
        profundidad_nueva = 0

    alto = await alcance.sesion.scalar(
        select(func.max(Category.depth)).where(
            Category.household_id == alcance.household_id,
            Category.path_ids.contains([tematica.id]),
        )
    )
    salto = profundidad_nueva - tematica.depth
    if (alto or tematica.depth) + salto > PROFUNDIDAD_MAXIMA - 1:
        raise ReglaDeNegocio(
            f"El movimiento superaría los {PROFUNDIDAD_MAXIMA} niveles de anidación.",
            codigo="profundidad_maxima",
        )

    await _exigir_nombre_libre(alcance, madre_id, tematica.name, tematica.id)
    tematica.parent_id = madre_id
    tematica.sort_order = posicion


@router.post(
    "/categories/{tematica_id}/move",
    response_model=CategoriaRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Mover y reordenar en el árbol",
)
async def mover(
    tematica_id: uuid.UUID, datos: CategoriaMoverCrear, alcance: AlcanceEscritura
) -> CategoriaRespuesta:
    tematica = await _tematica_o_404(alcance, tematica_id)
    await _mover_en_arbol(alcance, tematica, datos.parent_id, datos.position)
    await alcance.sesion.flush()
    await _refrescar_rutas(alcance)
    await alcance.sesion.commit()
    return await _detalle_de(alcance, tematica.id)


@router.post(
    "/categories/{tematica_id}/archive",
    response_model=CategoriaRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Archivar temática",
)
async def archivar(
    tematica_id: uuid.UUID,
    alcance: AlcanceEscritura,
    cascade: Annotated[bool, Query(description="Archiva también el subárbol.")] = True,
) -> CategoriaRespuesta:
    """F-06: sale de los selectores y sigue en los informes (RN-13)."""
    tematica = await _tematica_o_404(alcance, tematica_id)
    if tematica.is_system:
        raise Conflicto("«Sin clasificar» es del sistema: no se puede archivar.")
    activas = await alcance.sesion.scalar(
        select(func.count())
        .select_from(Category)
        .where(
            Category.household_id == alcance.household_id,
            Category.path_ids.contains([tematica.id]),
            Category.id != tematica.id,
            Category.archived_at.is_(None),
            Category.merged_into_id.is_(None),
        )
    )
    if activas and not cascade:
        raise Conflicto(
            f"Esta temática tiene {activas} subtemáticas activas. Archívalas antes o usa "
            "«cascade».",
            codigo="tematica_con_descendientes",
        )
    if tematica.archived_at is None or activas:
        # Una temática activa no puede tener una madre archivada: se archiva el
        # subárbol completo de una sola pasada usando `path_ids`.
        await alcance.sesion.execute(
            text(
                "UPDATE categories SET archived_at = now() "
                " WHERE household_id = :hogar "
                "   AND path_ids @> ARRAY[cast(:tematica as uuid)] "
                "   AND archived_at IS NULL"
            ),
            {"hogar": alcance.household_id, "tematica": tematica.id},
        )
        await alcance.sesion.commit()
    return await _detalle_de(alcance, tematica.id)


@router.post(
    "/categories/{tematica_id}/unarchive",
    response_model=CategoriaRespuesta,
    dependencies=[Depends(verificar_csrf)],
    summary="Desarchivar temática",
)
async def desarchivar(tematica_id: uuid.UUID, alcance: AlcanceEscritura) -> CategoriaRespuesta:
    """Desarchiva también sus antepasados: si no, quedaría colgando de una archivada."""
    tematica = await _tematica_o_404(alcance, tematica_id)
    if tematica.merged_into_id is not None:
        raise Conflicto(
            "Esta temática es el rastro de una fusión. Deshaz la fusión para recuperarla."
        )
    await _exigir_nombre_libre(alcance, tematica.parent_id, tematica.name, tematica.id)
    await alcance.sesion.execute(
        text(
            "UPDATE categories SET archived_at = NULL "
            " WHERE household_id = :hogar AND merged_into_id IS NULL "
            "   AND id = ANY(SELECT unnest(path_ids) FROM categories WHERE id = :tematica)"
        ),
        {"hogar": alcance.household_id, "tematica": tematica.id},
    )
    await alcance.sesion.commit()
    return await _detalle_de(alcance, tematica.id)


# --------------------------------------------------------------------------- #
# Uso y borrado
# --------------------------------------------------------------------------- #

SQL_USO = text(
    """
    SELECT
      (SELECT count(*) FROM transactions
        WHERE household_id = :hogar AND category_id = :tematica)          AS transactions,
      (SELECT count(*) FROM transaction_splits
        WHERE household_id = :hogar AND category_id = :tematica)          AS splits,
      (SELECT count(*) FROM invoice_lines
        WHERE household_id = :hogar AND category_id = :tematica)          AS invoice_lines,
      (SELECT count(*) FROM categorization_rules
        WHERE household_id = :hogar AND set_category_id = :tematica)      AS rules,
      (SELECT count(*) FROM recurring_rules
        WHERE household_id = :hogar AND category_id = :tematica)          AS recurring,
      (SELECT count(*) FROM goals
        WHERE household_id = :hogar AND category_id = :tematica)          AS goals,
      (SELECT count(*) FROM budget_allocations
        WHERE household_id = :hogar AND category_id = :tematica)          AS allocations,
      (SELECT count(*) FROM products
        WHERE household_id = :hogar AND category_id = :tematica)          AS products,
      (SELECT count(*) FROM payees
        WHERE household_id = :hogar AND default_category_id = :tematica)  AS payees,
      (SELECT min(booked_on) FROM vw_movement_lines
        WHERE household_id = :hogar AND category_id = :tematica)          AS primero,
      (SELECT max(booked_on) FROM vw_movement_lines
        WHERE household_id = :hogar AND category_id = :tematica)          AS ultimo,
      (SELECT count(*) FROM categories
        WHERE household_id = :hogar AND parent_id = :tematica)            AS children
    """
)


@router.get(
    "/categories/{tematica_id}/usage",
    response_model=CategoriaUsoRespuesta,
    summary="Dónde se usa una temática",
)
async def uso(tematica_id: uuid.UUID, alcance: Alcance) -> CategoriaUsoRespuesta:
    """Lo que se muestra antes de borrar o fusionar (RN-14)."""
    await _tematica_o_404(alcance, tematica_id)
    fila = (
        await alcance.sesion.execute(
            SQL_USO, {"hogar": alcance.household_id, "tematica": tematica_id}
        )
    ).one()
    total = (
        fila.transactions
        + fila.splits
        + fila.invoice_lines
        + fila.rules
        + fila.recurring
        + fila.goals
        + fila.allocations
        + fila.products
        + fila.payees
        + fila.children
    )
    return CategoriaUsoRespuesta(
        category_id=tematica_id,
        transactions=fila.transactions,
        splits=fila.splits,
        invoice_lines=fila.invoice_lines,
        rules=fila.rules,
        recurring=fila.recurring,
        goals=fila.goals,
        allocations=fila.allocations,
        products=fila.products,
        payees=fila.payees,
        first_used_on=fila.primero,
        last_used_on=fila.ultimo,
        can_hard_delete=total == 0,
    )


@router.delete(
    "/categories/{tematica_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verificar_csrf)],
    summary="Borrar temática",
)
async def borrar(
    tematica_id: uuid.UUID,
    alcance: AlcanceEscritura,
    reassign_to: Annotated[
        uuid.UUID | None, Query(description="Temática que recibe el histórico.")
    ] = None,
) -> None:
    """RN-14: con histórico, o se reasigna o no se borra. Nunca se descolocan informes."""
    tematica = await _tematica_o_404(alcance, tematica_id)
    if tematica.is_system:
        raise Conflicto("«Sin clasificar» es del sistema: no se puede borrar.")

    hijas = await alcance.sesion.scalar(
        select(func.count())
        .select_from(Category)
        .where(Category.household_id == alcance.household_id, Category.parent_id == tematica.id)
    )
    if hijas:
        raise Conflicto(
            f"Esta temática tiene {hijas} subtemáticas. Muévelas o fusiónalas antes de borrarla.",
            codigo="tematica_con_descendientes",
        )

    if reassign_to is not None:
        destino = await _tematica_o_404(alcance, reassign_to)
        # Reasignar es exactamente una fusión: se reutiliza para no tener dos
        # implementaciones del mismo movimiento de histórico. Se fuerza porque el
        # borrado no tiene una opción con la que reintentar, y RN-14 exige que
        # siempre exista un camino que no descoloque los informes pasados.
        await fusionar(alcance, [tematica.id], destino.id, OpcionesFusion(force=True))
        await alcance.sesion.commit()
        return

    fila = (
        await alcance.sesion.execute(
            SQL_USO, {"hogar": alcance.household_id, "tematica": tematica_id}
        )
    ).one()
    if any(
        (
            fila.transactions,
            fila.splits,
            fila.invoice_lines,
            fila.rules,
            fila.recurring,
            fila.goals,
            fila.allocations,
            fila.products,
            fila.payees,
        )
    ):
        raise Conflicto(
            "Esta temática tiene histórico. Indica «reassign_to» para trasladarlo, o archívala.",
            codigo="tematica_con_historico",
        )

    await alcance.sesion.delete(tematica)
    await alcance.sesion.flush()
    await _refrescar_rutas(alcance)
    await alcance.sesion.commit()
