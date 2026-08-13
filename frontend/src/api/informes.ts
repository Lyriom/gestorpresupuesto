/**
 * Informes. §3.19 del contrato.
 *
 * Todos aceptan `period`/`period_from`/`period_to` o `date_from`/`date_to`, y
 * excluyen las transferencias del gasto y del ingreso (RN-21).
 */
import { api } from '@/lib/api'
import {
  conQuery,
  type CategoriaRef,
  type ComercioRef,
  type FechaISO,
  type Importe,
  type Params,
  type Periodo,
  type UUID,
} from './comun'
import type { CuentaRef, TipoCuenta } from './cuentas'

export interface ParamsInforme {
  period?: Periodo
  period_from?: Periodo
  period_to?: Periodo
  date_from?: FechaISO
  date_to?: FechaISO
  /** `csv` responde en streaming y sin paginación (§3.19). */
  format?: 'json' | 'csv'
}

/* --- Gasto por temática (F-18) ------------------------------------- */

export interface FilaGastoPorTematica {
  category: CategoriaRef
  depth: number
  parent_id?: UUID | null
  amount: Importe
  share_pct: number
  transactions: number
  allocated?: Importe | null
  /** `allocated − amount`; negativo es sobrepaso. */
  variance?: Importe | null
  previous_amount?: Importe | null
  change_pct?: number | null
  children: FilaGastoPorTematica[]
}

export interface GastoPorTematica {
  period_from: string
  period_to: string
  currency: string
  total: Importe
  uncategorized: Importe
  rows: FilaGastoPorTematica[]
}

/* --- Ingresos y gastos (encabezado del panel) ---------------------- */

export interface FilaIngresoGasto {
  period: Periodo
  income: Importe
  expense: Importe
  savings: Importe
  savings_rate: number
}

export interface IngresoGasto {
  period_from?: Periodo | null
  period_to?: Periodo | null
  income_total: Importe
  expense_total: Importe
  savings_total: Importe
  savings_rate: number
  average_savings_rate?: number | null
  rows: FilaIngresoGasto[]
}

/* --- Cash flow (F-36) ---------------------------------------------- */

export interface PuntoCashFlowApi {
  period: string
  inflow: Importe
  outflow: Importe
  net: Importe
  cumulative: Importe
}

export interface CashFlow {
  granularity: 'month' | 'week'
  points: PuntoCashFlowApi[]
  total_inflow: Importe
  total_outflow: Importe
  net: Importe
  savings_rate: number
}

/* --- Mes a mes (F-19) ---------------------------------------------- */

export interface PuntoMensual {
  period: Periodo
  expense: Importe
  income: Importe
  net: Importe
  by_category: Record<string, Importe>
}

export interface ComparativaMensual {
  periods: Periodo[]
  series: PuntoMensual[]
  average_expense: Importe
  best_period?: Periodo | null
  worst_period?: Periodo | null
}

/* --- Top comercios (F-37) ------------------------------------------ */

export interface FilaTopComercio {
  payee?: ComercioRef | null
  amount: Importe
  transactions: number
  average_ticket: Importe
  share_pct: number
  top_category?: CategoriaRef | null
  previous_amount?: Importe | null
  change_pct?: number | null
}

export interface TopComercios {
  period_from: string
  period_to: string
  total: Importe
  rows: FilaTopComercio[]
}

/* --- Patrimonio neto (F-11) ---------------------------------------- */

export interface PuntoPatrimonio {
  period: Periodo
  assets: Importe
  liabilities: Importe
  net_worth: Importe
  change: Importe
  change_pct?: number | null
}

export interface PatrimonioPorCuenta {
  account: CuentaRef
  type: TipoCuenta
  balance: Importe
  is_liability: boolean
  change?: Importe | null
  change_pct?: number | null
}

export interface Patrimonio {
  points: PuntoPatrimonio[]
  current: Importe
  change_12m?: Importe | null
  by_account: PatrimonioPorCuenta[]
}

/* --- Subidas de precio (F-16) -------------------------------------- */

export interface FilaSubidaPrecio {
  product: { id: UUID; name: string; brand?: string | null; size_text?: string | null }
  payee?: ComercioRef | null
  previous_unit_price: string
  new_unit_price: string
  change_pct: number
  observed_at: FechaISO
  typical_quantity?: string | null
  /** Variación × cantidad habitual: ordena por lo que duele, no por el %. */
  estimated_monthly_impact?: Importe | null
}

export interface SubidasPrecio {
  period_from: string
  period_to: string
  min_change_pct: number
  total_estimated_impact: Importe
  rows: FilaSubidaPrecio[]
}

/* --- Presupuestado frente a real ----------------------------------- */

export interface FilaPresupuestoVsReal {
  period: Periodo
  category: CategoriaRef
  allocated: Importe
  spent: Importe
  variance: Importe
  used_pct: number
  is_overspent: boolean
}

export interface PresupuestoVsReal {
  period_from?: Periodo | null
  period_to?: Periodo | null
  allocated_total: Importe
  spent_total: Importe
  variance_total: Importe
  overspent_categories: number
  rows: FilaPresupuestoVsReal[]
}

export const apiInformes = {
  gastoPorTematica: (
    params: ParamsInforme & { depth?: number; category_id?: UUID; account_id?: UUID[] } = {},
  ) => api.get<GastoPorTematica>(conQuery('/reports/spending-by-category', params as Params)),

  ingresosYGastos: (params: ParamsInforme = {}) =>
    api.get<IngresoGasto>(conQuery('/reports/income-vs-expense', params as Params)),

  cashFlow: (params: ParamsInforme & { granularity?: 'month' | 'week' } = {}) =>
    api.get<CashFlow>(conQuery('/reports/cash-flow', params as Params)),

  mesAMes: (params: ParamsInforme & { category_id?: UUID[] } = {}) =>
    api.get<ComparativaMensual>(conQuery('/reports/monthly-comparison', params as Params)),

  topComercios: (params: ParamsInforme & { limit?: number; category_id?: UUID } = {}) =>
    api.get<TopComercios>(conQuery('/reports/top-payees', params as Params)),

  patrimonio: (params: ParamsInforme & { include_accounts?: boolean } = {}) =>
    api.get<Patrimonio>(conQuery('/reports/net-worth', params as Params)),

  subidasDePrecio: (params: ParamsInforme & { min_change_pct?: number } = {}) =>
    api.get<SubidasPrecio>(conQuery('/reports/price-increases', params as Params)),

  presupuestoVsReal: (params: ParamsInforme & { only_overspent?: boolean } = {}) =>
    api.get<PresupuestoVsReal>(conQuery('/reports/budget-vs-actual', params as Params)),
}
