/**
 * Facturas: bandeja, subida con progreso, sondeo del procesado y revisión.
 *
 * La revisión se edita en local (`borrador`) y se envía de una vez con
 * `PUT /invoices/{id}/lines`, que es idempotente. `can_confirm` y
 * `blocking_reasons` los decide el servidor: aquí no se reinventa la validación,
 * solo se añade la comprobación local de «toda línea necesita temática», que es
 * lo único que la interfaz puede resolver antes de llamar.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  apiFacturas,
  CONFIANZA_BAJA,
  type EstadoProcesado,
  type Factura,
  type FacturaActualizar,
  type FacturaConfirmarCrear,
  type FiltroFacturas,
  type LineaFactura,
  type LineaRevisionCrear,
  type LineasFactura,
  type ResultadoConfirmacion,
} from '@/api/facturas'
import { aNumero } from '@/lib/formato'
import { mensajeDeError } from './comun'

/** Ritmo de sondeo por defecto mientras la factura se procesa (§3.13). */
const RITMO_SONDEO_MS = 1500

/** Una línea en edición: la de la API más lo que el usuario está tecleando. */
export interface LineaBorrador extends LineaRevisionCrear {
  /** Clave estable de la fila, también para las líneas nuevas sin `id`. */
  clave: string
  confidence: number
  is_edited: boolean
  warnings: string[]
  suggested_category_id?: string | null
  suggested_product_name?: string | null
  last_unit_price?: string | null
  change_pct?: number | null
}

let contadorNuevas = 0

function aBorrador(linea: LineaFactura): LineaBorrador {
  return {
    clave: linea.id,
    id: linea.id,
    description: linea.description,
    quantity: linea.quantity ?? null,
    unit: linea.unit ?? null,
    unit_price: linea.unit_price ?? null,
    total: linea.total ?? '0.00',
    category_id: linea.category_id ?? null,
    product_id: linea.product_id ?? null,
    is_excluded: linea.is_excluded,
    is_product: linea.is_product,
    confidence: linea.confidence,
    is_edited: linea.is_edited,
    warnings: linea.warnings ?? [],
    suggested_category_id: linea.suggested_category?.id ?? null,
    suggested_product_name: linea.suggested_product?.product.name ?? null,
    last_unit_price: linea.last_unit_price ?? null,
    change_pct: linea.change_pct ?? null,
  }
}

/**
 * Qué dudó el sistema en una línea de confianza baja. El backend manda sus
 * `warnings` ya redactados; esto solo cubre el caso en que no manda ninguno.
 */
export function motivoDeRevision(linea: LineaBorrador): string | null {
  if (linea.warnings.length > 0) return linea.warnings.join(' · ')
  if (linea.confidence >= CONFIANZA_BAJA) return null
  const dudas: string[] = []
  if (!linea.quantity) dudas.push('la cantidad')
  if (/[?¿]/.test(linea.description) || linea.description.length < 4) dudas.push('la descripción')
  if (!linea.total || aNumero(linea.total) === 0) dudas.push('el importe')
  if (!linea.category_id) dudas.push('la temática')
  if (dudas.length === 0) return 'revisa esta línea: confianza baja en la lectura'
  return `revisa esta línea: confianza baja en ${dudas.join(' y ')}`
}

