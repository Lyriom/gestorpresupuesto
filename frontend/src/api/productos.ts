/**
 * Catálogo de productos, histórico de precios y comparativa por comercio.
 *
 * §3.14 del contrato. La tendencia la calcula el backend
 * (`app/services/precios.py`): aquí no se recalcula.
 */
import { api } from '@/lib/api'
import type { Tendencia } from '@/components/presupuesto/types'
import {
  conQuery,
  type Cantidad,
  type CategoriaRef,
  type ComercioRef,
  type FechaISO,
  type Importe,
  type InstanteISO,
  type Pagina,
  type Params,
  type ParamsListado,
  type Precio,
  type ProductoRef,
  type UUID,
} from './comun'

export type { Tendencia }

export const ETIQUETA_TENDENCIA: Record<Tendencia, string> = {
  sube: 'sube',
  baja: 'baja',
  estable: 'estable',
  sin_datos: 'sin datos',
}

export type OrigenPrecio = 'invoice' | 'manual' | 'import'

export interface Producto {
  id: UUID
  created_at: InstanteISO
  updated_at: InstanteISO
  name: string
  brand: string | null
  canonical_name: string
  size_value?: Cantidad | null
  size_unit?: string | null
  size_text?: string | null
  unit?: string | null
  barcode?: string | null
  default_category?: CategoriaRef | null
  is_archived: boolean
  aliases_count: number
  observations_count: number
  payees_count: number
  first_seen_on?: FechaISO | null
  last_seen_on?: FechaISO | null
  last_unit_price?: Precio | null
  min_unit_price?: Precio | null
  max_unit_price?: Precio | null
  average_unit_price?: Precio | null
  change_pct?: number | null
  change_pct_12m?: number | null
  trend: Tendencia
  has_increase: boolean
  note?: string | null
}

export interface ProductoCrear {
  name: string
  brand?: string | null
  size_value?: Cantidad | null
  size_unit?: string | null
  unit?: string | null
  barcode?: string | null
  default_category_id?: UUID | null
  note?: string | null
}

export interface ProductoActualizar extends Partial<ProductoCrear> {
  is_archived?: boolean
}

/** Una observación de precio del histórico. */
export interface Precio_ {
  id: UUID
  product_id: UUID
  product?: ProductoRef | null
  payee?: ComercioRef | null
  observed_at: FechaISO
  unit_price: Precio
  unit: string | null
  quantity?: Cantidad | null
  total?: Importe | null
  currency: string
  source: OrigenPrecio
  invoice_id?: UUID | null
  invoice_line_id?: UUID | null
  change_pct?: number | null
  change_basis?: 'same_payee' | 'global' | null
  is_increase: boolean
  note?: string | null
  created_at: InstanteISO
}

export interface EstadisticasPrecio {
  product_id: UUID
  observations: number
  period_from?: FechaISO | null
  period_to?: FechaISO | null
  min_unit_price?: Precio | null
  max_unit_price?: Precio | null
  average_unit_price?: Precio | null
  median_unit_price?: Precio | null
  last_unit_price?: Precio | null
  last_observed_at?: FechaISO | null
  change_pct?: number | null
  change_pct_12m?: number | null
  trend: Tendencia
  cheapest_payee?: ComercioRef | null
}

export interface PrecioPorComercio {
  payee: ComercioRef | null
  last_unit_price: Precio
  last_observed_at: FechaISO
  observations: number
  average_unit_price: Precio
  diff_vs_cheapest: Importe
  diff_vs_cheapest_pct: number
  /** La observación tiene más de 90 días. */
  is_stale: boolean
}

/** Comparativa entre comercios del mismo producto (F-38). */
export interface ComparativaProducto {
  product: ProductoRef
  unit?: string | null
  cheapest?: PrecioPorComercio | null
  most_expensive?: PrecioPorComercio | null
  spread_pct?: number | null
  by_payee: PrecioPorComercio[]
}

export interface FiltroProductos extends ParamsListado {
  category_id?: UUID
  payee_id?: UUID
  is_archived?: boolean
  has_increase?: boolean
}

export interface FiltroPrecios extends ParamsListado {
  payee_id?: UUID
  date_from?: FechaISO
  date_to?: FechaISO
}

export const apiProductos = {
  listar: (filtro: FiltroProductos = {}) =>
    api.get<Pagina<Producto>>(conQuery('/products', filtro as Params)),
  obtener: (id: UUID) => api.get<Producto>(`/products/${id}`),
  crear: (cuerpo: ProductoCrear) => api.post<Producto>('/products', cuerpo),
  actualizar: (id: UUID, cuerpo: ProductoActualizar) =>
    api.patch<Producto>(`/products/${id}`, cuerpo),
  borrar: (id: UUID, opciones: { reassign_to?: UUID; force?: boolean } = {}) =>
    api.delete<void>(conQuery(`/products/${id}`, opciones as Params)),

  precios: (id: UUID, filtro: FiltroPrecios = {}) =>
    api.get<Pagina<Precio_>>(conQuery(`/products/${id}/prices`, filtro as Params)),
  estadisticas: (id: UUID, filtro: { date_from?: FechaISO; date_to?: FechaISO } = {}) =>
    api.get<EstadisticasPrecio>(conQuery(`/products/${id}/price-stats`, filtro as Params)),
  comparativa: (id: UUID, meses = 12) =>
    api.get<ComparativaProducto>(conQuery(`/products/${id}/comparison`, { months: meses })),

  sugerencias: (descripcion: string, limite = 5) =>
    api.get<Array<{ product: ProductoRef; score: number; matched_alias?: string | null }>>(
      conQuery('/products/suggestions', { description: descripcion, limit: limite }),
    ),
}
