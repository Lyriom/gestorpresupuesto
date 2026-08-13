/**
 * Ajustes del usuario.
 *
 * El tema tiene dos casas: `useTema()` lo aplica en el navegador (y lo lee
 * `index.html` antes de la primera pintura) y el servidor lo guarda para el
 * siguiente dispositivo. Al guardar se sincronizan los dos.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  apiAjustes,
  type Ajustes,
  type AjustesActualizar,
  type Almacenamiento,
} from '@/api/ajustes'
import { mensajeDeError } from './comun'

export type SeccionAjustes = 'perfil' | 'preferencias' | 'avisos' | 'datos' | 'sesion'

export const SECCIONES_AJUSTES: Array<{ valor: SeccionAjustes; etiqueta: string }> = [
  { valor: 'perfil', etiqueta: 'Perfil y seguridad' },
  { valor: 'preferencias', etiqueta: 'Preferencias' },
  { valor: 'avisos', etiqueta: 'Notificaciones y avisos' },
  { valor: 'datos', etiqueta: 'Datos' },
  { valor: 'sesion', etiqueta: 'Sesión' },
]

export const useAjustes = defineStore('ajustes', () => {
  const ajustes = ref<Ajustes | null>(null)
  const almacenamiento = ref<Almacenamiento | null>(null)
  const cargando = ref(false)
  const guardando = ref(false)
  const error = ref<string | null>(null)

  const cargado = computed(() => ajustes.value !== null)

  async function cargar(forzar = false): Promise<void> {
    if (cargado.value && !forzar) return
    cargando.value = true
    error.value = null
    try {
      ajustes.value = await apiAjustes.obtener()
    } catch (e) {
      ajustes.value = null
      error.value = mensajeDeError(e, 'No se han podido cargar los ajustes.')
    } finally {
      cargando.value = false
    }
  }

  async function guardar(cambios: AjustesActualizar): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      ajustes.value = await apiAjustes.actualizar(cambios)
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se han podido guardar los cambios.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function cargarAlmacenamiento(): Promise<void> {
    try {
      almacenamiento.value = await apiAjustes.almacenamiento()
    } catch {
      almacenamiento.value = null
    }
  }

  return {
    ajustes,
    almacenamiento,
    cargando,
    guardando,
    error,
    cargado,
    cargar,
    guardar,
    cargarAlmacenamiento,
  }
})
