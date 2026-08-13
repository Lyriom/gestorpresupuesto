import { computed } from 'vue'
import { useMediaQuery } from '@vueuse/core'

/**
 * Breakpoints de §9.1 del sistema de diseño. Coinciden con los de Tailwind para
 * que una clase `lg:` y una rama de JavaScript no puedan discrepar nunca.
 */
export const BREAKPOINTS = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
  '2xl': 1536,
} as const

export type NombreBreakpoint = keyof typeof BREAKPOINTS

export function useMedia() {
  const sm = useMediaQuery(`(min-width: ${BREAKPOINTS.sm}px)`)
  const md = useMediaQuery(`(min-width: ${BREAKPOINTS.md}px)`)
  const lg = useMediaQuery(`(min-width: ${BREAKPOINTS.lg}px)`)
  const xl = useMediaQuery(`(min-width: ${BREAKPOINTS.xl}px)`)
  const xxl = useMediaQuery(`(min-width: ${BREAKPOINTS['2xl']}px)`)

  const punteroFino = useMediaQuery('(hover: hover) and (pointer: fine)')
  const movimientoReducido = useMediaQuery('(prefers-reduced-motion: reduce)')

  /** Nombre del tramo activo, útil para decidir densidades y variantes. */
  const tramo = computed<'base' | NombreBreakpoint>(() => {
    if (xxl.value) return '2xl'
    if (xl.value) return 'xl'
    if (lg.value) return 'lg'
    if (md.value) return 'md'
    if (sm.value) return 'sm'
    return 'base'
  })

  return {
    sm,
    md,
    lg,
    xl,
    xxl,
    tramo,
    punteroFino,
    movimientoReducido,
    /** < 768 px: navegación por barra inferior, tablas como tarjetas. */
    esMovil: computed(() => !md.value),
    /** 768–1023 px: la lateral se esconde tras el botón de menú. */
    esTableta: computed(() => md.value && !lg.value),
    esEscritorio: lg,
  }
}
