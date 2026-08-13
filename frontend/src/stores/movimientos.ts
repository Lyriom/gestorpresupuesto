/**
 * Lista de movimientos con todos los filtros combinables (F-42).
 *
 * Los filtros son estado del store y el router los refleja en la URL: quien
 * pega un enlace ve exactamente la misma lista. La ordenación la decide el
 * cliente y la ejecuta el servidor (`sort`), nunca se reordena en memoria.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  apiMovimientos,
  type EstadoMovimiento,
  type FiltroMovimientos,
  type Movimiento,
  type MovimientoActualizar,
  type MovimientoCrear,
  type SplitCrear,
  type TipoMovimiento,
} from '@/api/movimientos'
import { aNumero } from '@/lib/formato'
import { mensajeDeError } from './comun'

/** Filtros que la interfaz expone y el router serializa. */
export interface FiltrosVista {
  q: string
  desde: string | null
  hasta: string | null
  tematicas: string[]
  cuentas: string[]
  tipos: TipoMovimiento[]
  estados: EstadoMovimiento[]
  minimo: string | null
  maximo: string | null
  conFactura: boolean | null
  soloRecurrentes: boolean
  soloSinCategorizar: boolean
  incluirHijas: boolean
  /** Movimientos generados por una factura concreta. */
  facturaId: string | null
}

export function filtrosVacios(): FiltrosVista {
  return {
    q: '',
    desde: null,
    hasta: null,
    tematicas: [],
    cuentas: [],
    tipos: [],
    estados: [],
    minimo: null,
    maximo: null,
    conFactura: null,
    soloRecurrentes: false,
    soloSinCategorizar: false,
    incluirHijas: true,
    facturaId: null,
  }
}

export const useMovimientos = defineStore('movimientos', () => {
  const filtros = ref<FiltrosVista>(filtrosVacios())
  const pagina = ref(1)
  const tamanyoPagina = ref(25)
  const orden = ref<{ clave: string; sentido: 'asc' | 'desc' } | null>({
    clave: 'date',
    sentido: 'desc',
  })

  const items = ref<Movimiento[]>([])
  const total = ref(0)
  const cargando = ref(false)
  const recargando = ref(false)
  const guardando = ref(false)
  const error = ref<string | null>(null)

  /** Movimiento abierto en el cajón lateral. */
  const seleccionado = ref<Movimiento | null>(null)

  let peticion: AbortController | null = null

  /** Cuántos filtros hay puestos, para el badge de «Más filtros». */
  const filtrosActivos = computed(() => {
    const f = filtros.value
    let n = 0
    if (f.desde || f.hasta) n += 1
    n += f.tematicas.length > 0 ? 1 : 0
    n += f.cuentas.length > 0 ? 1 : 0
    n += f.tipos.length > 0 ? 1 : 0
    n += f.estados.length > 0 ? 1 : 0
    if (f.minimo || f.maximo) n += 1
    if (f.conFactura !== null) n += 1
    if (f.soloRecurrentes) n += 1
    if (f.soloSinCategorizar) n += 1
    if (f.facturaId) n += 1
    return n
  })

  const hayFiltros = computed(() => filtrosActivos.value > 0 || filtros.value.q.length > 0)

  /** Suma firmada de lo que se está viendo, para el pie de totales de la tabla. */
  const totalFiltrado = computed(() =>
    items.value.reduce((suma, m) => suma + aNumero(m.signed_amount), 0),
  )

  function aFiltroApi(): FiltroMovimientos {
    const f = filtros.value
    const sentido = orden.value?.sentido === 'asc' ? '' : '-'
    return {
      page: pagina.value,
      size: tamanyoPagina.value,
      sort: orden.value ? `${sentido}${orden.value.clave}` : undefined,
      q: f.q.length >= 2 ? f.q : undefined,
      date_from: f.desde ?? undefined,
      date_to: f.hasta ?? undefined,
      account_id: f.cuentas.length > 0 ? f.cuentas : undefined,
      category_id: f.tematicas.length > 0 ? f.tematicas : undefined,
      include_children: f.incluirHijas ? undefined : false,
      kind: f.tipos.length > 0 ? f.tipos : undefined,
      status: f.estados.length > 0 ? f.estados : undefined,
      min_amount: f.minimo ?? undefined,
      max_amount: f.maximo ?? undefined,
      has_invoice: f.conFactura ?? undefined,
      only_recurring: f.soloRecurrentes || undefined,
      only_uncategorized: f.soloSinCategorizar || undefined,
      invoice_id: f.facturaId ?? undefined,
      include: ['splits', 'tags', 'payee', 'account', 'category'],
    }
  }

  async function cargar(): Promise<void> {
    peticion?.abort()
    peticion = new AbortController()
    const primeraVez = items.value.length === 0
    if (primeraVez) cargando.value = true
    else recargando.value = true
    error.value = null
    try {
      const pag = await apiMovimientos.listar(aFiltroApi())
      items.value = pag.items
      total.value = pag.total
    } catch (e) {
      const mensaje = mensajeDeError(e, 'No se han podido cargar los movimientos.')
      // Una petición abortada por otra más nueva no es un error que mostrar.
      if (mensaje) {
        error.value = mensaje
        items.value = []
        total.value = 0
      }
    } finally {
      cargando.value = false
      recargando.value = false
    }
  }

  function aplicar(cambios: Partial<FiltrosVista>): void {
    filtros.value = { ...filtros.value, ...cambios }
    pagina.value = 1
  }

  function limpiarFiltros(): void {
    filtros.value = filtrosVacios()
    pagina.value = 1
  }

  async function crear(cuerpo: MovimientoCrear): Promise<Movimiento | null> {
    guardando.value = true
    error.value = null
    try {
      const creado = await apiMovimientos.crear(cuerpo)
      await cargar()
      return creado
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido guardar el movimiento.')
      return null
    } finally {
      guardando.value = false
    }
  }

  async function actualizar(id: string, cuerpo: MovimientoActualizar): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      const actualizado = await apiMovimientos.actualizar(id, cuerpo)
      items.value = items.value.map((m) => (m.id === id ? actualizado : m))
      if (seleccionado.value?.id === id) seleccionado.value = actualizado
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido guardar el movimiento.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function borrar(id: string): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      await apiMovimientos.borrar(id)
      items.value = items.value.filter((m) => m.id !== id)
      total.value = Math.max(0, total.value - 1)
      if (seleccionado.value?.id === id) seleccionado.value = null
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido eliminar el movimiento.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function guardarReparto(id: string, splits: SplitCrear[]): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      const actualizado = await apiMovimientos.sustituirSplits(id, splits)
      items.value = items.value.map((m) => (m.id === id ? actualizado : m))
      if (seleccionado.value?.id === id) seleccionado.value = actualizado
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido guardar el reparto.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function abrirDetalle(id: string): Promise<void> {
    const enLista = items.value.find((m) => m.id === id)
    seleccionado.value = enLista ?? null
    try {
      seleccionado.value = await apiMovimientos.obtener(id)
    } catch (e) {
      if (!enLista) error.value = mensajeDeError(e, 'No se ha podido cargar el movimiento.')
    }
  }

  function cerrarDetalle(): void {
    seleccionado.value = null
  }

  return {
    filtros,
    pagina,
    tamanyoPagina,
    orden,
    items,
    total,
    cargando,
    recargando,
    guardando,
    error,
    seleccionado,
    filtrosActivos,
    hayFiltros,
    totalFiltrado,
    cargar,
    aplicar,
    limpiarFiltros,
    crear,
    actualizar,
    borrar,
    guardarReparto,
    abrirDetalle,
    cerrarDetalle,
  }
})
