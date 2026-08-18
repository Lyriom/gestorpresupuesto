/**
 * Tipos de la barra de presupuesto y del análisis de precios.
 *
 * **Los nombres de campo son los del esquema Pydantic**, en inglés: son los que
 * viajan por el cable. `backend/app/schemas/presupuesto.py` es la fuente de
 * verdad (`PresupuestoRespuesta` y `AsignacionRespuesta`), no los nombres en
 * castellano de `app/services/presupuesto.py`, que son internos del servidor.
 *
 * Dos detalles del contrato que se notan aquí:
 *
 * - Los importes viajan como **cadena decimal** (`"1234.56"`) para no perder
 *   céntimos al serializar. Nada en la interfaz opera con ellos directamente:
 *   primero pasan por `aNumero()`.
 * - `spent_pct` es una **proporción** (`1.0` = presupuesto justo consumido), no
 *   un 0-100. Los componentes lo multiplican por 100 al pintar.
 *
 * Lo que el esquema no publica y la interfaz necesita (el disponible global, el
 * porcentaje asignado, la geometría de los tramos) se deriva en el componente:
 * son cuentas de presentación, no lógica de negocio duplicada.
 */

/** Importe monetario serializado por el backend: `"1234.56"`. */
export type Importe = string

/** Periodo mensual en formato `AAAA-MM`. */
export type Periodo = string

/** `EstadoSegmento` de `app/services/presupuesto.py`, tal cual llega en `state`. */
export type EstadoSegmento =
  | 'sin_gasto'
  | 'en_margen'
  | 'ajustado'
  | 'agotado'
  | 'sobrepasado'
  | 'sin_asignar'

/** `CategoriaRefRespuesta`: lo justo para pintar un chip. */
export interface CategoriaRef {
  id: string
  name: string
  color?: string | null
}

/** `AsignacionRespuesta`: una temática del periodo, ya calculada por el backend. */
export interface AsignacionTematica {
  category_id: string
  category: CategoriaRef
  allocated: Importe
  /** Sobrante (o exceso) que entra del periodo anterior. */
  rollover_in: Importe
  /** `allocated + rollover_in − spent`. */
  available: Importe
  spent: Importe
  /** Proporción sobre lo asignado más lo arrastrado. `1.0` = justo consumido. */
  spent_pct: number
  /** `max(0, spent − allocated − rollover_in)`. Nunca negativo. */
  overspent: Importe
  state: EstadoSegmento
  rollover_enabled: boolean
  /** No reasignable arrastrando en la barra (hipoteca, seguros). */
  is_locked: boolean
  note?: string | null
  children?: AsignacionTematica[]
}

/** `PresupuestoRespuesta`: el payload completo del mes. */
export interface PresupuestoMes {
  period: Periodo
  currency: string
  is_closed: boolean
  closed_at?: string | null
  /** Suma de ingresos reales del periodo. */
  income_actual: Importe
  planned_income?: Importe | null
  /** El 100 % del carril: `planned_income` si existe, si no `income_actual`. */
  income: Importe
  allocated_total: Importe
  spent_total: Importe
  /** `income − allocated_total`. Puede ser negativo. */
  unassigned: Importe
  /** `max(0, allocated_total − income)`. */
  overallocated: Importe
  rollover_in_total: Importe
  day_of_period: number
  days_in_period: number
  allocations: AsignacionTematica[]
  /** Ya vienen redactados en español desde el backend. */
  warnings: string[]
  note?: string | null
}

export const ETIQUETA_ESTADO: Record<EstadoSegmento, string> = {
  sin_gasto: 'Sin gasto',
  en_margen: 'En margen',
  ajustado: 'Ajustado',
  agotado: 'Agotado',
  sobrepasado: 'Sobrepasado',
  sin_asignar: 'Sin presupuesto',
}

/* ------------------------------------------------------------------ *
 * Modelo de pintado
 * ------------------------------------------------------------------ */

/**
 * Los tramos sintéticos no son temáticas: `sin-asignar` es la cola gris,
 * `de-mas` la zona rayada de sobreasignación y `en-rojo` el gasto que se sale
 * de los ingresos.
 */
export type TipoTramo = 'categoria' | 'otros' | 'sin-asignar' | 'de-mas' | 'en-rojo'

/** Un tramo del carril con la geometría ya resuelta. */
export interface TramoBarra {
  clave: string
  tipo: TipoTramo
  nombre: string
  /** Color CSS listo para usar (`var(--c-cat-3)`, `#568EF9`…). */
  color: string
  /** Importe que da la anchura: lo asignado, lo que falta por repartir o el exceso. */
  importe: number
  /** Anchura sobre el carril completo, 0–100. */
  anchoPct: number
  /** Parte sólida dentro del tramo, 0–100. */
  llenadoPct: number
  /** Anchura de la cresta de exceso sobre el tramo, 0–100. */
  crestaPct: number
  gastado: number
  disponible: number
  arrastrado: number
  sobrepaso: number
  /** Consumido sobre lo asignado más lo arrastrado, 0–100; puede pasar de 100. */
  consumidoPct: number
  estado: EstadoSegmento | null
  /** Una temática en `categoria`, las plegadas en `otros`, ninguna en los sintéticos. */
  asignaciones: AsignacionTematica[]
}

/** Cifras del mes ya convertidas a número, para no repetir `aNumero()` en cada plantilla. */
export interface CifrasMes {
  ingresos: number
  asignado: number
  gastado: number
  arrastrado: number
  sinAsignar: number
  /** Derivado: `income + rollover_in_total − spent_total`. */
  disponible: number
  /** 0–100. Derivado de `allocated_total / income`. */
  porcentajeAsignado: number
  /** 0–100. Derivado de `spent_total / max(income, allocated_total)`. */
  porcentajeGastado: number
  /** Se ha repartido más de lo que entra. */
  sobreasignado: boolean
  /** Se ha gastado más de lo que entra. */
  enRojo: boolean
  sobrepasadas: AsignacionTematica[]
}

export type ClaveCifra = 'ingresos' | 'asignado' | 'gastado' | 'disponible' | 'sinAsignar'

/* ------------------------------------------------------------------ *
 * Precios (app/schemas/producto.py)
 * ------------------------------------------------------------------ */

/** `Tendencia` de `app/services/precios.py`. */
export type Tendencia = 'sube' | 'baja' | 'estable' | 'sin_datos'
