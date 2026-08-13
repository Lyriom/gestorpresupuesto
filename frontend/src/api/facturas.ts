/**
 * Facturas PDF: subida, sondeo del procesado, revisión, corrección y confirmación.
 *
 * §3.12 y §3.13 del contrato. La extracción **no es fiable al 100 %**, así que
 * el contrato está construido para que sea imposible guardar sin revisar: la
 * confianza por línea manda en cómo se pinta la pantalla de revisión.
 */
import { api } from '@/lib/api'
import {
  conQuery,
  type CategoriaRef,
  type Cantidad,
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

export type EstadoFactura =
  | 'processing'
  | 'pending_review'
  | 'failed'
  | 'confirmed'
  | 'discarded'

export const ETIQUETA_ESTADO_FACTURA: Record<EstadoFactura, string> = {
  processing: 'Procesando',
  pending_review: 'Pendiente de revisar',
  failed: 'No se ha podido leer',
  confirmed: 'Guardada',
  discarded: 'Descartada',
}

export type MetodoExtraccion = 'tabla' | 'texto' | 'ocr' | 'ninguno'

export const ETIQUETA_METODO: Record<MetodoExtraccion, string> = {
  tabla: 'tabla',
  texto: 'texto',
  ocr: 'OCR',
  ninguno: 'sin lectura',
}

/** Confianza por debajo de la cual la interfaz destaca la línea (§3.13). */
export const CONFIANZA_BAJA = 0.6
/** A partir de aquí la confianza es alta y la línea no pide revisión. */
export const CONFIANZA_ALTA = 0.85

export type TonoConfianza = 'alta' | 'media' | 'baja'

/** Tramo de una confianza de lectura (§2.9). Vivía repetido en tres vistas. */
export function tonoConfianza(valor: number): TonoConfianza {
  if (valor >= CONFIANZA_ALTA) return 'alta'
  if (valor >= CONFIANZA_BAJA) return 'media'
  return 'baja'
}

/** La palabra acompaña siempre al número: el color no informa solo (§2.3). */
export const ETIQUETA_CONFIANZA: Record<TonoConfianza, string> = {
  alta: 'Alta',
  media: 'Media',
  baja: 'Baja',
}

export interface DescripcionNormalizada {
  canonical: string
  brand_guess?: string | null
  size_value?: Cantidad | null
  size_unit?: string | null
  code?: string | null
}

export interface SugerenciaProducto {
  product: ProductoRef
  score: number
  matched_alias?: string | null
  last_unit_price?: Precio | null
  last_payee?: ComercioRef | null
}

export interface LineaFactura {
  id: UUID
  line_number: number
  description: string
  quantity?: Cantidad | null
  unit?: string | null
  unit_price?: Precio | null
  total?: Importe | null
  /** De 0 a 1. Es el dato que ordena la revisión. */
  confidence: number
  normalized?: DescripcionNormalizada | null
  /** Corregida a mano: un reprocesado no la toca. */
  is_edited: boolean
  /** Descartada: no genera split ni precio. */
  is_excluded: boolean
  /** `false` para conceptos: potencia contratada, impuestos, portes. */
  is_product: boolean
  warnings: string[]
  category_id?: UUID | null
  category?: CategoriaRef | null
  product_id?: UUID | null
  product?: ProductoRef | null
  suggested_product?: SugerenciaProducto | null
  suggested_category?: CategoriaRef | null
  last_unit_price?: Precio | null
  last_seen_on?: FechaISO | null
  /** Variación frente al último precio visto del mismo producto. */
  change_pct?: number | null
}

export interface Factura {
  id: UUID
  created_at: InstanteISO
  updated_at: InstanteISO
  status: EstadoFactura
  issuer?: string | null
  issuer_tax_id?: string | null
  number?: string | null
  date?: FechaISO | null
  taxable_base?: Importe | null
  tax_amount?: Importe | null
  total?: Importe | null
  currency: string
  extraction_method: MetodoExtraccion
  pages: number
  confidence: number
  warnings: string[]
  lines_count: number
  lines_sum: Importe
  /** `lines_sum − total`, si descuadra. */
  total_mismatch?: Importe | null
  low_confidence_lines: number
  filename: string
  size_bytes: number
  checksum: string
  file_url: string
  payee_id?: UUID | null
  payee?: ComercioRef | null
  account_id?: UUID | null
  transaction_id?: UUID | null
  template_id?: UUID | null
  duplicate_of_id?: UUID | null
  default_category_id?: UUID | null
  note?: string | null
  uploaded_at: InstanteISO
  processed_at?: InstanteISO | null
  reviewed_at?: InstanteISO | null
  confirmed_at?: InstanteISO | null
  error?: string | null
  lines: LineaFactura[]
}

/** Sondeo del procesado: una sola fila, cacheable con `ETag`. */
export interface EstadoProcesado {
  id: UUID
  status: EstadoFactura
  progress: number
  extraction_method: MetodoExtraccion
  pages: number
  confidence: number
  lines_count: number
  low_confidence_lines: number
  warnings: string[]
  error?: string | null
  retry_after_seconds?: number | null
}

/** Lo que pinta la pantalla de revisión, con el semáforo de confirmación. */
export interface LineasFactura {
  invoice_id: UUID
  status: EstadoFactura
  total?: Importe | null
  taxable_base?: Importe | null
  lines_sum: Importe
  total_mismatch?: Importe | null
  /** 0,02 €, la misma constante que usa el extractor (RN-42). */
  tolerance: Importe
  can_confirm: boolean
  /** Ej.: «Hay 3 líneas sin temática», «Las líneas no suman el total». */
  blocking_reasons: string[]
  warnings: string[]
  low_confidence_lines: number
  lines: LineaFactura[]
}

export interface FacturaActualizar {
  issuer?: string | null
  issuer_tax_id?: string | null
  number?: string | null
  date?: FechaISO | null
  taxable_base?: Importe | null
  tax_amount?: Importe | null
  total?: Importe | null
  currency?: string
  payee_id?: UUID | null
  payee_name?: string | null
  account_id?: UUID | null
  default_category_id?: UUID | null
  note?: string | null
}

export interface LineaRevisionCrear {
  /** Nulo para una línea añadida a mano. */
  id?: UUID | null
  description: string
  quantity?: Cantidad | null
  unit?: string | null
  unit_price?: Precio | null
  total: Importe
  category_id?: UUID | null
  product_id?: UUID | null
  is_excluded?: boolean
  is_product?: boolean
}

/**
 * `POST /invoices/{id}/lines` usa `LineaFacturaCrear`, **no** el mismo esquema que
 * el guardado completo: no lleva `id` (`extra="forbid"` lo rechazaría) y sí
 * `position`. El total es opcional porque el backend recalcula el hueco (RN-41).
 */
export interface LineaFacturaCrear {
  description: string
  quantity?: Cantidad | null
  unit?: string | null
  unit_price?: Precio | null
  total?: Importe | null
  category_id?: UUID | null
  product_id?: UUID | null
  is_excluded?: boolean
  is_product?: boolean
  position?: number | null
}

export interface LineaFacturaActualizar {
  description?: string
  quantity?: Cantidad | null
  unit?: string | null
  unit_price?: Precio | null
  total?: Importe | null
  category_id?: UUID | null
  product_id?: UUID | null
  is_excluded?: boolean
  is_product?: boolean
}

export interface FacturaConfirmarCrear {
  account_id: UUID
  date?: FechaISO | null
  payee_id?: UUID | null
  /** Para las líneas sin temática propia. */
  default_category_id?: UUID | null
  transaction_id?: UUID | null
  create_splits?: boolean
  register_prices?: boolean
  /** Confirmar aun sin cuadrar el total (RN-42). */
  allow_total_mismatch?: boolean
  ignore_duplicate?: boolean
  tag_ids?: UUID[]
  note?: string | null
}

export interface AlertaPrecio {
  product: ProductoRef
  payee?: ComercioRef | null
  previous_unit_price: Precio
  new_unit_price: Precio
  change_pct: number
  observed_at: FechaISO
  invoice_line_id?: UUID | null
}

export interface ResultadoConfirmacion {
  invoice: Factura
  transaction_id: UUID
  splits_created: number
  prices_registered: number
  products_created: number
  products_linked: number
  total_mismatch?: Importe | null
  price_alerts: AlertaPrecio[]
  warnings: string[]
}

export interface FiltroFacturas extends ParamsListado {
  status?: EstadoFactura[]
  payee_id?: UUID
  date_from?: FechaISO
  date_to?: FechaISO
  min_total?: Importe
  max_total?: Importe
  has_transaction?: boolean
  confidence_below?: number
  include?: Array<'lines' | 'duplicates'>
}

export const apiFacturas = {
  listar: (filtro: FiltroFacturas = {}) =>
    api.get<Pagina<Factura>>(conQuery('/invoices', filtro as Params)),

  /** Sube el PDF con el campo de formulario `fichero`. Responde 202. */
  subir: (
    fichero: File,
    campos: { account_id?: UUID; payee_id?: UUID; template_id?: UUID } = {},
    alProgresar?: (pct: number) => void,
  ) => {
    const extra: Record<string, string> = {}
    for (const [clave, valor] of Object.entries(campos)) if (valor) extra[clave] = valor
    return api.subir<Factura>('/invoices', fichero, extra, alProgresar)
  },

  obtener: (id: UUID, incluir: Array<'lines' | 'duplicates'> = ['lines']) =>
    api.get<Factura>(conQuery(`/invoices/${id}`, { include: incluir })),

  estado: (id: UUID) => api.get<EstadoProcesado>(`/invoices/${id}/status`),

  lineas: (id: UUID, conSugerencias = true) =>
    api.get<LineasFactura>(
      conQuery(`/invoices/${id}/lines`, { include_suggestions: conSugerencias }),
    ),

  actualizarCabecera: (id: UUID, cuerpo: FacturaActualizar) =>
    api.patch<Factura>(`/invoices/${id}`, cuerpo),

  /** Guarda la revisión completa en una sola llamada. Idempotente. */
  sustituirLineas: (id: UUID, lines: LineaRevisionCrear[]) =>
    api.put<LineasFactura>(`/invoices/${id}/lines`, { lines }),

  actualizarLinea: (id: UUID, lineaId: UUID, cuerpo: LineaFacturaActualizar) =>
    api.patch<LineaFactura>(`/invoices/${id}/lines/${lineaId}`, cuerpo),

  anyadirLinea: (id: UUID, cuerpo: LineaFacturaCrear) =>
    api.post<LineaFactura>(`/invoices/${id}/lines`, cuerpo),

  borrarLinea: (id: UUID, lineaId: UUID) =>
    api.delete<void>(`/invoices/${id}/lines/${lineaId}`),

  vincularProducto: (
    id: UUID,
    lineaId: UUID,
    cuerpo: {
      product_id?: UUID
      new_product?: { name: string }
      remember_alias?: boolean
      /** Guarda la temática de la línea como la del producto (F-17). */
      set_default_category?: boolean
    },
  ) => api.post<LineaFactura>(`/invoices/${id}/lines/${lineaId}/link-product`, cuerpo),

  confirmar: (id: UUID, cuerpo: FacturaConfirmarCrear) =>
    api.post<ResultadoConfirmacion>(`/invoices/${id}/confirm`, cuerpo),

  desconfirmar: (id: UUID, conservarMovimiento = false) =>
    api.post<Factura>(
      conQuery(`/invoices/${id}/unconfirm`, { keep_transaction: conservarMovimiento }),
    ),

  reprocesar: (
    id: UUID,
    cuerpo: { template_id?: UUID | null; force_ocr?: boolean; keep_edited?: boolean } = {},
  ) => api.post<Factura>(`/invoices/${id}/reprocess`, { keep_edited: true, ...cuerpo }),

  borrar: (id: UUID, opciones: { force?: boolean; delete_transaction?: boolean } = {}) =>
    api.delete<void>(conQuery(`/invoices/${id}`, opciones as Params)),

  /** URL de descarga o previsualización del PDF original. */
  urlFichero: (id: UUID, disposition: 'inline' | 'attachment' = 'inline') =>
    `/api/v1${conQuery(`/invoices/${id}/file`, { disposition })}`,
}
