/**
 * Importación de extractos bancarios: CSV, OFX y QIF (§3.17 y §5.13, F-25).
 *
 * Diez operaciones sobre un **lote** (`import batch`) que no toca el dinero hasta
 * el `commit` (RN-67): se sube el fichero, el servidor lo analiza en segundo
 * plano, se revisan las filas una a una y solo entonces se crean los
 * movimientos. Todo es reversible con `rollback` (RN-69).
 *
 * El análisis puede acabar en `needs_mapping`: el fichero se ha leído, pero no
 * se ha reconocido qué columna es cada cosa y hace falta que lo diga el usuario
 * (`PUT /imports/{id}/mapping`, que vuelve a analizar).
 */
import { api } from '@/lib/api'
import {
  conQuery,
  type CategoriaRef,
  type ComercioRef,
  type FechaISO,
  type Importe,
  type InstanteISO,
  type Pagina,
  type Params,
  type ParamsListado,
  type UUID,
} from './comun'

/** Se detecta por el contenido del fichero, nunca por su extensión (RN-66). */
export type FormatoImportacion = 'csv' | 'ofx' | 'qif'

export const ETIQUETA_FORMATO: Record<FormatoImportacion, string> = {
  csv: 'CSV',
  ofx: 'OFX',
  qif: 'QIF',
}

export type EstadoImportacion =
  | 'analyzing'
  | 'needs_mapping'
  | 'ready'
  | 'committed'
  | 'failed'
  | 'discarded'

export const ETIQUETA_ESTADO_IMPORTACION: Record<EstadoImportacion, string> = {
  analyzing: 'Analizando',
  needs_mapping: 'Falta indicar las columnas',
  ready: 'Pendiente de revisar',
  committed: 'Importada',
  failed: 'No se ha podido leer',
  discarded: 'Descartada',
}

/** Estado de una fila tal y como lo clasifica el servicio de análisis. */
export type EstadoFilaImportacion = 'valida' | 'error' | 'duplicada'

/** La palabra acompaña siempre al icono y al color (§2.3). */
export const ETIQUETA_ESTADO_FILA: Record<EstadoFilaImportacion, string> = {
  valida: 'Correcta',
  error: 'Con error',
  duplicada: 'Duplicada',
}

/** Nombre legible del delimitador detectado: «;» no se lee en voz alta. */
export function nombreDelimitador(delimitador: string | null | undefined): string {
  switch (delimitador) {
    case ';':
      return 'punto y coma (;)'
    case ',':
      return 'coma (,)'
    case '\t':
      return 'tabulador'
    case '|':
      return 'barra vertical (|)'
    case null:
    case undefined:
    case '':
      return 'sin determinar'
    default:
      return `«${delimitador}»`
  }
}

/**
 * Mapeo de columnas del CSV. Las columnas van **por nombre**, que es lo que el
 * usuario ve en la cabecera del fichero; el servidor las traduce a índices.
 *
 * Sin `date_column` y sin `amount_column` (o `debit_column`/`credit_column`) el
 * servidor responde `mapeo_incompleto`. Además el análisis exige concepto, así
 * que `description_column` es igual de obligatoria en la práctica.
 */
export interface MapeoImportacion {
  date_column: string
  amount_column?: string | null
  debit_column?: string | null
  credit_column?: string | null
  description_column?: string | null
  payee_column?: string | null
  balance_column?: string | null
  currency_column?: string | null
  category_column?: string | null
  date_format?: string
  decimal_separator?: ',' | '.'
  thousands_separator?: '.' | ',' | ' ' | ''
  invert_sign?: boolean
  skip_rows?: number
  encoding?: string
  delimiter?: string
}

/** Una fila interpretada, revisable y corregible antes del `commit`. */
export interface FilaImportacion {
  id: UUID
  /** Número de línea en el fichero original, para poder señalarla. */
  row_number: number
  /** Celdas tal cual venían: en CSV la clave es el índice de columna. */
  raw: Record<string, string>
  date?: FechaISO | null
  amount?: Importe | null
  description?: string | null
  payee_name?: string | null
  balance?: Importe | null
  status: EstadoFilaImportacion
  suggested_payee?: ComercioRef | null
  suggested_category?: CategoriaRef | null
  matched_rule_id?: UUID | null
  is_duplicate: boolean
  duplicate_of_id?: UUID | null
  /** Excluida a mano: no genera movimiento. */
  is_skipped: boolean
  error?: string | null
  /** Huella de fecha + importe + concepto (RN-68). */
  fingerprint?: string | null
}

