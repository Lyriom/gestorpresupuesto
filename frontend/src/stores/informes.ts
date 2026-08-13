/**
 * Informes.
 *
 * Cada pestaña carga su propio informe y guarda su propio error, porque §2.12
 * pide que un informe roto no tumbe ni el selector de periodo ni las demás
 * pestañas.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  apiInformes,
  type CashFlow,
  type GastoPorTematica,
  type IngresoGasto,
  type ParamsInforme,
  type SubidasPrecio,
} from '@/api/informes'
import { desplazarPeriodo, periodoDe } from '@/lib/formato'
import { mensajeDeError } from './comun'

export type PestanyaInforme = 'ingresos' | 'tematicas' | 'precios' | 'ahorro'

export const PESTANYAS_INFORME: Array<{ valor: PestanyaInforme; etiqueta: string }> = [
  { valor: 'ingresos', etiqueta: 'Ingresos y gastos' },
  { valor: 'tematicas', etiqueta: 'Gasto por temática' },
  { valor: 'precios', etiqueta: 'Comparativa de precios' },
  { valor: 'ahorro', etiqueta: 'Ahorro' },
]

/** Rangos del selector de periodo, en meses hacia atrás. */
export const RANGOS = [
  { valor: '3', etiqueta: 'Últimos 3 meses', meses: 3 },
  { valor: '6', etiqueta: 'Últimos 6 meses', meses: 6 },
  { valor: '12', etiqueta: 'Últimos 12 meses', meses: 12 },
] as const

export const useInformes = defineStore('informes', () => {
  const pestanya = ref<PestanyaInforme>('ingresos')
  const meses = ref(6)

  const ingresosYGastos = ref<IngresoGasto | null>(null)
  const porTematica = ref<GastoPorTematica | null>(null)
  const cashFlow = ref<CashFlow | null>(null)
  const subidas = ref<SubidasPrecio | null>(null)

  const cargando = ref(false)
  const errores = ref<Record<PestanyaInforme, string | null>>({
    ingresos: null,
    tematicas: null,
    precios: null,
    ahorro: null,
  })

  const rango = computed<ParamsInforme>(() => {
    const hasta = periodoDe()
    return { period_from: desplazarPeriodo(hasta, -(meses.value - 1)), period_to: hasta }
  })

  const etiquetaRango = computed(
    () => RANGOS.find((r) => r.meses === meses.value)?.etiqueta ?? `Últimos ${meses.value} meses`,
  )

  /** Cierto cuando el rango elegido no tiene ni un movimiento. */
  const sinDatos = computed(() => {
    if (pestanya.value === 'tematicas') return porTematica.value?.rows.length === 0
    if (pestanya.value === 'precios') return subidas.value?.rows.length === 0
    if (pestanya.value === 'ahorro') return cashFlow.value?.points.length === 0
    return ingresosYGastos.value?.rows.length === 0
  })

  async function cargar(): Promise<void> {
    cargando.value = true
    errores.value = { ...errores.value, [pestanya.value]: null }
    const params = rango.value
    try {
      if (pestanya.value === 'ingresos') {
        ingresosYGastos.value = await apiInformes.ingresosYGastos(params)
      } else if (pestanya.value === 'tematicas') {
        porTematica.value = await apiInformes.gastoPorTematica({ ...params, depth: 1 })
      } else if (pestanya.value === 'precios') {
        subidas.value = await apiInformes.subidasDePrecio(params)
      } else {
        cashFlow.value = await apiInformes.cashFlow({ ...params, granularity: 'month' })
      }
    } catch (e) {
      errores.value = {
        ...errores.value,
        [pestanya.value]: mensajeDeError(e, 'No se ha podido generar este informe.'),
      }
    } finally {
      cargando.value = false
    }
  }

  function cambiarPestanya(nueva: PestanyaInforme): void {
    pestanya.value = nueva
    void cargar()
  }

  function cambiarRango(nuevos: number): void {
    meses.value = nuevos
    void cargar()
  }

  return {
    pestanya,
    meses,
    ingresosYGastos,
    porTematica,
    cashFlow,
    subidas,
    cargando,
    errores,
    rango,
    etiquetaRango,
    sinDatos,
    cargar,
    cambiarPestanya,
    cambiarRango,
  }
})
