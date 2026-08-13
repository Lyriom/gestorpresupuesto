/**
 * Presupuesto mensual, asignaciones, reasignación, arrastre y cierre.
 *
 * §3.7 del contrato. Los tipos de la barra viven en
 * `@/components/presupuesto/types` porque los consume el componente estrella;
 * aquí solo se reexportan para que quien llame a la API tenga un único sitio.
 */
import { api } from '@/lib/api'
import type {
  AsignacionTematica,
  PresupuestoMes,
} from '@/components/presupuesto/types'
import {
  conQuery,
  type CategoriaRef,
  type Importe,
  type Pagina,
  type Params,
  type Periodo,
  type UUID,
} from './comun'

export type { AsignacionTematica, PresupuestoMes }

/** Una fila del selector de mes. */
export interface ResumenPeriodo {
  period: Periodo
  income: Importe
  allocated_total: Importe
  spent_total: Importe
  is_closed: boolean
}

export interface AsignacionCrear {
  category_id: UUID
  amount: Importe
  rollover_enabled?: boolean | null
  note?: string | null
}

export interface AjustesPresupuestoCrear {
  planned_income?: Importe | null
  rollover_default?: boolean | null
  note?: string | null
}

export interface ReasignarCrear {
  from_category_id: UUID
  to_category_id: UUID
  amount: Importe
}

export interface CopiarPresupuestoCrear {
  source_period: Periodo
  strategy?: 'absolute' | 'proportional'
  overwrite?: boolean
  only_missing?: boolean
}

export interface DistribuirPresupuestoCrear {
  strategy?: 'equal' | 'last_period_share' | 'average_3m'
  category_ids?: UUID[]
  amount?: Importe | null
}

/** De dónde viene el rollover entrante de cada temática (F-26). */
export interface Arrastre {
  category_id: UUID
  category: CategoriaRef
  previous_period: Periodo
  previous_allocated: Importe
  previous_spent: Importe
  carried_in: Importe
  carried_negative: boolean
}

export const apiPresupuestos = {
  /** El payload del `BudgetBar` del mes. */
  obtener: (periodo: Periodo, opciones: { include_archived?: boolean; depth?: number } = {}) =>
    api.get<PresupuestoMes>(conQuery(`/budgets/${periodo}`, opciones as Params)),

  periodos: (desde?: Periodo, hasta?: Periodo) =>
    api.get<Pagina<ResumenPeriodo>>(
      conQuery('/budgets', { period_from: desde, period_to: hasta }),
    ),

  guardarAjustes: (periodo: Periodo, cuerpo: AjustesPresupuestoCrear) =>
    api.put<PresupuestoMes>(`/budgets/${periodo}`, cuerpo),

  /** Sustituye el reparto completo del periodo. Idempotente. */
  sustituirAsignaciones: (
    periodo: Periodo,
    allocations: AsignacionCrear[],
    removeMissing = true,
  ) =>
    api.put<PresupuestoMes>(`/budgets/${periodo}/allocations`, {
      allocations,
      remove_missing: removeMissing,
    }),

  asignarUna: (
    periodo: Periodo,
    categoryId: UUID,
    cuerpo: { amount?: Importe; rollover_enabled?: boolean; note?: string | null },
  ) => api.patch<AsignacionTematica>(`/budgets/${periodo}/allocations/${categoryId}`, cuerpo),

  reasignar: (periodo: Periodo, cuerpo: ReasignarCrear) =>
    api.post<PresupuestoMes>(`/budgets/${periodo}/reassign`, cuerpo),

  copiarDe: (periodo: Periodo, cuerpo: CopiarPresupuestoCrear) =>
    api.post<PresupuestoMes>(`/budgets/${periodo}/copy-from`, cuerpo),

  distribuir: (periodo: Periodo, cuerpo: DistribuirPresupuestoCrear) =>
    api.post<PresupuestoMes>(`/budgets/${periodo}/distribute`, cuerpo),

  arrastre: (periodo: Periodo) => api.get<Arrastre[]>(`/budgets/${periodo}/rollover`),

  cerrar: (periodo: Periodo) => api.post<PresupuestoMes>(`/budgets/${periodo}/close`),
  reabrir: (periodo: Periodo) => api.post<PresupuestoMes>(`/budgets/${periodo}/reopen`),
}
