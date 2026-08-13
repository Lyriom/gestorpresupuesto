/**
 * Transacciones, desglose por temáticas (splits), transferencias y adjuntos.
 *
 * §3.5 y §3.6 del contrato. El signo lo expresa `kind`, no el importe: el caso
 * normal se envía en positivo y solo un gasto puede ser negativo (devoluciones).
 */
import { api } from '@/lib/api'
import {
  conQuery,
  type CategoriaRef,
  type ComercioRef,
  type EtiquetaRef,
  type FechaISO,
  type Importe,
  type InstanteISO,
  type Pagina,
  type Params,
  type ParamsListado,
  type ResultadoLote,
  type UUID,
} from './comun'
import type { CuentaRef } from './cuentas'

export type TipoMovimiento = 'expense' | 'income' | 'transfer'
export type EstadoMovimiento = 'pending' | 'cleared' | 'reconciled'
export type OrigenMovimiento = 'manual' | 'import' | 'invoice' | 'recurring' | 'reconciliation'

export const ETIQUETA_TIPO_MOVIMIENTO: Record<TipoMovimiento, string> = {
  expense: 'Gasto',
  income: 'Ingreso',
  transfer: 'Transferencia',
}

export const ETIQUETA_ESTADO_MOVIMIENTO: Record<EstadoMovimiento, string> = {
  pending: 'Pendiente',
  cleared: 'Confirmado',
  reconciled: 'Conciliado',
}

export interface Split {
  id: UUID
  category_id: UUID
  category?: CategoriaRef | null
  amount: Importe
  note?: string | null
  invoice_line_id?: UUID | null
}

export interface SplitCrear {
  category_id: UUID
  amount: Importe
  note?: string | null
}

export interface Adjunto {
  id: UUID
  created_at: InstanteISO
  updated_at: InstanteISO
  transaction_id?: UUID | null
  invoice_id?: UUID | null
  filename: string
  content_type: string
  size_bytes: number
  pages?: number | null
  checksum: string
  download_url: string
}

export interface Movimiento {
  id: UUID
  created_at: InstanteISO
  updated_at: InstanteISO
  kind: TipoMovimiento
  account_id: UUID
  account?: CuentaRef | null
  date: FechaISO
  /** Como se capturó, con el signo que tecleó el usuario. */
  amount: Importe
  /** Efecto sobre el saldo, ya firmado. */
  signed_amount: Importe
  currency: string
  category_id: UUID | null
  category?: CategoriaRef | null
  payee_id: UUID | null
  payee?: ComercioRef | null
  description: string | null
  note: string | null
  is_split: boolean
  splits: Split[]
  tags: EtiquetaRef[]
  attachments_count: number
  attachments: Adjunto[]
  invoice_id?: UUID | null
  recurring_id?: UUID | null
  transfer_group_id?: UUID | null
  transfer_counterpart_id?: UUID | null
  status: EstadoMovimiento
  is_reconciled: boolean
  is_anomaly: boolean
  source: OrigenMovimiento
  categorized_by?: 'user' | 'rule' | 'invoice' | 'import' | null
}

export interface MovimientoCrear {
  kind?: 'expense' | 'income'
  account_id: UUID
  date: FechaISO
  amount: Importe
  currency?: string
  /** Nulo si hay splits o si se dejan actuar las reglas. */
  category_id?: UUID | null
  payee_id?: UUID | null
  /** Crea el comercio si no existe. */
  payee_name?: string | null
  description?: string | null
  note?: string | null
  tag_ids?: UUID[]
  splits?: SplitCrear[]
  apply_rules?: boolean
  status?: EstadoMovimiento
  invoice_id?: UUID | null
  recurring_id?: UUID | null
}

export interface MovimientoActualizar {
  date?: FechaISO
  amount?: Importe
  kind?: 'expense' | 'income'
  account_id?: UUID
  category_id?: UUID | null
  payee_id?: UUID | null
  payee_name?: string | null
  description?: string | null
  note?: string | null
  tag_ids?: UUID[]
  splits?: SplitCrear[]
  status?: EstadoMovimiento
}

export interface TransferenciaCrear {
  from_account_id: UUID
  to_account_id: UUID
  date: FechaISO
  amount: Importe
  currency?: string
  fee?: Importe | null
  fee_category_id?: UUID | null
  description?: string | null
  note?: string | null
  goal_id?: UUID | null
}

export interface Transferencia {
  transfer_group_id: UUID
  date: FechaISO
  amount: Importe
  currency: string
  fee?: Importe | null
  from_account: CuentaRef
  to_account: CuentaRef
  description: string | null
  note: string | null
  goal_id?: UUID | null
  out_transaction_id: UUID
  in_transaction_id: UUID
  fee_transaction_id?: UUID | null
  created_at: InstanteISO
}

/** Relaciones que se pueden expandir con `include` (§7.1). */
export type IncluirMovimiento =
  | 'splits'
  | 'tags'
  | 'payee'
  | 'attachments'
  | 'account'
  | 'category'

/** Todos los filtros combinables de F-42. */
export interface FiltroMovimientos extends ParamsListado {
  date_from?: FechaISO
  date_to?: FechaISO
  account_id?: UUID[]
  category_id?: UUID[]
  include_children?: boolean
  kind?: TipoMovimiento[]
  status?: EstadoMovimiento[]
  min_amount?: Importe
  max_amount?: Importe
  tag_id?: UUID[]
  payee_id?: UUID[]
  has_invoice?: boolean
  has_attachments?: boolean
  only_recurring?: boolean
  only_uncategorized?: boolean
  only_anomalies?: boolean
  invoice_id?: UUID
  recurring_id?: UUID
  include?: IncluirMovimiento[]
}

export const apiMovimientos = {
  listar: (filtro: FiltroMovimientos = {}) =>
    api.get<Pagina<Movimiento>>(conQuery('/transactions', filtro as Params)),
  obtener: (id: UUID, incluir: IncluirMovimiento[] = ['splits', 'tags', 'payee', 'attachments']) =>
    api.get<Movimiento>(conQuery(`/transactions/${id}`, { include: incluir })),
  crear: (cuerpo: MovimientoCrear) => api.post<Movimiento>('/transactions', cuerpo),
  actualizar: (id: UUID, cuerpo: MovimientoActualizar) =>
    api.patch<Movimiento>(`/transactions/${id}`, cuerpo),
  borrar: (id: UUID, force = false) =>
    api.delete<void>(conQuery(`/transactions/${id}`, { force: force || undefined })),

  sustituirSplits: (id: UUID, splits: SplitCrear[]) =>
    api.put<Movimiento>(`/transactions/${id}/splits`, { splits }),
  deshacerSplits: (id: UUID, categoryId?: UUID) =>
    api.delete<Movimiento>(conQuery(`/transactions/${id}/splits`, { category_id: categoryId })),

  categorizarEnLote: (ids: UUID[], categoryId: UUID) =>
    api.post<ResultadoLote>('/transactions/bulk-categorize', { ids, category_id: categoryId }),
  borrarEnLote: (ids: UUID[], force = false) =>
    api.post<ResultadoLote>('/transactions/bulk-delete', { ids, force }),

  crearTransferencia: (cuerpo: TransferenciaCrear) =>
    api.post<Transferencia>('/transfers', cuerpo),

  adjuntos: (id: UUID) => api.get<Adjunto[]>(`/transactions/${id}/attachments`),
  subirAdjunto: (id: UUID, fichero: File, alProgresar?: (pct: number) => void) =>
    api.subir<Adjunto>(`/transactions/${id}/attachments`, fichero, {}, alProgresar),
}
