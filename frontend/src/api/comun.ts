/**
 * Piezas compartidas de la capa de API.
 *
 * Los nombres de campo van **en inglés y en `snake_case`** porque son los que
 * publica `backend/app/schemas/*`: el cable manda (§4 del contrato). La
 * traducción al castellano ocurre en las vistas, con `dinero()`, `fechaCorta()` y
 * el microcopy de `docs/ux/flujos-y-wireframes.md`.
 *
 * Esta capa es fina a propósito: monta la URL, tipa la respuesta y nada más. Ni
 * caché, ni estado, ni cálculos: eso vive en `@/stores`.
 */

export type UUID = string

/** Importe monetario: cadena decimal con punto, dos decimales (§1.7). */
export type Importe = string
/** Precio unitario o cantidad: hasta cuatro decimales significativos. */
export type Precio = string
export type Cantidad = string

/** Fecha civil `AAAA-MM-DD`. */
export type FechaISO = string
/** Instante ISO 8601 en UTC con sufijo `Z`. */
export type InstanteISO = string
/** Periodo de presupuesto `AAAA-MM`. */
export type Periodo = string

/** Sobre único de todos los listados (§1.4). */
export interface Pagina<T> {
  items: T[]
  page: number
  size: number
  total: number
  pages: number
  next_cursor: string | null
}

/** Resultado de una operación en bloque (`bulk-*`, `read-all`, `recompute`). */
export interface ResultadoLote {
  affected: number
  skipped: number
  errors: Array<Record<string, string>>
}

export interface CategoriaRef {
  id: UUID
  name: string
  color?: string | null
}

export interface ComercioRef {
  id: UUID
  name: string
}

export interface EtiquetaRef {
  id: UUID
  name: string
  color?: string | null
}

export interface ProductoRef {
  id: UUID
  name: string
  brand?: string | null
  size_text?: string | null
}

/* ------------------------------------------------------------------ *
 * Query string
 * ------------------------------------------------------------------ */

export type ValorParam = string | number | boolean | null | undefined
/** Un valor de lista se serializa como parámetro repetido: `type=a&type=b`. */
export type Params = Record<string, ValorParam | readonly ValorParam[]>

/**
 * Monta la ruta con su *query string*.
 *
 * No se usa el parámetro `params` de `api.get()` porque ese solo admite valores
 * escalares y §1.5 exige repetir la clave para los filtros de tipo `IN`
 * (`account_id=…&account_id=…`). Las mismas reglas de descarte que
 * `construirUrl()`: `''`, `null` y `undefined` no viajan.
 */
export function conQuery(ruta: string, params?: Params): string {
  if (!params) return ruta
  const qs = new URLSearchParams()
  for (const [clave, valor] of Object.entries(params)) {
    const valores = Array.isArray(valor) ? valor : [valor]
    for (const v of valores) {
      if (v !== null && v !== undefined && v !== '') qs.append(clave, String(v))
    }
  }
  const cadena = qs.toString()
  return cadena ? `${ruta}?${cadena}` : ruta
}

/** Parámetros comunes de paginación y ordenación de todos los listados. */
export interface ParamsListado {
  page?: number
  size?: number
  sort?: string
  q?: string
  /** Modo alternativo: si se envía, se ignora `page` y no viene `total` (§1.4). */
  cursor?: string
}

/* ------------------------------------------------------------------ *
 * Céntimos ⇄ cadena decimal
 *
 * `CampoImporte` trabaja en céntimos enteros y el contrato en cadena decimal.
 * La conversión vive aquí para que ninguna vista la improvise.
 * ------------------------------------------------------------------ */

/** `1570` → `"15.70"`. */
export function importeDeCentimos(centimos: number | null | undefined): Importe | null {
  if (centimos === null || centimos === undefined || !Number.isFinite(centimos)) return null
  return (centimos / 100).toFixed(2)
}

/** `"15.70"` → `1570`. Redondea al céntimo, que es la precisión del dinero. */
export function centimosDeImporte(valor: Importe | number | null | undefined): number | null {
  if (valor === null || valor === undefined || valor === '') return null
  const n = typeof valor === 'number' ? valor : Number.parseFloat(valor)
  return Number.isFinite(n) ? Math.round(n * 100) : null
}
