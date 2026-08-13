/**
 * Catálogo de productos y ficha con histórico de precios.
 *
 * Cada bloque de la ficha carga por separado y falla por separado: si el gráfico
 * de precios no llega, las cifras de cabecera que sí llegaron se quedan (§2.11).
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  apiProductos,
  type ComparativaProducto,
  type EstadisticasPrecio,
  type FiltroProductos,
  type Precio_,
  type Producto,
} from '@/api/productos'
import { mensajeDeError } from './comun'

export const useProductos = defineStore('productos', () => {
  // --- Catálogo ---
  const items = ref<Producto[]>([])
  const total = ref(0)
  const busqueda = ref('')
  const pagina = ref(1)
  const tamanyoPagina = ref(25)
  const soloConSubida = ref(false)
  const cargando = ref(false)
  const error = ref<string | null>(null)

  // --- Ficha ---
  const producto = ref<Producto | null>(null)
  const precios = ref<Precio_[]>([])
  const estadisticas = ref<EstadisticasPrecio | null>(null)
  const comparativa = ref<ComparativaProducto | null>(null)
  const cargandoFicha = ref(false)
  const cargandoHistorico = ref(false)
  const errorFicha = ref<string | null>(null)
  const errorHistorico = ref<string | null>(null)

  /** Sin dos observaciones no hay variación que contar (§8.3). */
  const hayHistorico = computed(() => precios.value.length >= 2)
  const sinCompras = computed(
    () => !cargandoHistorico.value && !errorHistorico.value && precios.value.length === 0,
  )

  async function cargar(): Promise<void> {
    cargando.value = true
    error.value = null
    try {
      const filtro: FiltroProductos = {
        page: pagina.value,
        size: tamanyoPagina.value,
        q: busqueda.value.length >= 2 ? busqueda.value : undefined,
        has_increase: soloConSubida.value || undefined,
        sort: 'name',
      }
      const pag = await apiProductos.listar(filtro)
      items.value = pag.items
      total.value = pag.total
    } catch (e) {
      items.value = []
      total.value = 0
      error.value = mensajeDeError(e, 'No se han podido cargar los productos.')
    } finally {
      cargando.value = false
    }
  }

  async function cargarFicha(id: string): Promise<void> {
    cargandoFicha.value = true
    errorFicha.value = null
    try {
      producto.value = await apiProductos.obtener(id)
    } catch (e) {
      producto.value = null
      errorFicha.value = mensajeDeError(e, 'No se ha podido cargar este producto.')
    } finally {
      cargandoFicha.value = false
    }
    void cargarHistorico(id)
  }

  async function cargarHistorico(id: string): Promise<void> {
    cargandoHistorico.value = true
    errorHistorico.value = null
    try {
      const [pag, stats, comp] = await Promise.all([
        apiProductos.precios(id, { size: 200, sort: 'observed_at' }),
        apiProductos.estadisticas(id),
        apiProductos.comparativa(id),
      ])
      precios.value = pag.items
      estadisticas.value = stats
      comparativa.value = comp
    } catch (e) {
      precios.value = []
      estadisticas.value = null
      comparativa.value = null
      errorHistorico.value = mensajeDeError(
        e,
        'No se ha podido cargar el histórico de este producto.',
      )
    } finally {
      cargandoHistorico.value = false
    }
  }

  function limpiarFicha(): void {
    producto.value = null
    precios.value = []
    estadisticas.value = null
    comparativa.value = null
    errorFicha.value = null
    errorHistorico.value = null
  }

  return {
    items,
    total,
    busqueda,
    pagina,
    tamanyoPagina,
    soloConSubida,
    cargando,
    error,
    producto,
    precios,
    estadisticas,
    comparativa,
    cargandoFicha,
    cargandoHistorico,
    errorFicha,
    errorHistorico,
    hayHistorico,
    sinCompras,
    cargar,
    cargarFicha,
    cargarHistorico,
    limpiarFicha,
  }
})
