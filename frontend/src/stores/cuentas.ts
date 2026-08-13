/**
 * Cuentas y patrimonio.
 *
 * El saldo es derivado en el servidor (RN-08): aquí nunca se suma nada.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  apiCuentas,
  ETIQUETA_TIPO_CUENTA,
  type Cuenta,
  type CuentaActualizar,
  type CuentaCrear,
  type ResumenCuentas,
} from '@/api/cuentas'
import { mensajeDeError } from './comun'

export const useCuentas = defineStore('cuentas', () => {
  const items = ref<Cuenta[]>([])
  const resumen = ref<ResumenCuentas | null>(null)
  const cargando = ref(false)
  const guardando = ref(false)
  const error = ref<string | null>(null)
  const mostrarArchivadas = ref(false)
  const cargado = ref(false)

  const activas = computed(() => items.value.filter((c) => !c.is_archived))

  /** Opciones para los selectores de cuenta de los formularios. */
  const opciones = computed(() =>
    activas.value.map((c) => ({
      valor: c.id,
      etiqueta: c.name,
      grupo: ETIQUETA_TIPO_CUENTA[c.type],
    })),
  )

  function nombreDe(id: string | null | undefined): string {
    if (!id) return '—'
    return items.value.find((c) => c.id === id)?.name ?? 'Cuenta'
  }

  async function cargar(forzar = false): Promise<void> {
    if (cargado.value && !forzar) return
    cargando.value = true
    error.value = null
    try {
      const pag = await apiCuentas.listar({
        size: 200,
        is_archived: mostrarArchivadas.value ? undefined : false,
      })
      items.value = pag.items
      cargado.value = true
    } catch (e) {
      items.value = []
      error.value = mensajeDeError(e, 'No se han podido cargar las cuentas.')
    } finally {
      cargando.value = false
    }
  }

  async function cargarResumen(): Promise<void> {
    try {
      resumen.value = await apiCuentas.resumen()
    } catch {
      resumen.value = null
    }
  }

  async function crear(cuerpo: CuentaCrear): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      await apiCuentas.crear(cuerpo)
      await cargar(true)
      await cargarResumen()
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido crear la cuenta.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function actualizar(id: string, cuerpo: CuentaActualizar): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      await apiCuentas.actualizar(id, cuerpo)
      await cargar(true)
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se han podido guardar los cambios.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function archivar(id: string): Promise<boolean> {
    guardando.value = true
    try {
      await apiCuentas.archivar(id)
      await cargar(true)
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido archivar la cuenta.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function borrar(id: string): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      await apiCuentas.borrar(id)
      await cargar(true)
      await cargarResumen()
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido eliminar la cuenta.')
      return false
    } finally {
      guardando.value = false
    }
  }

  return {
    items,
    resumen,
    cargando,
    guardando,
    error,
    mostrarArchivadas,
    cargado,
    activas,
    opciones,
    nombreDe,
    cargar,
    cargarResumen,
    crear,
    actualizar,
    archivar,
    borrar,
  }
})
