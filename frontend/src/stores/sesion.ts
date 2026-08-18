/**
 * Sesión, perfil y estado del asistente inicial.
 *
 * Es el store del que dependen las guardas del router, así que distingue tres
 * situaciones que no son la misma: «todavía no lo he comprobado»
 * (`comprobada === false`), «no hay sesión» (`usuario === null`) y «hay sesión».
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  apiAuth,
  type LoginCrear,
  type Meta,
  type Onboarding,
  type OnboardingSembrarCrear,
  type RegistroCrear,
  type Sesion,
  type UsuarioActualizar,
  type Yo,
} from '@/api/auth'
import { configurarFormato, periodoDe } from '@/lib/formato'
import { erroresPorCampo, mensajeDeError } from './comun'

export const useSesion = defineStore('sesion', () => {
  const usuario = ref<Yo | null>(null)
  const meta = ref<Meta | null>(null)
  const onboarding = ref<Onboarding | null>(null)
  const sesiones = ref<Sesion[]>([])

  /** Ya se ha preguntado al servidor por la sesión al menos una vez. */
  const comprobada = ref(false)
  const cargando = ref(false)
  const enviando = ref(false)
  const error = ref<string | null>(null)
  /**
   * Errores por campo del último envío, con la clave del cuerpo de la petición
   * (`email`, `password`, `name`). §2.1 pide que el correo ya registrado se
   * ancle al campo además de salir en la banda general.
   */
  const erroresCampo = ref<Record<string, string>>({})

  const autenticado = computed(() => usuario.value !== null)
  const necesitaOnboarding = computed(
    () => autenticado.value && usuario.value?.onboarding_completed === false,
  )
  const registroAbierto = computed(
    () => meta.value?.allow_registration === true || meta.value?.first_run === true,
  )
  const periodoActual = computed(() => usuario.value?.current_period ?? periodoDe())
  const nombreApp = computed(() => meta.value?.app_name ?? 'Gestor de presupuesto')
  const maxSubidaMb = computed(() => meta.value?.max_upload_mb ?? 10)

  const minutosDeSesion = computed(() => {
    const caduca = usuario.value?.session_expires_at
    if (!caduca) return undefined
    const restante = new Date(caduca).getTime() - Date.now()
    return Math.max(0, Math.round(restante / 60_000))
  })

  /** Datos del usuario tal y como los espera `LayoutApp`. */
  const usuarioDelLayout = computed(() =>
    usuario.value
      ? { nombre: usuario.value.name, correo: usuario.value.email }
      : undefined,
  )

  async function cargarMeta(): Promise<void> {
    if (meta.value) return
    try {
      meta.value = await apiAuth.meta()
    } catch {
      // El login debe poder pintarse aunque `/meta` falle: se asume lo prudente.
      meta.value = {
        app_name: 'Gestor de presupuesto',
        allow_registration: true,
        first_run: false,
        default_currency: 'USD',
        default_locale: 'es-EC',
        max_upload_mb: 10,
        max_pdf_pages: 20,
        ocr_enabled: false,
      }
    }
    // Ya se puede formatear con el idioma y la moneda de la instalación. Hace
    // falta antes de la sesión: la pantalla de entrada también lleva el símbolo.
    configurarFormato({
      locale: meta.value.default_locale,
      moneda: meta.value.default_currency,
    })
  }

  /** Comprueba si hay sesión. No lanza: devuelve si la hay o no. */
  async function comprobarSesion(): Promise<boolean> {
    cargando.value = true
    try {
      usuario.value = await apiAuth.yo()
      aplicarFormatoDelUsuario()
      return true
    } catch {
      usuario.value = null
      return false
    } finally {
      comprobada.value = true
      cargando.value = false
    }
  }

  /**
   * Lo del usuario manda sobre lo de la instalación.
   *
   * La moneda y la granularidad vienen del hogar y el idioma del perfil, así que
   * quien tenga el hogar en dólares y por semanas ve dólares y semanas aunque el
   * servidor arrancase con otra cosa.
   */
  function aplicarFormatoDelUsuario(): void {
    if (!usuario.value) return
    configurarFormato({
      locale: usuario.value.locale || undefined,
      moneda: usuario.value.currency || undefined,
      granularidad: usuario.value.budget_granularity || undefined,
    })
  }

  async function entrar(credenciales: LoginCrear): Promise<boolean> {
    enviando.value = true
    error.value = null
    erroresCampo.value = {}
    try {
      // La cookie CSRF tiene que existir antes del primer POST (§2.2).
      await apiAuth.csrf().catch(() => undefined)
      await apiAuth.entrar(credenciales)
      await comprobarSesion()
      return autenticado.value
    } catch (e) {
      error.value = mensajeDeError(e, 'El correo o la contraseña no son correctos.')
      erroresCampo.value = erroresPorCampo(e)
      return false
    } finally {
      enviando.value = false
    }
  }

  async function registrar(datos: RegistroCrear): Promise<boolean> {
    enviando.value = true
    error.value = null
    erroresCampo.value = {}
    try {
      await apiAuth.csrf().catch(() => undefined)
      await apiAuth.registrar(datos)
      await comprobarSesion()
      return autenticado.value
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido crear la cuenta.')
      erroresCampo.value = erroresPorCampo(e)
      return false
    } finally {
      enviando.value = false
    }
  }

  async function salir(): Promise<void> {
    try {
      await apiAuth.salir()
    } finally {
      olvidar()
    }
  }

  /** Limpia el estado local sin llamar al servidor (401 o cierre de sesión ajeno). */
  function olvidar(): void {
    usuario.value = null
    onboarding.value = null
    sesiones.value = []
    comprobada.value = true
  }

  async function cargarOnboarding(): Promise<void> {
    cargando.value = true
    error.value = null
    try {
      onboarding.value = await apiAuth.onboarding()
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido cargar el asistente inicial.')
    } finally {
      cargando.value = false
    }
  }

  async function sembrar(datos: OnboardingSembrarCrear): Promise<void> {
    onboarding.value = await apiAuth.sembrarOnboarding(datos)
  }

  async function completarOnboarding(): Promise<void> {
    onboarding.value = await apiAuth.completarOnboarding()
    if (usuario.value) usuario.value = { ...usuario.value, onboarding_completed: true }
  }

  async function guardarPerfil(cambios: UsuarioActualizar): Promise<boolean> {
    enviando.value = true
    error.value = null
    try {
      const actualizado = await apiAuth.actualizarPerfil(cambios)
      if (usuario.value) usuario.value = { ...usuario.value, ...actualizado }
      aplicarFormatoDelUsuario()
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se han podido guardar los cambios.')
      return false
    } finally {
      enviando.value = false
    }
  }

  async function cargarSesiones(): Promise<void> {
    cargando.value = true
    try {
      sesiones.value = (await apiAuth.sesiones()).items
    } catch (e) {
      error.value = mensajeDeError(e, 'No se han podido cargar los dispositivos.')
    } finally {
      cargando.value = false
    }
  }

  async function revocarSesion(id: string): Promise<void> {
    await apiAuth.revocarSesion(id)
    sesiones.value = sesiones.value.filter((s) => s.id !== id)
  }

  async function cambiarContrasenya(actual: string, nueva: string): Promise<boolean> {
    enviando.value = true
    error.value = null
    try {
      await apiAuth.cambiarContrasenya({ current_password: actual, new_password: nueva })
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido cambiar la contraseña.')
      return false
    } finally {
      enviando.value = false
    }
  }

  return {
    usuario,
    meta,
    onboarding,
    sesiones,
    comprobada,
    cargando,
    enviando,
    error,
    erroresCampo,
    autenticado,
    necesitaOnboarding,
    registroAbierto,
    periodoActual,
    nombreApp,
    maxSubidaMb,
    minutosDeSesion,
    usuarioDelLayout,
    cargarMeta,
    comprobarSesion,
    entrar,
    registrar,
    salir,
    olvidar,
    cargarOnboarding,
    sembrar,
    completarOnboarding,
    guardarPerfil,
    cargarSesiones,
    revocarSesion,
    cambiarContrasenya,
  }
})