export interface FilaImportacionActualizar {
  date?: FechaISO | null
  amount?: Importe | null
  description?: string | null
  payee_id?: UUID | null
  payee_name?: string | null
  category_id?: UUID | null
  note?: string | null
  is_skipped?: boolean
  is_duplicate?: boolean
}

export interface Importacion {
  id: UUID
  created_at: InstanteISO
  updated_at: InstanteISO
  status: EstadoImportacion
  format: FormatoImportacion
  account_id: UUID
  filename: string
  size_bytes: number
  checksum: string
  detected_columns: string[]
  detected_delimiter?: string | null
  detected_encoding?: string | null
  mapping?: MapeoImportacion | null
  rows_total: number
  rows_valid: number
  rows_duplicated: number
  rows_skipped: number
  rows_error: number
  date_from?: FechaISO | null
  date_to?: FechaISO | null
  committed_at?: InstanteISO | null
  rolled_back_at?: InstanteISO | null
  transactions_created: number
  warnings: string[]
  error?: string | null
}

/** Sondeo del análisis, con el `Retry-After` que marca el ritmo. */
export interface EstadoAnalisis {
  id: UUID
  status: EstadoImportacion
  progress: number
  rows_total: number
  rows_valid: number
  rows_error: number
  /** Campos que el servidor no ha sabido reconocer: fecha, concepto, importe. */
  missing_fields: string[]
  error?: string | null
  retry_after_seconds?: number | null
}

export interface ImportacionConfirmar {
  /** RN-68: lo decide el usuario en la pantalla de revisión. */
  skip_duplicates?: boolean
  apply_rules?: boolean
  create_missing_payees?: boolean
  default_category_id?: UUID | null
}

export interface ResultadoImportacion {
  import_id: UUID
  transactions_created: number
  transactions_deleted: number
  duplicates_skipped: number
  rows_failed: number
  rules_applied: number
  payees_created: number
  warnings: string[]
}

export interface FiltroImportaciones extends ParamsListado {
  status?: EstadoImportacion[]
  account_id?: UUID
}

export interface FiltroFilasImportacion extends ParamsListado {
  only_duplicates?: boolean
  only_errors?: boolean
}

export const apiImportaciones = {
  listar: (filtro: FiltroImportaciones = {}) =>
    api.get<Pagina<Importacion>>(conQuery('/imports', filtro as Params)),

  /** Sube el extracto con el campo de formulario `fichero`. Responde 202. */
  subir: (
    fichero: File,
    campos: { account_id: UUID; format?: FormatoImportacion; mapping_id?: UUID },
    alProgresar?: (pct: number) => void,
  ) => {
    const extra: Record<string, string> = {}
    for (const [clave, valor] of Object.entries(campos)) if (valor) extra[clave] = String(valor)
    return api.subir<Importacion>('/imports', fichero, extra, alProgresar)
  },

  obtener: (id: UUID) => api.get<Importacion>(`/imports/${id}`),

  estado: (id: UUID) => api.get<EstadoAnalisis>(`/imports/${id}/status`),

  filas: (id: UUID, filtro: FiltroFilasImportacion = {}) =>
    api.get<Pagina<FilaImportacion>>(conQuery(`/imports/${id}/preview`, filtro as Params)),

  /** Fija el mapeo a mano y **vuelve a analizar** el fichero (RN-67). */
  fijarMapeo: (id: UUID, mapeo: MapeoImportacion) =>
    api.put<Importacion>(`/imports/${id}/mapping`, mapeo),

  corregirFila: (id: UUID, filaId: UUID, cambios: FilaImportacionActualizar) =>
    api.patch<FilaImportacion>(`/imports/${id}/rows/${filaId}`, cambios),

  confirmar: (id: UUID, cuerpo: ImportacionConfirmar = {}) =>
    api.post<ResultadoImportacion>(`/imports/${id}/commit`, cuerpo),

  /** Deshace el lote: borra exactamente los movimientos que creó (RN-69). */
  revertir: (id: UUID) => api.post<ResultadoImportacion>(`/imports/${id}/rollback`),

  borrar: (id: UUID) => api.delete<void>(`/imports/${id}`),
}
