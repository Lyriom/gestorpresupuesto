/**
 * Temáticas jerárquicas: árbol, movimiento, reordenación, archivado y fusión.
 *
 * §3.4 del contrato. Los nombres de campo son los de
 * `backend/app/schemas/categoria.py`.
 */
import { api } from '@/lib/api'
import {
  conQuery,
  type CategoriaRef,
  type FechaISO,
  type Importe,
  type InstanteISO,
  type Pagina,
  type Params,
  type ParamsListado,
  type Periodo,
  type UUID,
} from './comun'

/** RN-11: hasta seis niveles (`depth` de 0 a 5). */
export const PROFUNDIDAD_MAXIMA = 6

export type TipoTematica = 'expense' | 'income'

export interface Categoria {
  id: UUID
  created_at: InstanteISO
  updated_at: InstanteISO
  name: string
  parent_id: UUID | null
  kind: TipoTematica
  /** Ruta materializada de UUID: `a1b2/…/f9e8`. */
  path: string
  depth: number
  position: number
  color: string | null
  icon: string | null
  rollover_enabled: boolean
  is_locked: boolean
  is_archived: boolean
  is_default: boolean
  monthly_target: Importe | null
  children_count: number
  descendants_count: number
  /** Miga de pan, de la raíz al padre. */
  ancestors: CategoriaRef[]
  // Solo con include=stats o ?period=
  transactions_count?: number | null
  spent?: Importe | null
  allocated?: Importe | null
}

/** Nodo del árbol de `GET /categories/tree`, ya ordenado por `position`. */
export interface CategoriaNodo extends Categoria {
  children: CategoriaNodo[]
}

export interface CategoriaCrear {
  name: string
  parent_id?: UUID | null
  kind?: TipoTematica
  color?: string | null
  icon?: string | null
  rollover_enabled?: boolean
  is_locked?: boolean
  monthly_target?: Importe | null
  position?: number | null
}

export interface CategoriaActualizar {
  name?: string
  color?: string | null
  icon?: string | null
  rollover_enabled?: boolean
  is_locked?: boolean
  monthly_target?: Importe | null
  is_default?: boolean
}

export interface CategoriaMoverCrear {
  parent_id: UUID | null
  position: number
}

export interface CategoriaFusionCrear {
  source_ids: UUID[]
  target_id: UUID
  move_children?: boolean
  keep_source_names_as_alias?: boolean
  /** Reabre, recalcula y vuelve a cerrar los periodos cerrados (RN-20). */
  force?: boolean
}

/** Lo que se va a mover, antes de moverlo: es el diálogo de confirmación. */
export interface CategoriaFusionPrevia {
  target: CategoriaRef
  sources: CategoriaRef[]
  transactions: number
  splits: number
  invoice_lines: number
  rules: number
  recurring: number
  products: number
  payees: number
  goals: number
  budget_periods: number
  /** Suma de asignaciones que quedará en la temática destino. */
  allocations_merged: Importe
  children_moved: number
  /** Ej.: «El periodo 2026-03 está cerrado». */
  conflicts: string[]
}

export interface CategoriaFusionResultado extends CategoriaFusionPrevia {
  merge_id: UUID
  performed_at: InstanteISO
  undo_available_until: InstanteISO
}

/** Dónde se usa: lo que se muestra antes de borrar o fusionar (RN-14). */
export interface CategoriaUso {
  category_id: UUID
  transactions: number
  splits: number
  invoice_lines: number
  rules: number
  recurring: number
  goals: number
  allocations: number
  products: number
  payees: number
  first_used_on: FechaISO | null
  last_used_on: FechaISO | null
  /** `false` obliga a reasignar o archivar. */
  can_hard_delete: boolean
}

export interface FiltroCategorias extends ParamsListado {
  parent_id?: UUID
  kind?: TipoTematica
  max_depth?: number
  is_archived?: boolean
  period?: Periodo
  include?: 'stats'
}

export const apiCategorias = {
  listar: (filtro: FiltroCategorias = {}) =>
    api.get<Pagina<Categoria>>(conQuery('/categories', filtro as Params)),

  arbol: (filtro: { is_archived?: boolean; kind?: TipoTematica; period?: Periodo } = {}) =>
    api.get<CategoriaNodo[]>(conQuery('/categories/tree', filtro as Params)),

  obtener: (id: UUID) => api.get<Categoria>(`/categories/${id}`),
  crear: (cuerpo: CategoriaCrear) => api.post<Categoria>('/categories', cuerpo),
  actualizar: (id: UUID, cuerpo: CategoriaActualizar) =>
    api.patch<Categoria>(`/categories/${id}`, cuerpo),
  borrar: (id: UUID, reassignTo?: UUID) =>
    api.delete<void>(conQuery(`/categories/${id}`, { reassign_to: reassignTo })),

  archivar: (id: UUID, cascade = false) =>
    api.post<Categoria>(conQuery(`/categories/${id}/archive`, { cascade })),
  desarchivar: (id: UUID) => api.post<Categoria>(`/categories/${id}/unarchive`),

  mover: (id: UUID, cuerpo: CategoriaMoverCrear) =>
    api.post<Categoria>(`/categories/${id}/move`, cuerpo),
  reordenar: (items: Array<{ id: UUID; parent_id: UUID | null; position: number }>) =>
    api.post<Categoria[]>('/categories/reorder', { items }),

  uso: (id: UUID) => api.get<CategoriaUso>(`/categories/${id}/usage`),
  previsualizarFusion: (cuerpo: CategoriaFusionCrear) =>
    api.post<CategoriaFusionPrevia>('/categories/merge/preview', cuerpo),
  fusionar: (cuerpo: CategoriaFusionCrear) =>
    api.post<CategoriaFusionResultado>('/categories/merge', cuerpo),
}
