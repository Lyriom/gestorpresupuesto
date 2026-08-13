/**
 * Alertas del panel y contador de la barra lateral.
 *
 * El texto llega redactado del backend (RN-73) y no se recompone: lo único que
 * añade la interfaz es qué acción ofrecer según el tipo.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { apiAlertas, type Alerta, type TipoAlerta } from '@/api/alertas'
import { mensajeDeError } from './comun'

/** Acción directa que acompaña a un aviso del panel, cuando la tiene. */
export type AccionAlerta = 'reasignar' | 'asignar' | 'ver-movimientos' | 'ver-producto' | null

export function accionDe(tipo: TipoAlerta): AccionAlerta {
  switch (tipo) {
    case 'budget_overspent':
      return 'reasignar'
    case 'budget_near_limit':
      return 'ver-movimientos'
    case 'product_price_increase':
    case 'recurring_price_increase':
      return 'ver-producto'
    case 'unusual_spending':
    case 'duplicate_suspected':
      return 'ver-movimientos'
    default:
      return null
  }
}

export const useAlertas = defineStore('alertas', () => {
  const items = ref<Alerta[]>([])
  const sinLeer = ref(0)
  const cargando = ref(false)
  const error = ref<string | null>(null)

  const abiertas = computed(() => items.value.filter((a) => !a.is_dismissed))

  async function cargar(periodo?: string): Promise<void> {
    cargando.value = true
    error.value = null
    try {
      const pag = await apiAlertas.listar({
        period: periodo,
        is_dismissed: false,
        size: 25,
        sort: '-severity',
      })
      items.value = pag.items
    } catch (e) {
      items.value = []
      error.value = mensajeDeError(e, 'No se han podido cargar los avisos.')
    } finally {
      cargando.value = false
    }
  }

  async function cargarContador(): Promise<void> {
    try {
      sinLeer.value = (await apiAlertas.sinLeer()).unread
    } catch {
      sinLeer.value = 0
    }
  }

  async function descartar(id: string): Promise<void> {
    items.value = items.value.filter((a) => a.id !== id)
    try {
      await apiAlertas.descartar(id)
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido descartar el aviso.')
    }
  }

  async function marcarTodasLeidas(periodo?: string): Promise<void> {
    try {
      await apiAlertas.marcarTodasLeidas(periodo)
      items.value = items.value.map((a) => ({ ...a, is_read: true }))
      sinLeer.value = 0
    } catch (e) {
      error.value = mensajeDeError(e, 'No se han podido marcar los avisos como leídos.')
    }
  }

  return {
    items,
    sinLeer,
    cargando,
    error,
    abiertas,
    cargar,
    cargarContador,
    descartar,
    marcarTodasLeidas,
  }
})
