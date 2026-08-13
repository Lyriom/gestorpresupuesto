/**
 * Alertas. §3.16 del contrato.
 *
 * RN-73: toda alerta es accionable y financiera. El texto llega ya redactado en
 * español desde el backend, así que la interfaz no compone mensajes.
 */
import { api } from '@/lib/api'
import {
  conQuery,
  type FechaISO,
  type Importe,
  type InstanteISO,
  type Pagina,
  type Params,
  type ParamsListado,
  type Periodo,
  type UUID,
} from './comun'

export type TipoAlerta =
  | 'budget_overspent'
  | 'budget_near_limit'
  | 'product_price_increase'
  | 'recurring_price_increase'
  | 'unusual_spending'
  | 'upcoming_charge'
  | 'duplicate_suspected'
  | 'invoice_low_confidence'
  | 'goal_at_risk'
  | 'account_unreconciled'

export type Severidad = 'info' | 'warning' | 'critical'

export interface Alerta {
  id: UUID
  type: TipoAlerta
  severity: Severidad
  title: string
  message: string
  period?: Periodo | null
  amount?: Importe | null
  change_pct?: number | null
  is_read: boolean
  is_dismissed: boolean
  muted_until?: InstanteISO | null
  created_at: InstanteISO
  resolved_at?: InstanteISO | null
  category_id?: UUID | null
  transaction_id?: UUID | null
  product_id?: UUID | null
  recurring_id?: UUID | null
  invoice_id?: UUID | null
  goal_id?: UUID | null
  account_id?: UUID | null
}

export interface ContadorAlertas {
  unread: number
  by_severity: Partial<Record<Severidad, number>>
}

export interface FiltroAlertas extends ParamsListado {
  type?: TipoAlerta[]
  severity?: Severidad[]
  is_read?: boolean
  is_dismissed?: boolean
  period?: Periodo
  date_from?: FechaISO
  date_to?: FechaISO
}

export const apiAlertas = {
  listar: (filtro: FiltroAlertas = {}) =>
    api.get<Pagina<Alerta>>(conQuery('/alerts', filtro as Params)),
  sinLeer: () => api.get<ContadorAlertas>('/alerts/unread-count'),
  marcarLeida: (id: UUID) => api.post<Alerta>(`/alerts/${id}/read`),
  marcarTodasLeidas: (periodo?: Periodo, tipos: TipoAlerta[] = []) =>
    api.post<{ affected: number }>('/alerts/read-all', { period: periodo, type: tipos }),
  descartar: (id: UUID, muteDays = 30) =>
    api.post<void>(`/alerts/${id}/dismiss`, { mute_days: muteDays }),
}