export const useFacturas = defineStore('facturas', () => {
  // --- Bandeja ---
  const items = ref<Factura[]>([])
  const total = ref(0)
  const cargando = ref(false)
  const error = ref<string | null>(null)

  // --- Subida ---
  const subiendo = ref(false)
  const progresoSubida = ref(0)
  const errorSubida = ref<string | null>(null)

  // --- Factura activa ---
  const factura = ref<Factura | null>(null)
  const revision = ref<LineasFactura | null>(null)
  const estado = ref<EstadoProcesado | null>(null)
  const borrador = ref<LineaBorrador[]>([])
  const cargandoFactura = ref(false)
  const guardando = ref(false)
  const errorFactura = ref<string | null>(null)

  let sondeo: ReturnType<typeof setTimeout> | null = null

  const procesando = computed(() => (estado.value ?? factura.value)?.status === 'processing')
  const fallida = computed(() => (estado.value ?? factura.value)?.status === 'failed')
  const confirmada = computed(() => factura.value?.status === 'confirmed')

  const sumaLineas = computed(() =>
    borrador.value
      .filter((l) => !l.is_excluded)
      .reduce((suma, l) => suma + aNumero(l.total), 0),
  )
  const totalFactura = computed(() => aNumero(factura.value?.total))
  const diferencia = computed(() => sumaLineas.value - totalFactura.value)
  const tolerancia = computed(() => aNumero(revision.value?.tolerance ?? '0.02'))
  const cuadra = computed(() => Math.abs(diferencia.value) <= tolerancia.value)

  const lineasSinTematica = computed(() =>
    borrador.value.filter((l) => !l.is_excluded && !l.category_id),
  )
  const lineasDeConfianzaBaja = computed(() =>
    borrador.value.filter((l) => l.confidence < CONFIANZA_BAJA),
  )
  /** Lo único que bloquea guardar es la falta de temática (§2.9 de la spec). */
  const puedeGuardar = computed(
    () => borrador.value.length > 0 && lineasSinTematica.value.length === 0,
  )

  async function cargar(filtro: FiltroFacturas = {}): Promise<void> {
    cargando.value = true
    error.value = null
    try {
      const pag = await apiFacturas.listar({ size: 25, ...filtro })
      items.value = pag.items
      total.value = pag.total
    } catch (e) {
      items.value = []
      total.value = 0
      error.value = mensajeDeError(e, 'No se han podido cargar las facturas.')
    } finally {
      cargando.value = false
    }
  }

  async function subir(fichero: File): Promise<Factura | null> {
    subiendo.value = true
    progresoSubida.value = 0
    errorSubida.value = null
    try {
      const subida = await apiFacturas.subir(fichero, {}, (pct) => {
        progresoSubida.value = pct
      })
      factura.value = subida
      estado.value = null
      return subida
    } catch (e) {
      errorSubida.value = mensajeDeError(e, 'No se ha podido subir el archivo.')
      return null
    } finally {
      subiendo.value = false
    }
  }

  /** Sondea el procesado al ritmo que marca el propio backend. */
  function arrancarSondeo(id: string): void {
    detenerSondeo()
    const tick = async () => {
      try {
        const nuevo = await apiFacturas.estado(id)
        estado.value = nuevo
        if (nuevo.status === 'processing') {
          const espera = (nuevo.retry_after_seconds ?? 0) * 1000 || RITMO_SONDEO_MS
          sondeo = setTimeout(() => void tick(), espera)
          return
        }
        detenerSondeo()
        if (nuevo.status === 'pending_review' || nuevo.status === 'failed') {
          await cargarRevision(id)
        }
      } catch (e) {
        detenerSondeo()
        errorFactura.value = mensajeDeError(e, 'No se ha podido leer el documento.')
      }
    }
    void tick()
  }

  function detenerSondeo(): void {
    if (sondeo) clearTimeout(sondeo)
    sondeo = null
  }

  async function cargarFactura(id: string): Promise<void> {
    cargandoFactura.value = true
    errorFactura.value = null
    try {
      factura.value = await apiFacturas.obtener(id)
      if (factura.value.status === 'processing') arrancarSondeo(id)
    } catch (e) {
      factura.value = null
      errorFactura.value = mensajeDeError(e, 'No se ha podido cargar esta factura.')
    } finally {
      cargandoFactura.value = false
    }
  }

  async function cargarRevision(id: string): Promise<void> {
    cargandoFactura.value = true
    errorFactura.value = null
    try {
      const [cabecera, lineas] = await Promise.all([
        apiFacturas.obtener(id),
        apiFacturas.lineas(id),
      ])
      factura.value = cabecera
      revision.value = lineas
      borrador.value = lineas.lines.map(aBorrador)
      // Una temática sugerida sin confirmar sigue siendo una línea sin temática;
      // se precarga para no obligar a teclear lo que el sistema ya adivinó bien.
      for (const linea of borrador.value) {
        if (!linea.category_id && linea.suggested_category_id) {
          linea.category_id = linea.suggested_category_id
        }
      }
    } catch (e) {
      errorFactura.value = mensajeDeError(e, 'No se han podido cargar las líneas de la factura.')
    } finally {
      cargandoFactura.value = false
    }
  }

  function anyadirLineaEnBorrador(): void {
    contadorNuevas += 1
    borrador.value = [
      ...borrador.value,
      {
        clave: `nueva-${contadorNuevas}`,
        id: null,
        description: '',
        quantity: null,
        unit: null,
        unit_price: null,
        total: '0.00',
        category_id: null,
        product_id: null,
        is_excluded: false,
        is_product: true,
        confidence: 1,
        is_edited: true,
        warnings: [],
      },
    ]
  }

  function quitarLineaDelBorrador(clave: string): void {
    borrador.value = borrador.value.filter((l) => l.clave !== clave)
  }

  function editarLinea(clave: string, cambios: Partial<LineaBorrador>): void {
    borrador.value = borrador.value.map((l) =>
      l.clave === clave ? { ...l, ...cambios, is_edited: true, confidence: 1 } : l,
    )
  }

  async function guardarCabecera(cambios: FacturaActualizar): Promise<boolean> {
    if (!factura.value) return false
    guardando.value = true
    errorFactura.value = null
    try {
      factura.value = await apiFacturas.actualizarCabecera(factura.value.id, cambios)
      return true
    } catch (e) {
      errorFactura.value = mensajeDeError(e, 'No se han podido guardar los cambios.')
      return false
    } finally {
      guardando.value = false
    }
  }

  /**
   * Solo los campos que acepta `LineaRevisionCrear`.
   *
   * El esquema de petición lleva `extra="forbid"` (§8.5), así que enviar de
   * propina la confianza o las sugerencias sería un 422: hay que construir el
   * cuerpo campo a campo y no repartir el borrador entero.
   */
  function aPeticion(linea: LineaBorrador): LineaRevisionCrear {
    return {
      id: linea.id ?? null,
      description: linea.description,
      quantity: linea.quantity ?? null,
      unit: linea.unit ?? null,
      unit_price: linea.unit_price ?? null,
      total: linea.total,
      category_id: linea.category_id ?? null,
      product_id: linea.product_id ?? null,
      is_excluded: linea.is_excluded ?? false,
      is_product: linea.is_product ?? true,
    }
  }

  /** «Guardar como borrador»: manda toda la revisión de una vez. */
  async function guardarBorrador(): Promise<boolean> {
    if (!factura.value) return false
    guardando.value = true
    errorFactura.value = null
    try {
      revision.value = await apiFacturas.sustituirLineas(
        factura.value.id,
        borrador.value.map(aPeticion),
      )
      borrador.value = revision.value.lines.map(aBorrador)
      return true
    } catch (e) {
      errorFactura.value = mensajeDeError(e, 'No se ha podido guardar la revisión.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function confirmar(cuerpo: FacturaConfirmarCrear): Promise<ResultadoConfirmacion | null> {
    if (!factura.value) return null
    guardando.value = true
    errorFactura.value = null
    try {
      const guardado = await guardarBorrador()
      if (!guardado) return null
      const resultado = await apiFacturas.confirmar(factura.value.id, {
        allow_total_mismatch: true,
        ...cuerpo,
      })
      factura.value = resultado.invoice
      return resultado
    } catch (e) {
      errorFactura.value = mensajeDeError(e, 'No se ha podido guardar la factura.')
      return null
    } finally {
      guardando.value = false
    }
  }

  async function borrar(id: string, force = false): Promise<boolean> {
    try {
      await apiFacturas.borrar(id, { force })
      items.value = items.value.filter((f) => f.id !== id)
      return true
    } catch (e) {
      errorFactura.value = mensajeDeError(e, 'No se ha podido eliminar la factura.')
      return false
    }
  }

  function limpiarActiva(): void {
    detenerSondeo()
    factura.value = null
    revision.value = null
    estado.value = null
    borrador.value = []
    errorFactura.value = null
    progresoSubida.value = 0
    errorSubida.value = null
  }

  return {
    items,
    total,
    cargando,
    error,
    subiendo,
    progresoSubida,
    errorSubida,
    factura,
    revision,
    estado,
    borrador,
    cargandoFactura,
    guardando,
    errorFactura,
    procesando,
    fallida,
    confirmada,
    sumaLineas,
    totalFactura,
    diferencia,
    tolerancia,
    cuadra,
    lineasSinTematica,
    lineasDeConfianzaBaja,
    puedeGuardar,
    cargar,
    subir,
    arrancarSondeo,
    detenerSondeo,
    cargarFactura,
    cargarRevision,
    anyadirLineaEnBorrador,
    quitarLineaDelBorrador,
    editarLinea,
    guardarCabecera,
    guardarBorrador,
    confirmar,
    borrar,
    limpiarActiva,
  }
})
