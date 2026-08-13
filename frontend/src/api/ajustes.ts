/**
 * Ajustes del usuario, vistas guardadas y almacenamiento. §3.20 del contrato.
 */
import { api } from '@/lib/api'
import type { Tema } from './auth'
import type { InstanteISO, UUID } from './comun'

export type ArrastreNegativo = 'carry' | 'reset'
export type PeriodicidadDigest = 'off' | 'weekly' | 'monthly'

export interface Ajustes {
  currency: string
  locale: string
  timezone: string
  /** 0 = lunes. */
  first_day_of_week: number
  theme: Tema
  rollover_default: boolean
  rollover_negative: ArrastreNegativo
  /** `0.9` avisa al 90 % consumido. */
  budget_alert_pct: number
  /** `3.0` avisa a partir de +3 %. */
  price_increase_pct: number
  anomaly_z: number
  duplicate_window_days: number
  product_match_threshold: number
  digest: PeriodicidadDigest
}

export type AjustesActualizar = Partial<Ajustes>

export interface VistaGuardada {
  id: UUID
  created_at: InstanteISO
  updated_at: InstanteISO
  name: string
  resource: 'transactions' | 'invoices' | 'products' | 'alerts'
  filters: Record<string, unknown>
  is_pinned: boolean
  last_used_at?: InstanteISO | null
}

export interface Almacenamiento {
  invoices_bytes: number
  attachments_bytes: number
  exports_bytes: number
  total_bytes: number
  quota_bytes?: number | null
  files_count: number
  used_pct?: number | null
}

export const apiAjustes = {
  obtener: () => api.get<Ajustes>('/settings'),
  actualizar: (cuerpo: AjustesActualizar) => api.patch<Ajustes>('/settings', cuerpo),

  vistas: () => api.get<VistaGuardada[]>('/settings/views'),
  guardarVista: (cuerpo: {
    name: string
    resource?: VistaGuardada['resource']
    filters: Record<string, unknown>
    is_pinned?: boolean
  }) => api.post<VistaGuardada>('/settings/views', cuerpo),
  borrarVista: (id: UUID) => api.delete<void>(`/settings/views/${id}`),

  almacenamiento: () => api.get<Almacenamiento>('/settings/storage'),
}
