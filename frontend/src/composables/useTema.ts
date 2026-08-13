import { computed, ref, watch } from 'vue'

export type Tema = 'dark' | 'light'
/** Lo que el usuario elige en el menú: los dos temas o «según el sistema». */
export type PreferenciaTema = Tema | 'sistema'

/**
 * Contrato con index.html: ese script lee `tema` antes de la primera pintura y
 * solo entiende 'dark' | 'light'. Por eso aquí se guardan DOS claves: `tema`
 * con el tema ya resuelto (para que no haya destello al recargar) y
 * `tema-preferencia` con la elección real, que puede ser «sistema».
 * Sin preferencia guardada el tema es oscuro: es el de la marca, no el del SO.
 */
const CLAVE_RESUELTO = 'tema'
const CLAVE_PREFERENCIA = 'tema-preferencia'

function leer(clave: string): string | null {
  try {
    return localStorage.getItem(clave)
  } catch {
    return null
  }
}

function escribir(clave: string, valor: string): void {
  try {
    localStorage.setItem(clave, valor)
  } catch {
    /* localStorage bloqueado: el tema funciona igual, solo no se recuerda */
  }
}

function preferenciaGuardada(): PreferenciaTema {
  const p = leer(CLAVE_PREFERENCIA)
  if (p === 'dark' || p === 'light' || p === 'sistema') return p
  const heredado = leer(CLAVE_RESUELTO)
  return heredado === 'light' || heredado === 'dark' ? heredado : 'dark'
}

const consulta =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null

const oscuroEnSistema = ref(consulta ? consulta.matches : true)
consulta?.addEventListener('change', (e) => {
  oscuroEnSistema.value = e.matches
})

const preferencia = ref<PreferenciaTema>(preferenciaGuardada())

const tema = computed<Tema>(() => {
  if (preferencia.value === 'sistema') return oscuroEnSistema.value ? 'dark' : 'light'
  return preferencia.value
})

watch(
  tema,
  (valor) => {
    if (typeof document === 'undefined') return
    document.documentElement.dataset.theme = valor
    // El color de la barra del navegador sale del propio token, no de una copia
    // del hex: `content` no acepta `var()`, así que se resuelve al aplicarlo.
    const fondo = getComputedStyle(document.documentElement)
      .getPropertyValue('--c-app-bg')
      .trim()
    if (fondo) {
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', fondo)
    }
    escribir(CLAVE_RESUELTO, valor)
  },
  { immediate: true },
)

export const OPCIONES_TEMA: ReadonlyArray<{ valor: PreferenciaTema; etiqueta: string }> = [
  { valor: 'dark', etiqueta: 'Oscuro' },
  { valor: 'light', etiqueta: 'Claro' },
  { valor: 'sistema', etiqueta: 'Según el sistema' },
]

export function useTema() {
  function establecer(valor: PreferenciaTema): void {
    preferencia.value = valor
    escribir(CLAVE_PREFERENCIA, valor)
  }

  /** Alterna entre claro y oscuro; si estaba en «sistema», fija el contrario. */
  function alternar(): void {
    establecer(tema.value === 'dark' ? 'light' : 'dark')
  }

  return {
    tema,
    preferencia: computed(() => preferencia.value),
    esOscuro: computed(() => tema.value === 'dark'),
    opciones: OPCIONES_TEMA,
    establecer,
    alternar,
  }
}
