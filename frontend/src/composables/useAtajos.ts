import { computed, ref, toValue, type MaybeRefOrGetter } from 'vue'
import { tryOnScopeDispose, useEventListener } from '@vueuse/core'

export interface Atajo {
  /**
   * `'/'`, `'mod+k'`, `'shift+n'` o una secuencia con espacios: `'g t'`.
   * `mod` es ⌘ en macOS y Ctrl en el resto.
   */
  combinacion: string
  descripcion: string
  accion: (evento: KeyboardEvent) => void
  /** Por defecto un atajo no dispara mientras se escribe en un campo. */
  enCampos?: boolean
  /** Cabecera bajo la que se agrupa en la ayuda de atajos. */
  grupo?: string
}

const ESPERA_SECUENCIA = 1200

function normalizarParte(parte: string): string {
  const trozos = parte
    .split('+')
    .map((t) => t.trim().toLowerCase())
    .filter(Boolean)
  const tecla = trozos.pop() ?? ''
  const mod = trozos.some((t) => t === 'mod' || t === 'cmd' || t === 'meta' || t === 'ctrl')
  const alt = trozos.some((t) => t === 'alt' || t === 'option')
  // En un carácter imprimible el shift ya va dentro del propio carácter.
  const shift = trozos.includes('shift') && tecla.length > 1
  return [mod && 'mod', alt && 'alt', shift && 'shift', tecla].filter(Boolean).join('+')
}

function normalizar(combinacion: string): string[] {
  return combinacion.split(' ').filter(Boolean).map(normalizarParte)
}

function tokenDeEvento(evento: KeyboardEvent): string {
  const tecla = evento.key.toLowerCase()
  return [
    (evento.metaKey || evento.ctrlKey) && 'mod',
    evento.altKey && 'alt',
    evento.shiftKey && tecla.length > 1 && 'shift',
    tecla,
  ]
    .filter(Boolean)
    .join('+')
}

function esCampoDeTexto(destino: EventTarget | null): boolean {
  if (!(destino instanceof HTMLElement)) return false
  if (destino.isContentEditable) return true
  const etiqueta = destino.tagName
  if (etiqueta === 'TEXTAREA' || etiqueta === 'SELECT') return true
  if (etiqueta !== 'INPUT') return false
  const tipo = (destino as HTMLInputElement).type
  return tipo !== 'checkbox' && tipo !== 'radio' && tipo !== 'button'
}

/** Registro global para poder pintar la ayuda «?» con los atajos vivos. */
const registrados = ref<Atajo[]>([])

export function atajosRegistrados() {
  return computed(() => registrados.value)
}

/**
 * Escucha atajos mientras el ámbito que la llama siga vivo. Soporta secuencias
 * de dos teclas: el búfer se olvida a los 1,2 s, como en GitHub o Linear.
 */
export function useAtajos(atajos: MaybeRefOrGetter<Atajo[]>): void {
  let buffer: string[] = []
  let olvido: ReturnType<typeof setTimeout> | null = null

  function reiniciar(): void {
    buffer = []
    if (olvido !== null) clearTimeout(olvido)
    olvido = null
  }

  registrados.value = [...registrados.value, ...toValue(atajos)]
  tryOnScopeDispose(() => {
    const propios = new Set(toValue(atajos))
    registrados.value = registrados.value.filter((a) => !propios.has(a))
    reiniciar()
  })

  useEventListener(
    typeof document !== 'undefined' ? document : null,
    'keydown',
    (evento: KeyboardEvent) => {
      if (evento.isComposing) return
      const token = tokenDeEvento(evento)
      const enCampo = esCampoDeTexto(evento.target)
      buffer = [...buffer, token].slice(-2)

      for (const atajo of toValue(atajos)) {
        if (enCampo && !atajo.enCampos) continue
        const secuencia = normalizar(atajo.combinacion)
        const cola = buffer.slice(-secuencia.length)
        if (cola.length !== secuencia.length) continue
        if (!secuencia.every((parte, i) => parte === cola[i])) continue
        evento.preventDefault()
        reiniciar()
        atajo.accion(evento)
        return
      }

      if (olvido !== null) clearTimeout(olvido)
      olvido = setTimeout(reiniciar, ESPERA_SECUENCIA)
    },
  )
}
