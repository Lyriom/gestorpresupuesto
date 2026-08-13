/**
 * Cuentas, saldos y patrimonio. §3.3 del contrato.
 *
 * `current_balance` es derivado (RN-08): no existe como campo editable.
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
  type UUID,
} from './comun'

export type TipoCuenta =
  | 'checking'
  | 'savings'
  | 'cash'
  | 'credit_card'
  | 'investment'
  | 'debt'

/** Rótulos en español de España para los selectores y las tablas. */
export const ETIQUETA_TIPO_CUENTA: Record<TipoCuenta, string> = {
  checking: 'Corriente',
  savings: 'Ahorro',
  cash: 'Efectivo',
  credit_card: 'Tarjeta de crédito',
  investment: 'Inversión',
  debt: 'Deuda',
}

export const TIPOS_CUENTA: TipoCuenta[] = [
  'checking',
  'savings',
  'cash',
  'credit_card',
  'investment',
  'debt',
]

export interface CuentaRef {
  id: UUID
  name: string
  type: TipoCuenta
  currency: string
  color?: string | null
}

export interface Cuenta {
  id: UUID
  created_at: InstanteISO
  updated_at: InstanteISO
  name: string
  type: TipoCuenta
  currency: string
  initial_balance: Importe
  current_balance: Importe
  /** Tarjetas: límite − saldo dispuesto. */
  available_balance?: Importe | null
  is_liability: boolean
  is_archived: boolean
  is_excluded_from_net_worth: boolean
  color: string | null
  icon: string | null
  opened_on?: FechaISO | null
  last_transaction_on: FechaISO | null
  transactions_count: number
  reconciled_through: FechaISO | null
  credit_limit?: Importe | null
  interest_rate?: string | number | null
  monthly_payment?: Importe | null
  ends_on?: FechaISO | null
}

export interface CuentaCrear {
  name: string
  type: TipoCuenta
  currency?: string
  initial_balance?: Importe
  opened_on?: FechaISO | null
  color?: string | null
  icon?: string | null
  is_excluded_from_net_worth?: boolean
  credit_limit?: Importe | null
  interest_rate?: string | null
  monthly_payment?: Importe | null
  ends_on?: FechaISO | null
}

export interface CuentaActualizar {
  name?: string
  currency?: string
  opened_on?: FechaISO | null
  color?: string | null
  icon?: string | null
  is_excluded_from_net_worth?: boolean
  credit_limit?: Importe | null
  interest_rate?: string | null
  monthly_payment?: Importe | null
  ends_on?: FechaISO | null
  note?: string | null
}

export interface TotalPorTipo {
  type: TipoCuenta
  total: Importe
  accounts: number
}

/** Activos, pasivos y patrimonio neto actual (F-11, RN-25). */
export interface ResumenCuentas {
  as_of: FechaISO
  currency: string
  assets: Importe
  liabilities: Importe
  net_worth: Importe
  by_type: TotalPorTipo[]
}

export interface SaldoCuenta {
  account_id: UUID
  as_of: FechaISO
  balance: Importe
  reconciled_balance: Importe
  unreconciled_amount: Importe
  pending_recurring: Importe
}

export interface FiltroCuentas extends ParamsListado {
  type?: TipoCuenta[]
  is_archived?: boolean
  as_of?: FechaISO
}

export const apiCuentas = {
  listar: (filtro: FiltroCuentas = {}) =>
    api.get<Pagina<Cuenta>>(conQuery('/accounts', filtro as Params)),
  resumen: (asOf?: FechaISO) =>
    api.get<ResumenCuentas>(conQuery('/accounts/summary', { as_of: asOf })),
  obtener: (id: UUID) => api.get<Cuenta>(`/accounts/${id}`),
  crear: (cuerpo: CuentaCrear) => api.post<Cuenta>('/accounts', cuerpo),
  actualizar: (id: UUID, cuerpo: CuentaActualizar) =>
    api.patch<Cuenta>(`/accounts/${id}`, cuerpo),
  borrar: (id: UUID) => api.delete<void>(`/accounts/${id}`),
  archivar: (id: UUID) => api.post<Cuenta>(`/accounts/${id}/archive`),
  desarchivar: (id: UUID) => api.post<Cuenta>(`/accounts/${id}/unarchive`),
  saldo: (id: UUID, asOf?: FechaISO) =>
    api.get<SaldoCuenta>(conQuery(`/accounts/${id}/balance`, { as_of: asOf })),
}
