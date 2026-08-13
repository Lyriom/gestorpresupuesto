/**
 * Tipos de la barra de presupuesto y del análisis de precios.
 *
 * Reflejan literalmente lo que devuelve el backend
 * (`app/services/presupuesto.py` y `app/services/precios.py`), incluido el
 * detalle de que los importes viajan como cadena decimal para no perder
 * céntimos al serializar. Nada en la interfaz debe operar con ellos
 * directamente: primero pasan por `aNumero()`.
 *
 * OJO con la capa de esquemas: `app/schemas/presupuesto.py` publica los mismos
 * datos con nombres en inglés (`period`, `income`, `allocated_total`,
 * `allocations`, `allocated`, `spent`, `overspent`, `state`, `warnings`) y el
 * consumo como proporción (`spent_pct`, 1.0 = justo consumido) en vez de 0-100.
 * Estos tipos siguen al servicio; si la API se sirve con los nombres del
 * esquema, la traducción va en la capa de cliente (`lib/api.ts` o una store),
 * no dentro de los componentes.
 */

/** Importe monetario serializado por el backend: `"1234.56"`. */
export type Importe = string

/** Porcentaje de 0 a 100 (puede pasar de 100 en un sobrepaso), como cadena decimal. */
export type PorcentajeApi = string

/** Periodo mensual en formato `AAAA-MM`. */
export type Periodo = string

export type EstadoSegmento =
  | 'sin_gasto'
  | 'en_margen'
  | 'ajustado'
  | 'agotado'
  | 'sobrepasado'
  | 'sin_asignar'

/** Una temática ya calculada, lista para dibujar. */
export interface SegmentoBarra {
  categoria_id: string
  nombre: string
  /** Ranura de la paleta, hex, o token CSS. Ver `colores.ts`. */
  color: string | null
  icono: string | null
  categoria_padre_id: string | null
  asignado: Importe
  gastado: Importe
  arrastrado: Importe
  /** `asignado + arrastrado - gastado`; negativo si hay sobrepaso. */
  disponible: Importe
  /** Sobre lo asignado más lo arrastrado. */
  porcentaje_consumido: PorcentajeApi
  /** Anchura del segmento sobre el total de la barra. */
  porcentaje_de_la_barra: PorcentajeApi
  estado: EstadoSegmento
  /** Cuánto se ha pasado de lo asignado. Cero si no se ha pasado. */
  sobrepaso: Importe
}

/** Todo lo que la pantalla principal necesita para dibujar el mes. */
export interface BarraPresupuesto {
  periodo: Periodo
  ingresos: Importe
  total_asignado: Importe
  total_gastado: Importe
  total_arrastrado: Importe
  /** Ingresos menos lo asignado. Negativo si se ha repartido más de lo que entra. */
  sin_asignar: Importe
  /** Ingresos más arrastres menos gastado. */
  disponible: Importe
  porcentaje_asignado: PorcentajeApi
  porcentaje_gastado: PorcentajeApi
  segmentos: SegmentoBarra[]
  /** Ya vienen redactados en español desde el backend. */
  avisos: string[]
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
  /** Consumido sobre lo asignado más lo arrastrado; puede pasar de 100. */
  consumidoPct: number
  estado: EstadoSegmento | null
  /** Una temática en `categoria`, las plegadas en `otros`, ninguna en los sintéticos. */
  segmentos: SegmentoBarra[]
}

/** Cifras del mes ya convertidas a número, para no repetir `aNumero()` en cada plantilla. */
export interface CifrasMes {
  ingresos: number
  asignado: number
  gastado: number
  arrastrado: number
  sinAsignar: number
  disponible: number
  porcentajeAsignado: number
  porcentajeGastado: number
  /** Se ha repartido más de lo que entra. */
  sobreasignado: boolean
  /** Se ha gastado más de lo que entra. */
  enRojo: boolean
  sobrepasadas: SegmentoBarra[]
}

export type ClaveCifra = 'ingresos' | 'asignado' | 'gastado' | 'disponible' | 'sinAsignar'

/* ------------------------------------------------------------------ *
 * Precios (app/services/precios.py)
 * ------------------------------------------------------------------ */

export type Tendencia = 'sube' | 'baja' | 'estable' | 'sin_datos'

/** Un precio unitario observado en una factura. */
export interface PuntoPrecio {
  fecha: string
  precio: Importe
  comercio: string | null
  factura_id: string | null
  cantidad: Importe | null
}

/** Último precio conocido de un producto en un comercio. */
export interface ComparativaComercio {
  comercio: string
  precio: Importe
  fecha: string
  observaciones: number
}

export interface AnalisisPrecio {
  observaciones: number
  precio_actual: Importe | null
  precio_anterior: Importe | null
  fecha_actual: string | null
  /** Proporción, no porcentaje: `0.08` es un +8 %. */
  variacion_ultima: Importe | null
  variacion_total: Importe | null
  precio_minimo: Importe | null
  precio_maximo: Importe | null
  precio_medio: Importe | null
  fecha_minimo: string | null
  fecha_maximo: string | null
  tendencia: Tendencia
  hay_alerta: boolean
  mensaje_alerta: string | null
  por_comercio: ComparativaComercio[]
  comercio_mas_barato: string | null
  ahorro_por_unidad: Importe | null
}
