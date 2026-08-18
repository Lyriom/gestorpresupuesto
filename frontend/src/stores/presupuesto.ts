/**
 * Presupuesto del mes activo.
 *
 * El payload de `GET /budgets/{period}` llega **ya calculado** (estado de cada
 * temática, consumo, sobrepaso, arrastre y avisos redactados): aquí se guarda
 * tal cual y no se recalcula nada. El periodo activo es el ámbito de casi toda
 * la aplicación, así que vive aquí y no en cada vista.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  apiPresupuestos,
  type AsignacionCrear,
  type PresupuestoMes,
  type ResumenPeriodo,
} from '@/api/presupuestos'
import { aNumero, desplazarPeriodo, periodoDe } from '@/lib/formato'
import { mensajeDeError } from './comun'

export const usePresupuesto = defineStore('presupuesto', () => {
  const periodo = ref(periodoDe())
  const mes = ref<PresupuestoMes | null>(null)
  const periodos = ref<ResumenPeriodo[]>([])

  const cargando = ref(false)
  const recargando = ref(false)
  const guardando = ref(false)
  const error = ref<string | null>(null)

  const asignaciones = computed(() => mes.value?.allocations ?? [])
  const avisos = computed(() => mes.value?.warnings ?? [])
  const sinIngresos = computed(() => !!mes.value && aNumero(mes.value.income) <= 0)
  const sinRepartir = computed(
    () => !!mes.value && aNumero(mes.value.income) > 0 && aNumero(mes.value.allocated_total) <= 0,
  )
  const sobrepasadas = computed(() =>
    asignaciones.value.filter((a) => a.state === 'sobrepasado'),
  )
  const sinAsignacion = computed(() => asignaciones.value.filter((a) => a.state === 'sin_asignar'))

  function establecerPeriodo(nuevo: string): void {
    if (nuevo === periodo.value) return
    periodo.value = nuevo
    void cargar()
  }

  /** Adelante o atrás un periodo, sea un mes o una semana. */
  function moverPeriodo(cuantos: number): void {
    establecerPeriodo(desplazarPeriodo(periodo.value, cuantos))
  }

  async function cargar(): Promise<void> {
    const esRecarga = mes.value !== null && mes.value.period === periodo.value
    if (esRecarga) recargando.value = true
    else cargando.value = true
    error.value = null
    try {
      mes.value = await apiPresupuestos.obtener(periodo.value)
    } catch (e) {
      mes.value = null
      error.value = mensajeDeError(e, 'No se ha podido cargar el presupuesto del mes.')
    } finally {
      cargando.value = false
      recargando.value = false
    }
  }

  async function cargarPeriodos(): Promise<void> {
    try {
      periodos.value = (await apiPresupuestos.periodos()).items
    } catch {
      periodos.value = []
    }
  }

  /** Guarda el reparto completo del mes. Idempotente por contrato. */
  async function guardarReparto(allocations: AsignacionCrear[]): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      mes.value = await apiPresupuestos.sustituirAsignaciones(periodo.value, allocations)
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido guardar el reparto.')
      return false
    } finally {
      guardando.value = false
    }
  }

  /** Mueve presupuesto de una temática a otra sin tocar el total (RN-29). */
  async function reasignar(desde: string, hasta: string, importe: string): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      mes.value = await apiPresupuestos.reasignar(periodo.value, {
        from_category_id: desde,
        to_category_id: hasta,
        amount: importe,
      })
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido reasignar el presupuesto.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function ponerIngresoPrevisto(importe: string): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      mes.value = await apiPresupuestos.guardarAjustes(periodo.value, { planned_income: importe })
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se han podido guardar los ingresos.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function copiarDelMesAnterior(): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      mes.value = await apiPresupuestos.copiarDe(periodo.value, {
        source_period: desplazarPeriodo(periodo.value, -1),
        strategy: 'absolute',
      })
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido copiar el reparto del mes pasado.')
      return false
    } finally {
      guardando.value = false
    }
  }

  return {
    periodo,
    mes,
    periodos,
    cargando,
    recargando,
    guardando,
    error,
    asignaciones,
    avisos,
    sinIngresos,
    sinRepartir,
    sobrepasadas,
    sinAsignacion,
    establecerPeriodo,
    moverPeriodo,
    cargar,
    cargarPeriodos,
    guardarReparto,
    reasignar,
    ponerIngresoPrevisto,
    copiarDelMesAnterior,
  }
})
