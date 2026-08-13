/**
 * Recurrentes y suscripciones. §3.8 del contrato.
 *
 * Solo lo que necesitan las pantallas montadas: el alta de un ingreso que se
 * repite cada mes desde el asistente inicial y el listado de próximos
 * vencimientos. El resto del recurso (detección, pausa, materialización) se
 * añadirá cuando tenga pantalla.
 */
import { api } from '@/lib/api'
import {
  conQuery,
  type CategoriaRef,
  type FechaISO,
  type Importe,
  type Pagina,
  type Params,
  type ParamsListado,
  type UUID,
} from './comun'

export type Frecuencia =
  | 'weekly'
  | 'biweekly'
  | 'monthly'
  | 'bimonthly'
  | 'quarterly'
  | 'semiannual'
  | 'yearly'
  | 'every_n_days'
  | 'last_weekday_of_month'

export const ETIQUETA_FRECUENCIA: Record<Frecuencia, string> = {
  weekly: 'Cada semana',
  biweekly: 'Cada dos semanas',
  monthly: 'Cada mes',
  bimonthly: 'Cada dos meses',
  quarterly: 'Cada trimestre',
  semiannual: 'Cada semestre',
  yearly: 'Cada año',
  every_n_days: 'Cada N días',
  last_weekday_of_month: 'El último día laborable del mes',
}

export interface RecurrenteCrear {
  name: string
  kind?: 'expense' | 'income'
  account_id: UUID
  category_id?: UUID | null
  amount: Importe
  currency?: string
  frequency: Frecuencia
  interval?: number
  /** `-1` = último día del mes, el caso de las nóminas. */
  day_of_month?: number | null
  starts_on: FechaISO
  is_subscription?: boolean
  note?: string | null
}

export interface Recurrente {
  id: UUID
  name: string
  kind: 'expense' | 'income'
  account_id: UUID
  category?: CategoriaRef | null
  amount: Importe
  currency: string
  frequency: Frecuencia
  interval: number
  next_occurrence_on?: FechaISO | null
  is_active: boolean
  is_subscription: boolean
}

export const apiRecurrentes = {
  listar: (filtro: ParamsListado & { is_active?: boolean } = {}) =>
    api.get<Pagina<Recurrente>>(conQuery('/recurring', filtro as Params)),
  crear: (cuerpo: RecurrenteCrear) => api.post<Recurrente>('/recurring', cuerpo),
}
