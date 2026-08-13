"""Fusión de temáticas (F-04): el algoritmo de `modelo-datos.md` §4.

Fusionar **origen** en **destino** significa que todo lo que apuntaba al origen
apunta al destino, que el origen queda como lápida (`archived_at` +
`merged_into_id`) y que **los importes totales del hogar no cambian en ningún
periodo**: ni el gasto, ni el asignado, ni el saldo de ninguna cuenta.

Tres decisiones sostienen todo el módulo:

1. **Una sola transacción y un bloqueo de aviso por hogar.** Dos fusiones
   simultáneas en el mismo hogar se serializan; en hogares distintos no se
   estorban. El `COMMIT` lo hace quien llama.
2. **Ninguna fila se modifica sin quedar registrada.** Cada paso es un CTE que
   modifica y devuelve, más un `INSERT` en `merge_operation_changes` alimentado por
   ese `RETURNING`: por construcción no se puede cambiar algo sin anotarlo.
3. **El dinero viaja como texto dentro del diario.** `to_jsonb(numeric)` produce un
   número JSON, que al leerse en Python sería un `float`; con `::text` el céntimo
   sobrevive intacto al viaje de ida y vuelta.

La reversión (§4.9) está escrita aquí y no como función `plpgsql`: el esquema no
incluye `revert_merge()`, así que el diario se recorre desde Python, por grupos de
`(tabla, columna)` en orden descendente de `seq`, que es a la vez correcto y de
coste constante en número de sentencias.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Row, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AlcanceHogar
from app.core.errors import Conflicto, NoEncontrado, ReglaDeNegocio
from app.models.auditoria import AuditLog
from app.models.categoria import Category
from app.models.fusion import TABLAS_REVERSIBLES, MergeOperation

logger = logging.getLogger("app.fusion")

#: RN-20: una fusión se puede deshacer durante treinta días.
DIAS_PARA_DESHACER = 30

#: Cortafuegos para una fusión patológica: no puede dejar el hogar bloqueado.
TIEMPO_MAXIMO = "30s"

CERO = Decimal("0.00")

#: Columnas que la fusión escribe, con el tipo al que hay que convertir el valor
#: guardado en el diario para deshacerlo. Es la lista blanca que acota el SQL
#: dinámico de la reversión: ningún nombre que no esté aquí llega a una sentencia.
COLUMNAS: dict[tuple[str, str], str] = {
    ("categories", "parent_id"): "uuid",
    ("categories", "name"): "text",
    ("categories", "archived_at"): "timestamptz",
    ("categories", "merged_into_id"): "uuid",
    ("categories", "color_slot"): "smallint",
    ("categories", "is_locked"): "boolean",
    ("transactions", "category_id"): "uuid",
    ("transaction_splits", "category_id"): "uuid",
    ("transaction_splits", "amount"): "numeric(14,2)",
    ("transaction_splits", "notes"): "text",
    ("invoice_lines", "category_id"): "uuid",
    ("budget_allocations", "category_id"): "uuid",
    ("budget_allocations", "allocated_amount"): "numeric(14,2)",
    ("budget_allocations", "carryover_in"): "numeric(14,2)",
    ("budget_allocations", "rollover_mode"): "varchar(16)",
    ("budget_allocations", "is_locked"): "boolean",
    ("budget_allocations", "note"): "text",
    ("budget_allocations", "source"): "varchar(10)",
    ("categorization_rules", "set_category_id"): "uuid",
    ("categorization_rules", "is_active"): "boolean",
    ("recurring_rules", "category_id"): "uuid",
    ("recurring_rules", "template_splits"): "jsonb",
    ("goals", "category_id"): "uuid",
    ("products", "category_id"): "uuid",
    ("payees", "default_category_id"): "uuid",
    ("alerts", "category_id"): "uuid",
    ("saved_views", "filters"): "jsonb",
}

#: Columnas cuyo valor es un documento JSON completo y no un escalar.
COLUMNAS_JSONB = frozenset({("recurring_rules", "template_splits"), ("saved_views", "filters")})

#: `jsonb #>> '{}'` desenvuelve el escalar sin comillas; sobre `'null'::jsonb` da
#: `NULL`, que es justo lo que hace falta para restaurar una columna vaciada.
DESENVOLVER = "(c.old_value #>> '{}')"


def _validar_destino(tabla: str, columna: str | None = None) -> None:
    """Ninguna cadena del cliente llega al SQL: solo lo que hay en las listas."""
    if tabla not in TABLAS_REVERSIBLES:
        raise ValueError(f"Tabla no reversible: {tabla}")
    if columna is not None and (tabla, columna) not in COLUMNAS:
        raise ValueError(f"Columna no registrada para deshacer: {tabla}.{columna}")


# --------------------------------------------------------------------------- #
# Contratos de entrada y salida
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class OpcionesFusion:
    """Las opciones del cuerpo `CategoryMergeIn`, más los dos valores recomendados.

    El contrato de la API no expone una decisión por cada colisión de nombre de
    hija (§4.6 del modelo de datos sí la contempla); aquí se aplica la opción
    recomendada, `merge_child`: la hija del origen se fusiona con su homónima del
    destino, recursivamente y dentro de la misma transacción.
    """

    move_children: bool = True
    keep_source_names_as_alias: bool = True
    force: bool = False
    collapse_duplicate_splits: bool = True

    def como_json(self) -> dict[str, Any]:
        return {
            "move_children": self.move_children,
            "keep_source_names_as_alias": self.keep_source_names_as_alias,
            "force": self.force,
            "collapse_duplicate_splits": self.collapse_duplicate_splits,
        }


@dataclass(slots=True)
class ResumenFusion:
    """Lo que se va a mover, con cifras concretas (§4.4)."""

    transactions: int = 0
    splits: int = 0
    invoice_lines: int = 0
    rules: int = 0
    recurring: int = 0
    products: int = 0
    payees: int = 0
    goals: int = 0
    budget_periods: int = 0
    allocations_merged: Decimal = CERO
    children_moved: int = 0
    conflicts: list[str] = field(default_factory=list)

    @property
    def registros(self) -> int:
        return (
            self.transactions
            + self.splits
            + self.invoice_lines
            + self.rules
            + self.recurring
            + self.products
            + self.payees
            + self.goals
            + self.budget_periods
            + self.children_moved
        )


@dataclass(slots=True)
class ResultadoFusion:
    """La fusión ya hecha (o deshecha), con lo que la interfaz necesita mostrar."""

    operacion: MergeOperation
    origenes: list[Category]
    destino: Category
    resumen: ResumenFusion
    filas_cambiadas: int


# --------------------------------------------------------------------------- #
# Validaciones (§4.3)
# --------------------------------------------------------------------------- #


async def _cargar(sesion: AsyncSession, hogar: uuid.UUID, tematica_id: uuid.UUID) -> Category:
    """RN-02: una temática de otro hogar responde 404, nunca 403."""
    tematica = (
        await sesion.execute(
            select(Category)
            .where(Category.id == tematica_id, Category.household_id == hogar)
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if tematica is None:
        raise NoEncontrado("Esa temática no existe.")
    return tematica


async def _bloquear(sesion: AsyncSession, hogar: uuid.UUID, tematica_id: uuid.UUID) -> Category:
    """Como `_cargar`, pero con `FOR UPDATE`.

    Se revalida **después** de bloquear porque la previsualización pudo hacerse
    hace diez minutos y en ese tiempo alguien puede haber archivado el destino.
    """
    tematica = (
        await sesion.execute(
            select(Category)
            .where(Category.id == tematica_id, Category.household_id == hogar)
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if tematica is None:
        raise NoEncontrado("Esa temática no existe.")
    return tematica


def validar_par(origen: Category, destino: Category) -> None:
    """RN-17, RN-18 y RN-19, en el orden en que se le explican al usuario."""
    if origen.id == destino.id:
        raise ReglaDeNegocio(
            "No se puede fusionar una temática consigo misma.", codigo="fusion_invalida"
        )
    if origen.is_system:
        raise ReglaDeNegocio(
            f"«{origen.name}» es una temática del sistema: es el destino de los gastos sin "
            "clasificar y no se puede absorber.",
            codigo="fusion_invalida",
        )
    if origen.merged_into_id is not None:
        raise Conflicto(f"«{origen.name}» ya se fusionó con otra temática.")
    if destino.archived_at is not None or destino.merged_into_id is not None:
        raise ReglaDeNegocio(
            f"«{destino.name}» está archivada o fusionada: no se puede fusionar hacia ella.",
            codigo="fusion_invalida",
        )
    if origen.kind != destino.kind:
        # Fusionar ingreso en gasto invertiría el signo de todos los informes
        # históricos. Prohibido sin excepción.
        raise ReglaDeNegocio(
            "No se puede fusionar una temática de ingreso con una de gasto.",
            codigo="fusion_invalida",
        )
    # RN-18: el destino no puede colgar del origen. `path_ids` acaba en el propio
    # identificador, así que los antepasados son todo menos el último elemento.
    if origen.id in (destino.path_ids or [])[:-1]:
        raise ReglaDeNegocio(
            f"«{destino.name}» es una subtemática de «{origen.name}»: fusionarlas destruiría "
            "la jerarquía. Mueve primero la subtemática fuera.",
            codigo="fusion_invalida",
        )


# --------------------------------------------------------------------------- #
# Previsualización (§4.4)
# --------------------------------------------------------------------------- #

SQL_PREVIA = text(
    """
    SELECT
      (SELECT count(*) FROM transactions
        WHERE household_id = :hogar AND category_id = :origen)               AS transactions,
      (SELECT count(*) FROM transaction_splits
        WHERE household_id = :hogar AND category_id = :origen)               AS splits,
      (SELECT count(*) FROM invoice_lines
        WHERE household_id = :hogar AND category_id = :origen)               AS invoice_lines,
      (SELECT count(*) FROM categorization_rules
        WHERE household_id = :hogar AND set_category_id = :origen)           AS rules,
      (SELECT count(*) FROM recurring_rules
        WHERE household_id = :hogar AND category_id = :origen)               AS recurring,
      (SELECT count(*) FROM goals
        WHERE household_id = :hogar AND category_id = :origen)               AS goals,
      (SELECT count(*) FROM products
        WHERE household_id = :hogar AND category_id = :origen)               AS products,
      (SELECT count(*) FROM payees
        WHERE household_id = :hogar AND default_category_id = :origen)       AS payees,
      (SELECT count(*) FROM categories
        WHERE household_id = :hogar AND parent_id = :origen
          AND archived_at IS NULL AND merged_into_id IS NULL)                AS children,
      (SELECT count(*) FROM budget_allocations
        WHERE household_id = :hogar AND category_id = :origen)               AS allocations,
      -- Lo que quedará asignado en el destino: la SUMA de los dos (§4.5).
      (SELECT COALESCE(sum(allocated_amount), 0) FROM budget_allocations
        WHERE household_id = :hogar AND category_id IN (:origen, :destino))  AS allocated_total,
      -- Meses en los que las dos tienen asignación: los importes se suman.
      (SELECT count(*) FROM budget_allocations s
         JOIN budget_allocations t ON t.budget_period_id = s.budget_period_id
                                  AND t.category_id = :destino
        WHERE s.household_id = :hogar AND s.category_id = :origen)          AS allocation_clashes,
      -- De esos meses, cuántos están ya cerrados: aviso obligatorio.
      (SELECT count(*) FROM budget_allocations s
         JOIN budget_periods p ON p.id = s.budget_period_id
        WHERE s.household_id = :hogar AND s.category_id = :origen
          AND p.closed_at IS NOT NULL)                                      AS closed_periods,
      -- Transacciones con reparto en las dos: sus splits se colapsarían.
      (SELECT count(*) FROM (
          SELECT s.transaction_id
            FROM transaction_splits s
           WHERE s.household_id = :hogar AND s.category_id IN (:origen, :destino)
           GROUP BY s.transaction_id
          HAVING count(DISTINCT s.category_id) = 2) x)                      AS split_clashes
    """
)

#: Lo que quedará asignado en el destino tras la fusión: la suma de las
#: asignaciones de las origen y del destino, contando cada una una sola vez (§4.5).
SQL_ASIGNADO_TOTAL = text(
    """
    SELECT COALESCE(sum(allocated_amount), 0) AS total
      FROM budget_allocations
     WHERE household_id = :hogar
       AND category_id = ANY (cast(string_to_array(:categorias, ',') as uuid[]))
    """
)

SQL_HIJAS_EN_CONFLICTO = text(
    """
    SELECT a.id AS hija, a.name AS nombre, b.id AS gemela
      FROM categories a
      JOIN categories b ON lower(b.name) = lower(a.name)
                       AND b.parent_id = :destino
                       AND b.archived_at IS NULL AND b.merged_into_id IS NULL
     WHERE a.household_id = :hogar AND a.parent_id = :origen
       AND a.archived_at IS NULL AND a.merged_into_id IS NULL
    """
)


async def previsualizar(
    alcance: AlcanceHogar,
    origen_ids: list[uuid.UUID],
    destino_id: uuid.UUID,
    opciones: OpcionesFusion,
) -> tuple[list[Category], Category, ResumenFusion]:
    """Cuenta lo que se movería y avisa de lo que puede sorprender.

    No escribe nada: la fila de `merge_operations` se crea al confirmar. Así dos
    pestañas abiertas en el mismo diálogo no pelean por el índice parcial de
    previsualizaciones vivas.
    """
    sesion = alcance.sesion
    destino = await _cargar(sesion, alcance.household_id, destino_id)
    origenes = [await _cargar(sesion, alcance.household_id, oid) for oid in origen_ids]
    for origen in origenes:
        validar_par(origen, destino)

    resumen = ResumenFusion()
    periodos = 0
    for origen in origenes:
        parametros = {
            "hogar": alcance.household_id,
            "origen": origen.id,
            "destino": destino.id,
        }
        fila = (await sesion.execute(SQL_PREVIA, parametros)).one()
        resumen.transactions += fila.transactions
        resumen.splits += fila.splits
        resumen.invoice_lines += fila.invoice_lines
        resumen.rules += fila.rules
        resumen.recurring += fila.recurring
        resumen.goals += fila.goals
        resumen.products += fila.products
        resumen.payees += fila.payees
        periodos += fila.allocations
        if opciones.move_children:
            resumen.children_moved += fila.children

        if fila.allocation_clashes:
            resumen.conflicts.append(
                f"{fila.allocation_clashes} meses tienen asignación en «{origen.name}» y en "
                f"«{destino.name}»: los importes se suman."
            )
        if fila.closed_periods:
            resumen.conflicts.append(
                f"⚠ {fila.closed_periods} de esos meses están cerrados y sus informes cambiarán."
            )
        if fila.split_clashes and opciones.collapse_duplicate_splits:
            resumen.conflicts.append(
                f"{fila.split_clashes} transacciones tienen reparto en las dos temáticas: "
                "sus líneas se unirán en una."
            )
        if opciones.move_children:
            gemelas = (await sesion.execute(SQL_HIJAS_EN_CONFLICTO, parametros)).all()
            for gemela in gemelas:
                resumen.conflicts.append(
                    f"⚠ «{gemela.nombre}» existe en las dos temáticas: se fusionarán también."
                )

    resumen.budget_periods = periodos
    # Lo asignado se suma **una sola vez** sobre el conjunto completo: con varios
    # orígenes, hacerlo dentro del bucle contaba las asignaciones del destino una
    # vez por origen e inflaba la cifra que la pantalla de confirmación enseña.
    asignado = await sesion.scalar(
        SQL_ASIGNADO_TOTAL,
        {
            "hogar": alcance.household_id,
            "categorias": ",".join(str(c.id) for c in [*origenes, destino]),
        },
    )
    resumen.allocations_merged = Decimal(str(asignado or 0))
    return origenes, destino, resumen


# --------------------------------------------------------------------------- #
# Diario de deshacer
# --------------------------------------------------------------------------- #

SQL_ANOTAR = text(
    """
    INSERT INTO merge_operation_changes
           (id, merge_operation_id, household_id, table_name, row_pk,
            change_type, column_name, old_value, new_value)
    VALUES (gen_random_uuid(), :operacion, :hogar, :tabla, :fila,
            'update', :columna, cast(:antes as jsonb), cast(:despues as jsonb))
    """
)


async def _anotar(
    sesion: AsyncSession,
    operacion: uuid.UUID,
    hogar: uuid.UUID,
    tabla: str,
    fila: uuid.UUID,
    columna: str,
    antes: Any,
    despues: Any,
) -> None:
    """Una fila de diario, en una sentencia propia.

    Se emite suelta —y no dentro de un `VALUES` múltiple— porque el orden de `seq`
    es lo que determina el orden de la reversión, y para la lápida ese orden es
    obligatorio: `merged_into_id` tiene que volver a `NULL` antes que
    `archived_at`, o `ck_categories_merged_is_archived` se incumple a medio camino.
    """
    _validar_destino(tabla, columna)
    await sesion.execute(
        SQL_ANOTAR,
        {
            "operacion": operacion,
            "hogar": hogar,
            "tabla": tabla,
            "fila": fila,
            "columna": columna,
            "antes": json.dumps(antes),
            "despues": json.dumps(despues),
        },
    )


def _sql_reasignar(tabla: str, columna: str) -> str:
    """Un CTE que reasigna y un `INSERT` alimentado por su `RETURNING`."""
    _validar_destino(tabla, columna)
    return f"""
        WITH movidas AS (
            UPDATE {tabla}
               SET {columna} = :destino
             WHERE household_id = :hogar AND {columna} = :origen
            RETURNING id
        )
        INSERT INTO merge_operation_changes
               (id, merge_operation_id, household_id, table_name, row_pk,
                change_type, column_name, old_value, new_value)
        SELECT gen_random_uuid(), :operacion, :hogar, '{tabla}', movidas.id,
               'update', '{columna}',
               to_jsonb(cast(:origen_txt as text)), to_jsonb(cast(:destino_txt as text))
          FROM movidas
    """


async def _reasignar(
    sesion: AsyncSession, contexto: dict[str, Any], tabla: str, columna: str
) -> int:
    resultado = await sesion.execute(text(_sql_reasignar(tabla, columna)), contexto)
    return resultado.rowcount or 0


# --------------------------------------------------------------------------- #
# Pasos de la ejecución (§4.7 y §4.8)
# --------------------------------------------------------------------------- #

SQL_COLAPSAR_SPLITS = text(
    """
    WITH duplicados AS (
        SELECT s.id, s.transaction_id, s.amount, s.notes,
               row_number() OVER (PARTITION BY s.transaction_id
                                  ORDER BY s.line_number, s.id)         AS orden,
               sum(s.amount) OVER (PARTITION BY s.transaction_id)       AS importe_unido,
               count(*)      OVER (PARTITION BY s.transaction_id)       AS cuantos,
               string_agg(s.notes, ' · ') FILTER (WHERE s.notes IS NOT NULL)
                             OVER (PARTITION BY s.transaction_id)       AS notas_unidas
          FROM transaction_splits s
         WHERE s.household_id = :hogar AND s.category_id = :destino
    ),
    superviviente AS (
        UPDATE transaction_splits s
           SET amount = d.importe_unido,
               notes  = COALESCE(d.notas_unidas, s.notes)
          FROM duplicados d
         WHERE s.id = d.id AND d.orden = 1 AND d.cuantos > 1
        RETURNING s.id, d.amount AS importe_antiguo, d.importe_unido AS importe_nuevo,
                  d.notes AS notas_antiguas, s.notes AS notas_nuevas
    ),
    diario_superviviente AS (
        INSERT INTO merge_operation_changes
               (id, merge_operation_id, household_id, table_name, row_pk,
                change_type, column_name, old_value, new_value)
        SELECT gen_random_uuid(), :operacion, :hogar, 'transaction_splits', v.id,
               'update', c.columna, c.antes, c.despues
          FROM superviviente v,
               LATERAL (VALUES
                   ('amount', to_jsonb(v.importe_antiguo::text),
                              to_jsonb(v.importe_nuevo::text)),
                   ('notes',  to_jsonb(v.notas_antiguas), to_jsonb(v.notas_nuevas))
               ) AS c(columna, antes, despues)
        RETURNING 1
    ),
    condenados AS (
        DELETE FROM transaction_splits s
         USING duplicados d
         WHERE s.id = d.id AND d.orden > 1 AND d.cuantos > 1
        RETURNING s.*
    )
    INSERT INTO merge_operation_changes
           (id, merge_operation_id, household_id, table_name, row_pk,
            change_type, old_row)
    SELECT gen_random_uuid(), :operacion, :hogar, 'transaction_splits', condenados.id,
           'delete', to_jsonb(condenados)
      FROM condenados
    """
)

# 8.1 antes de 8.2: después de sumar ya no se puede leer el valor anterior.
SQL_DIARIO_PRESUPUESTO = text(
    """
    INSERT INTO merge_operation_changes
           (id, merge_operation_id, household_id, table_name, row_pk,
            change_type, column_name, old_value, new_value)
    SELECT gen_random_uuid(), :operacion, :hogar, 'budget_allocations', t.id,
           'update', c.columna, c.antes, c.despues
      FROM budget_allocations t
      JOIN budget_allocations s ON s.budget_period_id = t.budget_period_id
                               AND s.category_id = :origen
      CROSS JOIN LATERAL (VALUES
          ('allocated_amount', to_jsonb(t.allocated_amount::text),
                               to_jsonb((t.allocated_amount + s.allocated_amount)::text)),
          ('carryover_in',     to_jsonb(t.carryover_in::text),
                               to_jsonb((t.carryover_in + s.carryover_in)::text)),
          ('is_locked',        to_jsonb(t.is_locked), to_jsonb(t.is_locked OR s.is_locked)),
          ('note',             to_jsonb(t.note),
                               to_jsonb(NULLIF(concat_ws(' · ',
                                   NULLIF(t.note, ''),
                                   CASE WHEN s.note IS DISTINCT FROM t.note
                                        THEN NULLIF(s.note, '') END), ''))),
          ('source',           to_jsonb(t.source), to_jsonb('merge'::text))
      ) AS c(columna, antes, despues)
     WHERE t.household_id = :hogar AND t.category_id = :destino
    """
)

# 8.2 La suma, que es la única resolución que deja «disponible» como estaba (§4.5).
SQL_SUMAR_PRESUPUESTO = text(
    """
    UPDATE budget_allocations t
       SET allocated_amount = t.allocated_amount + s.allocated_amount,
           carryover_in     = t.carryover_in + s.carryover_in,
           is_locked        = t.is_locked OR s.is_locked,
           note             = NULLIF(concat_ws(' · ',
                                  NULLIF(t.note, ''),
                                  CASE WHEN s.note IS DISTINCT FROM t.note
                                       THEN NULLIF(s.note, '') END), ''),
           source           = 'merge'
      FROM budget_allocations s
     WHERE s.budget_period_id = t.budget_period_id
       AND s.category_id = :origen
       AND t.household_id = :hogar
       AND t.category_id = :destino
    """
)

# 8.3 antes de 8.4: al revés, el UPDATE chocaría con la unicidad (periodo, temática).
SQL_BORRAR_PRESUPUESTO_EN_COLISION = text(
    """
    WITH condenadas AS (
        DELETE FROM budget_allocations AS s
         WHERE s.household_id = :hogar
           AND s.category_id = :origen
           AND EXISTS (SELECT 1 FROM budget_allocations t
                        WHERE t.budget_period_id = s.budget_period_id
                          AND t.category_id = :destino)
        RETURNING s.*
    )
    INSERT INTO merge_operation_changes
           (id, merge_operation_id, household_id, table_name, row_pk,
            change_type, old_row)
    SELECT gen_random_uuid(), :operacion, :hogar, 'budget_allocations', condenadas.id,
           'delete', to_jsonb(condenadas)
      FROM condenadas
    """
)

# 9.2 Dos reglas idénticas apuntando ahora a la misma temática: se desactiva la de
# menor prioridad. No se borra: la escribió una persona.
SQL_DESACTIVAR_REGLAS_DUPLICADAS = text(
    """
    WITH ordenadas AS (
        SELECT id, row_number() OVER (PARTITION BY conditions, set_category_id
                                      ORDER BY priority, created_at) AS orden
          FROM categorization_rules
         WHERE household_id = :hogar AND set_category_id = :destino AND is_active
    ),
    desactivadas AS (
        UPDATE categorization_rules r SET is_active = false
          FROM ordenadas o WHERE r.id = o.id AND o.orden > 1
        RETURNING r.id
    )
    INSERT INTO merge_operation_changes
           (id, merge_operation_id, household_id, table_name, row_pk,
            change_type, column_name, old_value, new_value)
    SELECT gen_random_uuid(), :operacion, :hogar, 'categorization_rules', desactivadas.id,
           'update', 'is_active', to_jsonb(true), to_jsonb(false)
      FROM desactivadas
    """
)


def _sql_reescribir_jsonb(tabla: str, columna: str) -> str:
    """Reemplazo textual controlado del identificador dentro de un JSONB.

    Es seguro porque un UUID canónico no es subcadena de otro UUID ni de ningún
    otro valor razonable. El valor anterior se guarda **completo**, así que
    deshacer restaura el documento entero y no depende de invertir el reemplazo.
    El paso que siempre se olvida: un filtro guardado que de pronto no devuelve nada.
    """
    _validar_destino(tabla, columna)
    return f"""
        WITH antes AS (
            SELECT id, {columna} AS valor FROM {tabla}
             WHERE household_id = :hogar
               AND {columna} IS NOT NULL
               AND strpos({columna}::text, cast(:origen_txt as text)) > 0
        ),
        movidas AS (
            UPDATE {tabla} d
               SET {columna} = replace(d.{columna}::text,
                                       cast(:origen_txt as text),
                                       cast(:destino_txt as text))::jsonb
              FROM antes a
             WHERE d.id = a.id
            RETURNING d.id, a.valor AS valor_antiguo, d.{columna} AS valor_nuevo
        )
        INSERT INTO merge_operation_changes
               (id, merge_operation_id, household_id, table_name, row_pk,
                change_type, column_name, old_value, new_value)
        SELECT gen_random_uuid(), :operacion, :hogar, '{tabla}', movidas.id,
               'update', '{columna}', movidas.valor_antiguo, movidas.valor_nuevo
          FROM movidas
    """


# Solo las hijas **vivas** cambian de madre: una lápida conserva su `parent_id`
# (§4.8, paso 12), y moverla bajo el destino haría que al deshacer dos temáticas
# homónimas quedasen activas bajo la misma madre a la vez.
SQL_REPARENTAR_HIJAS = text(
    """
    WITH antes AS (
        SELECT id, parent_id FROM categories
         WHERE household_id = :hogar AND parent_id = :origen
           AND archived_at IS NULL AND merged_into_id IS NULL
    ),
    movidas AS (
        UPDATE categories c SET parent_id = :destino
          FROM antes a WHERE c.id = a.id
        RETURNING c.id, a.parent_id AS madre_antigua
    )
    INSERT INTO merge_operation_changes
           (id, merge_operation_id, household_id, table_name, row_pk,
            change_type, column_name, old_value, new_value)
    SELECT gen_random_uuid(), :operacion, :hogar, 'categories', movidas.id,
           'update', 'parent_id',
           to_jsonb(cast(movidas.madre_antigua as text)), to_jsonb(cast(:destino_txt as text))
      FROM movidas
    """
)


async def _periodos_cerrados(
    sesion: AsyncSession, hogar: uuid.UUID, origen: uuid.UUID
) -> list[str]:
    filas = await sesion.execute(
        text(
            """
            SELECT to_char(p.period_month, 'YYYY-MM') AS periodo
              FROM budget_allocations s
              JOIN budget_periods p ON p.id = s.budget_period_id
             WHERE s.household_id = :hogar AND s.category_id = :origen
               AND p.closed_at IS NOT NULL
             ORDER BY p.period_month
            """
        ),
        {"hogar": hogar, "origen": origen},
    )
    return [fila.periodo for fila in filas]


async def _fusionar_par(
    alcance: AlcanceHogar,
    origen: Category,
    destino: Category,
    opciones: OpcionesFusion,
    padre: uuid.UUID | None = None,
) -> tuple[MergeOperation, ResumenFusion]:
    """Los pasos 1 a 12 de §4.7 para un único par origen-destino."""
    sesion = alcance.sesion
    hogar = alcance.household_id
    resumen = ResumenFusion()

    cerrados = await _periodos_cerrados(sesion, hogar, origen.id)
    if cerrados and not opciones.force:
        # RN-20: un periodo cerrado bloquea la fusión salvo `force`.
        raise Conflicto(
            "Hay asignaciones de presupuesto en periodos ya cerrados ("
            + ", ".join(cerrados[:3])
            + (" y más" if len(cerrados) > 3 else "")
            + "). Confirma con «force» si aceptas que esos informes cambien.",
            codigo="periodo_cerrado",
        )

    # PASO 1 y 2 — Bitácora abierta y fila del origen congelada.
    operacion = MergeOperation(
        household_id=hogar,
        entity_type="category",
        source_id=origen.id,
        target_id=destino.id,
        source_label=origen.name,
        target_label=destino.name,
        status="running",
        options=opciones.como_json(),
        parent_merge_operation_id=padre,
        performed_by_id=alcance.usuario.id,
        started_at=datetime.now(UTC),
    )
    sesion.add(operacion)
    await sesion.flush()

    # Los identificadores viajan dos veces: como `uuid` para comparar columnas y
    # como texto para el diario. Un mismo parámetro no puede tener los dos tipos.
    contexto: dict[str, Any] = {
        "hogar": hogar,
        "origen": origen.id,
        "destino": destino.id,
        "operacion": operacion.id,
        "origen_txt": str(origen.id),
        "destino_txt": str(destino.id),
    }
    instantanea = await sesion.scalar(
        text("SELECT to_jsonb(c) FROM categories c WHERE id = :origen"), {"origen": origen.id}
    )

    # PASO 4 — Hijas: primero las fusiones recursivas, luego el reparentado.
    if opciones.move_children:
        gemelas = (await sesion.execute(SQL_HIJAS_EN_CONFLICTO, contexto)).all()
        for gemela in gemelas:
            hija = await _bloquear(sesion, hogar, gemela.hija)
            hermana = await _bloquear(sesion, hogar, gemela.gemela)
            validar_par(hija, hermana)
            # Recursión en profundidad, dentro de la misma transacción: deshacer la
            # madre deshace las hijas porque la clave ajena es CASCADE.
            _, parcial = await _fusionar_par(alcance, hija, hermana, opciones, padre=operacion.id)
            resumen.transactions += parcial.transactions
            resumen.splits += parcial.splits
            resumen.invoice_lines += parcial.invoice_lines
            resumen.children_moved += 1 + parcial.children_moved
        resumen.children_moved += (
            await sesion.execute(SQL_REPARENTAR_HIJAS, contexto)
        ).rowcount or 0

    # PASO 5 a 7 — Transacciones, splits y líneas de factura.
    resumen.transactions += await _reasignar(sesion, contexto, "transactions", "category_id")
    resumen.splits += await _reasignar(sesion, contexto, "transaction_splits", "category_id")
    if opciones.collapse_duplicate_splits:
        await sesion.execute(SQL_COLAPSAR_SPLITS, contexto)
    resumen.invoice_lines += await _reasignar(sesion, contexto, "invoice_lines", "category_id")

    # PASO 8 — Presupuesto: el orden de las cuatro sentencias no es negociable.
    await sesion.execute(SQL_DIARIO_PRESUPUESTO, contexto)
    await sesion.execute(SQL_SUMAR_PRESUPUESTO, contexto)
    await sesion.execute(SQL_BORRAR_PRESUPUESTO_EN_COLISION, contexto)
    resumen.budget_periods += await _reasignar(
        sesion, contexto, "budget_allocations", "category_id"
    )

    # PASO 9 a 11 — Reglas, recurrentes, objetivos, avisos y referencias en JSONB.
    resumen.rules += await _reasignar(sesion, contexto, "categorization_rules", "set_category_id")
    await sesion.execute(SQL_DESACTIVAR_REGLAS_DUPLICADAS, contexto)
    resumen.recurring += await _reasignar(sesion, contexto, "recurring_rules", "category_id")
    resumen.goals += await _reasignar(sesion, contexto, "goals", "category_id")
    await _reasignar(sesion, contexto, "alerts", "category_id")
    resumen.products += await _reasignar(sesion, contexto, "products", "category_id")
    resumen.payees += await _reasignar(sesion, contexto, "payees", "default_category_id")
    await sesion.execute(text(_sql_reescribir_jsonb("saved_views", "filters")), contexto)
    await sesion.execute(
        text(_sql_reescribir_jsonb("recurring_rules", "template_splits")), contexto
    )

    # PASO 12 — Lápida. Conserva su `parent_id` para que la miga de pan de un
    # informe de hace dos años siga teniendo sentido.
    ranura, bloqueada = origen.color_slot, origen.is_locked
    # Se lee el `archived_at` de antes: fusionar una temática **ya archivada** es
    # legítimo, y anotar `None` como valor previo hacía que el deshacer la
    # resucitase activa, con sus hijas archivadas y el árbol descuadrado.
    archivada_antes = await sesion.scalar(
        text("SELECT archived_at::text FROM categories WHERE id = :origen"),
        {"origen": origen.id},
    )
    await sesion.execute(
        text(
            """
            UPDATE categories
               SET archived_at = now(), merged_into_id = :destino,
                   color_slot = NULL, is_locked = false
             WHERE household_id = :hogar AND id = :origen
            """
        ),
        contexto,
    )
    marca = await sesion.scalar(
        text("SELECT archived_at::text FROM categories WHERE id = :origen"),
        {"origen": origen.id},
    )
    # El orden importa: al deshacer se recorre al revés, y `merged_into_id` debe
    # volver a NULL antes que `archived_at`.
    await _anotar(
        sesion, operacion.id, hogar, "categories", origen.id, "archived_at", archivada_antes, marca
    )
    await _anotar(
        sesion,
        operacion.id,
        hogar,
        "categories",
        origen.id,
        "merged_into_id",
        None,
        str(destino.id),
    )
    # Libera la ranura de color: vuelve a la cola de asignación (regla 5 de §2.4).
    await _anotar(sesion, operacion.id, hogar, "categories", origen.id, "color_slot", ranura, None)
    await _anotar(
        sesion, operacion.id, hogar, "categories", origen.id, "is_locked", bloqueada, False
    )

    # PASO 15 — Cerrar la bitácora.
    filas = await sesion.scalar(
        text("SELECT count(*) FROM merge_operation_changes WHERE merge_operation_id = :operacion"),
        {"operacion": operacion.id},
    )
    operacion.status = "done"
    operacion.finished_at = datetime.now(UTC)
    operacion.undo_deadline = operacion.finished_at + timedelta(days=DIAS_PARA_DESHACER)
    operacion.source_snapshot = instantanea
    operacion.counts = {
        "transactions": resumen.transactions,
        "splits": resumen.splits,
        "invoice_lines": resumen.invoice_lines,
        "budget_allocations": resumen.budget_periods,
        "rules": resumen.rules,
        "recurring": resumen.recurring,
        "goals": resumen.goals,
        "products": resumen.products,
        "payees": resumen.payees,
        "children": resumen.children_moved,
        "rows": int(filas or 0),
        "closed_periods": cerrados,
    }
    await sesion.flush()
    return operacion, resumen


async def _bloquear_hogar(sesion: AsyncSession, hogar: uuid.UUID) -> None:
    """Serializa las fusiones del hogar y acota el tiempo de la transacción.

    El aislamiento `REPEATABLE READ` que sugiere §4.7 no se fija: `SET TRANSACTION
    ISOLATION LEVEL` tiene que ser la primera sentencia de la transacción y la
    dependencia de alcance ya ha ejecutado el `set_config` del row level security.
    Lo que de verdad serializa es este bloqueo más el `FOR UPDATE` de cada fila.
    """
    await sesion.execute(text(f"SET LOCAL statement_timeout = '{TIEMPO_MAXIMO}'"))
    await sesion.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:clave, 0))"),
        {"clave": f"merge:{hogar}"},
    )


async def fusionar(
    alcance: AlcanceHogar,
    origen_ids: list[uuid.UUID],
    destino_id: uuid.UUID,
    opciones: OpcionesFusion,
) -> ResultadoFusion:
    """Fusiona una o varias temáticas en el destino. Todo o nada.

    Con varios orígenes, la operación del primero hace de raíz y las demás cuelgan
    de ella: así «deshacer» es una sola acción para el usuario, igual que lo fue
    «fusionar».
    """
    sesion = alcance.sesion
    hogar = alcance.household_id
    await _bloquear_hogar(sesion, hogar)

    destino = await _bloquear(sesion, hogar, destino_id)
    raiz: MergeOperation | None = None
    origenes: list[Category] = []
    resumen = ResumenFusion()

    for origen_id in origen_ids:
        origen = await _bloquear(sesion, hogar, origen_id)
        validar_par(origen, destino)
        origenes.append(origen)
        operacion, parcial = await _fusionar_par(
            alcance, origen, destino, opciones, padre=raiz.id if raiz else None
        )
        raiz = raiz or operacion
        for campo in (
            "transactions",
            "splits",
            "invoice_lines",
            "rules",
            "recurring",
            "products",
            "payees",
            "goals",
            "budget_periods",
            "children_moved",
        ):
            setattr(resumen, campo, getattr(resumen, campo) + getattr(parcial, campo))

    assert raiz is not None  # noqa: S101 - `origen_ids` viene validado con min_length=1

    # PASO 13 — La caché del árbol se reconstruye una sola vez, ya sin las lápidas.
    await sesion.execute(
        text("SELECT refresh_category_paths(cast(:hogar as uuid))"), {"hogar": hogar}
    )
    resumen.allocations_merged = await _asignado_de(sesion, hogar, destino.id)

    sesion.add(
        AuditLog(
            household_id=hogar,
            actor_user_id=alcance.usuario.id,
            action="category.merged",
            entity_table="categories",
            entity_id=destino.id,
            entity_label=destino.name,
            after={
                "merge_operation_id": str(raiz.id),
                "sources": [str(o.id) for o in origenes],
                "counts": raiz.counts,
            },
        )
    )
    await sesion.flush()
    filas = await _filas_del_arbol(sesion, raiz.id)
    # Las lápidas y las sumas se han escrito con SQL crudo: lo que la sesión tenga
    # cargado del ORM ya no es de fiar. Se caduca todo y se recargan de forma
    # explícita las filas que sí se van a leer; en asíncrono una carga perezosa
    # fuera de un `await` no es recuperable.
    sesion.expire_all()
    for objeto in (raiz, destino, alcance.usuario, *origenes):
        await sesion.refresh(objeto)
    return ResultadoFusion(
        operacion=raiz,
        origenes=origenes,
        destino=destino,
        resumen=resumen,
        filas_cambiadas=filas,
    )


async def _asignado_de(sesion: AsyncSession, hogar: uuid.UUID, tematica: uuid.UUID) -> Decimal:
    total = await sesion.scalar(
        text(
            "SELECT COALESCE(sum(allocated_amount), 0) FROM budget_allocations "
            " WHERE household_id = :hogar AND category_id = :tematica"
        ),
        {"hogar": hogar, "tematica": tematica},
    )
    return Decimal(str(total or 0))


# --------------------------------------------------------------------------- #
# Deshacer (§4.9)
# --------------------------------------------------------------------------- #

SQL_ARBOL_DE_OPERACIONES = text(
    """
    WITH RECURSIVE arbol AS (
        SELECT id FROM merge_operations WHERE id = :raiz
        UNION ALL
        SELECT m.id FROM merge_operations m JOIN arbol a
            ON m.parent_merge_operation_id = a.id
    )
    SELECT string_agg(id::text, ',') AS ids, count(*) AS cuantas FROM arbol
    """
)

SQL_FILAS_DEL_ARBOL = text(
    """
    WITH RECURSIVE arbol AS (
        SELECT id FROM merge_operations WHERE id = :raiz
        UNION ALL
        SELECT m.id FROM merge_operations m JOIN arbol a
            ON m.parent_merge_operation_id = a.id
    )
    SELECT count(*) FROM merge_operation_changes
     WHERE merge_operation_id IN (SELECT id FROM arbol)
    """
)


async def _filas_del_arbol(sesion: AsyncSession, raiz: uuid.UUID) -> int:
    return int(await sesion.scalar(SQL_FILAS_DEL_ARBOL, {"raiz": raiz}) or 0)


async def _operaciones_del_arbol(sesion: AsyncSession, raiz: uuid.UUID) -> str:
    fila = (await sesion.execute(SQL_ARBOL_DE_OPERACIONES, {"raiz": raiz})).one()
    return fila.ids or str(raiz)


SQL_CONFLICTO_POSTERIOR = text(
    """
    SELECT mo.id, mo.source_label, mo.finished_at, count(*) AS filas
      FROM merge_operation_changes posterior
      JOIN merge_operations mo ON mo.id = posterior.merge_operation_id
     WHERE posterior.household_id = :hogar
       AND mo.status = 'done'
       AND posterior.merge_operation_id <> ALL (cast(string_to_array(:ops, ',') as uuid[]))
       AND posterior.seq > (
            SELECT COALESCE(max(seq), 0) FROM merge_operation_changes
             WHERE merge_operation_id = ANY (cast(string_to_array(:ops, ',') as uuid[])))
       AND (posterior.table_name, posterior.row_pk) IN (
            SELECT table_name, row_pk FROM merge_operation_changes
             WHERE merge_operation_id = ANY (cast(string_to_array(:ops, ',') as uuid[])))
     GROUP BY mo.id, mo.source_label, mo.finished_at
     ORDER BY count(*) DESC
     LIMIT 5
    """
)

SQL_GRUPOS_DEL_DIARIO = text(
    """
    SELECT table_name, change_type, column_name, max(seq) AS orden
      FROM merge_operation_changes
     WHERE merge_operation_id = ANY (cast(string_to_array(:ops, ',') as uuid[]))
     GROUP BY table_name, change_type, column_name
     ORDER BY max(seq) DESC
    """
)

# Restaurar los splits borrados y devolver su importe al superviviente tiene que
# ocurrir en **una sola sentencia**: los disparadores AFTER se encolan hasta el
# final de la sentencia, así que `ck_transactions_split_invariant` nunca ve el
# estado intermedio en el que la suma de los repartos no cuadra con el importe.
SQL_DESHACER_SPLITS = text(
    """
    WITH cambios AS (
        SELECT * FROM merge_operation_changes
         WHERE merge_operation_id = ANY (cast(string_to_array(:ops, ',') as uuid[]))
           AND table_name = 'transaction_splits'
           AND (change_type = 'delete'
                OR column_name IN ('amount', 'notes'))
    ),
    restaurados AS (
        INSERT INTO transaction_splits
        SELECT r.* FROM cambios c
          CROSS JOIN LATERAL jsonb_populate_record(NULL::transaction_splits, c.old_row) AS r
         WHERE c.change_type = 'delete'
        RETURNING id
    ),
    -- Importe y notas se pivotan a una fila por reparto: PostgreSQL aplica una
    -- sola de las modificaciones que una misma sentencia haga sobre la misma fila,
    -- así que dos CTE de UPDATE sobre el superviviente perderían una de las dos.
    -- Con varios orígenes la misma fila se anota una vez por origen, así que hay
    -- que quedarse con la anotación **más antigua** (`seq` menor), que es la que
    -- guarda el valor de antes de la fusión. Ordenar por el valor —`max()` sobre
    -- el texto del importe— elegía un estado intermedio y el reparto restaurado
    -- no cuadraba con el importe de la transacción.
    por_fila AS (
        SELECT row_pk,
               bool_or(column_name = 'amount') AS toca_importe,
               (array_agg(old_value #>> '{}' ORDER BY seq)
                    FILTER (WHERE column_name = 'amount'))[1] AS importe,
               bool_or(column_name = 'notes')  AS toca_notas,
               (array_agg(old_value #>> '{}' ORDER BY seq)
                    FILTER (WHERE column_name = 'notes'))[1] AS notas
          FROM cambios WHERE change_type = 'update'
         GROUP BY row_pk
    ),
    actualizados AS (
        UPDATE transaction_splits s
           SET amount = CASE WHEN f.toca_importe
                             THEN f.importe::numeric(14,2) ELSE s.amount END,
               notes  = CASE WHEN f.toca_notas THEN f.notas ELSE s.notes END
          FROM por_fila f
         WHERE s.id = f.row_pk
        RETURNING s.id
    )
    SELECT (SELECT count(*) FROM restaurados)
         + (SELECT count(*) FROM actualizados) AS filas
    """
)


def _sql_restaurar_borradas(tabla: str) -> str:
    _validar_destino(tabla)
    return f"""
        INSERT INTO {tabla}
        SELECT r.* FROM merge_operation_changes c
          CROSS JOIN LATERAL jsonb_populate_record(NULL::{tabla}, c.old_row) AS r
         WHERE c.merge_operation_id = ANY (cast(string_to_array(:ops, ',') as uuid[]))
           AND c.table_name = '{tabla}' AND c.change_type = 'delete'
    """


def _sql_revertir_columna(tabla: str, columna: str) -> str:
    """Devuelve una columna a su valor de antes de la fusión.

    El `DISTINCT ON` no es cosmético: una fusión con varios orígenes anota la misma
    fila del destino una vez por origen, y sin desempate `UPDATE ... FROM` elige
    una cualquiera de las anotaciones —PostgreSQL no promete cuál—, con lo que la
    asignación de presupuesto podía quedar en un valor intermedio. La anotación de
    `seq` menor es la única que guarda el valor original.
    """
    _validar_destino(tabla, columna)
    tipo = COLUMNAS[(tabla, columna)]
    valor = "c.old_value" if (tabla, columna) in COLUMNAS_JSONB else f"{DESENVOLVER}::{tipo}"
    return f"""
        UPDATE {tabla} d SET {columna} = {valor}
          FROM (
            SELECT DISTINCT ON (row_pk) row_pk, old_value
              FROM merge_operation_changes
             WHERE merge_operation_id = ANY (cast(string_to_array(:ops, ',') as uuid[]))
               AND table_name = '{tabla}' AND change_type = 'update'
               AND column_name = '{columna}'
             ORDER BY row_pk, seq
          ) c
         WHERE d.id = c.row_pk
    """


async def deshacer(alcance: AlcanceHogar, operacion_id: uuid.UUID) -> ResultadoFusion:
    """Devuelve el hogar al estado exacto anterior a la fusión.

    Nunca se intenta una reversión parcial: si otra fusión posterior tocó alguna de
    las mismas filas, se rechaza con un mensaje que dice cuál y cuántas.
    """
    sesion = alcance.sesion
    hogar = alcance.household_id
    await _bloquear_hogar(sesion, hogar)

    operacion = (
        await sesion.execute(
            select(MergeOperation)
            .where(
                MergeOperation.id == operacion_id,
                MergeOperation.household_id == hogar,
                MergeOperation.entity_type == "category",
                # Una operación hija no se deshace por su cuenta: se deshace con su
                # madre, que es la unidad atómica. Aceptarla revertía media fusión y
                # dejaba la raíz en `done`, de modo que el siguiente deshacer de la
                # raíz reinsertaba filas ya restauradas y acababa en 500.
                MergeOperation.parent_merge_operation_id.is_(None),
            )
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if operacion is None:
        raise NoEncontrado("Esa fusión no existe.")
    if operacion.status == "reverted":
        raise Conflicto("Esta fusión ya se ha deshecho.")
    if operacion.status != "done":
        raise Conflicto("Esta fusión no llegó a completarse: no hay nada que deshacer.")
    if operacion.undo_deadline is not None and operacion.undo_deadline < datetime.now(UTC):
        raise Conflicto(
            "El plazo de treinta días para deshacer esta fusión ha terminado.",
        )

    destino = await _bloquear(sesion, hogar, operacion.target_id)
    if destino.merged_into_id is not None:
        raise Conflicto(
            f"«{destino.name}» se ha fusionado a su vez con otra temática. Deshaz primero "
            "esa fusión.",
        )

    ops = await _operaciones_del_arbol(sesion, operacion.id)
    parametros = {"ops": ops, "hogar": hogar}

    posterior = (await sesion.execute(SQL_CONFLICTO_POSTERIOR, parametros)).all()
    if posterior:
        peor = posterior[0]
        fecha = peor.finished_at.strftime("%d/%m/%Y") if peor.finished_at else "más reciente"
        raise Conflicto(
            f"No se puede deshacer: la fusión de «{peor.source_label}» del {fecha} modificó "
            f"{peor.filas} de estos registros. Deshaz esa primero.",
        )

    filas = await _revertir_diario(sesion, parametros)

    await sesion.execute(
        text("SELECT refresh_category_paths(cast(:hogar as uuid))"), {"hogar": hogar}
    )

    ahora = datetime.now(UTC)
    await sesion.execute(
        text(
            """
            WITH RECURSIVE arbol AS (
                SELECT id FROM merge_operations WHERE id = :raiz
                UNION ALL
                SELECT m.id FROM merge_operations m JOIN arbol a
                    ON m.parent_merge_operation_id = a.id
            )
            UPDATE merge_operations SET status = 'reverted', reverted_at = :ahora,
                   reverted_by_id = :usuario
             WHERE id IN (SELECT id FROM arbol)
            """
        ),
        {"raiz": operacion.id, "ahora": ahora, "usuario": alcance.usuario.id},
    )

    origen = await _cargar(sesion, hogar, operacion.source_id)
    sesion.add(
        AuditLog(
            household_id=hogar,
            actor_user_id=alcance.usuario.id,
            action="category.merge_reverted",
            entity_table="categories",
            entity_id=origen.id,
            entity_label=origen.name,
            after={"merge_operation_id": str(operacion.id), "rows": filas},
        )
    )
    await sesion.flush()
    sesion.expire_all()
    for objeto in (operacion, alcance.usuario):
        await sesion.refresh(objeto)
    return ResultadoFusion(
        operacion=operacion,
        origenes=[await _cargar(sesion, hogar, operacion.source_id)],
        destino=await _cargar(sesion, hogar, operacion.target_id),
        resumen=ResumenFusion(
            allocations_merged=await _asignado_de(sesion, hogar, operacion.target_id)
        ),
        filas_cambiadas=filas,
    )


async def _revertir_diario(sesion: AsyncSession, parametros: dict[str, Any]) -> int:
    """Recorre el diario por grupos, en orden descendente de `seq`.

    Se agrupa por `(tabla, tipo, columna)` y se ordena por el `seq` mayor de cada
    grupo: una sentencia por grupo en lugar de una por fila, que es la diferencia
    entre deshacer una fusión de veinte mil transacciones en un segundo o en media
    hora. Dentro de un grupo el orden es irrelevante porque las filas son disjuntas.
    """
    grupos = (await sesion.execute(SQL_GRUPOS_DEL_DIARIO, {"ops": parametros["ops"]})).all()
    if not grupos:
        return 0

    def es_atomico(grupo: Row[Any]) -> bool:
        return grupo.table_name == "transaction_splits" and (
            grupo.change_type == "delete" or grupo.column_name in ("amount", "notes")
        )

    atomicos = [g for g in grupos if es_atomico(g)]
    pasos: list[tuple[int, str | None, Row[Any] | None]] = [
        (g.orden, None, g) for g in grupos if not es_atomico(g)
    ]
    if atomicos:
        pasos.append((max(g.orden for g in atomicos), "splits", None))
    pasos.sort(key=lambda paso: paso[0], reverse=True)

    filas = 0
    for _, especial, grupo in pasos:
        if especial == "splits":
            filas += int(await sesion.scalar(SQL_DESHACER_SPLITS, {"ops": parametros["ops"]}) or 0)
            continue
        assert grupo is not None  # noqa: S101 - los dos casos son exhaustivos
        if grupo.change_type == "delete":
            sql = _sql_restaurar_borradas(grupo.table_name)
        else:
            sql = _sql_revertir_columna(grupo.table_name, grupo.column_name)
        resultado = await sesion.execute(text(sql), {"ops": parametros["ops"]})
        filas += resultado.rowcount or 0
    return filas
