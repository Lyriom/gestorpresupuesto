/**
 * Etiquetas libres y comercios. §3.9 y §3.10 del contrato.
 *
 * Van juntos porque las dos vistas que los usan (el formulario completo de
 * movimiento y sus filtros) los piden a la vez y ninguno tiene pantalla propia.
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
  type UUID,
} from './comun'

export interface Etiqueta {
  id: UUID
  name: string
  color?: string | null
  created_at: InstanteISO
  transactions_count?: number | null
  total_amount?: Importe | null
}

export interface Comercio {
  id: UUID
  created_at: InstanteISO
  updated_at: InstanteISO
  name: string
  normalized_name: string
  default_category?: CategoriaRef | null
  aliases: string[]
  tax_id: string | null
  website: string | null
  note?: string | null
  is_archived: boolean
  transactions_count?: number | null
  total_spent?: Importe | null
  average_ticket?: Importe | null
  first_seen_on?: FechaISO | null
  last_seen_on?: FechaISO | null
  invoices_count?: number | null
}

export const apiEtiquetas = {
  listar: (filtro: ParamsListado & { include?: 'stats' } = {}) =>
    api.get<Pagina<Etiqueta>>(conQuery('/tags', filtro as Params)),
  crear: (cuerpo: { name: string; color?: string | null }) =>
    api.post<Etiqueta>('/tags', cuerpo),
  borrar: (id: UUID) => api.delete<void>(`/tags/${id}`),
}

export const apiComercios = {
  listar: (filtro: ParamsListado & { category_id?: UUID; include?: 'stats' } = {}) =>
    api.get<Pagina<Comercio>>(conQuery('/payees', filtro as Params)),
  obtener: (id: UUID) => api.get<Comercio>(`/payees/${id}`),
  crear: (cuerpo: { name: string; default_category_id?: UUID | null }) =>
    api.post<Comercio>('/payees', cuerpo),
}
