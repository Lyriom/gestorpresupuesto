/**
 * Resolución del color de una temática.
 *
 * La paleta categórica son 12 ranuras de orden fijo declaradas en el sistema de
 * diseño; aquí solo se traduce lo que guarda el backend (`color`) al token CSS
 * correspondiente. El orden de la lista es parte de la validación de daltonismo:
 * reordenarla la rompe.
 *
 * Este módulo no importa nada: lo usan tanto la BudgetBar como los gráficos, y
 * la BudgetBar no debe arrastrar Chart.js al primer pintado del dashboard.
 */

export const RANURAS_CATEGORICAS = 12

/** `var(--c-cat-1)` … `var(--c-cat-12)`, en el orden validado del sistema de diseño. */
export const PALETA_CATEGORICA: readonly string[] = Array.from(
  { length: RANURAS_CATEGORICAS },
  (_, i) => `var(--c-cat-${i + 1})`,
)

/** Gris del agregado «Otros». Nunca es un hue más. */
export const COLOR_OTROS = 'var(--c-cat-other)'

/** Ranura 1-12 → token. Con más de 12 temáticas se recicla desde la 1. */
export function tokenDeRanura(ranura: number): string {
  const indice = ((Math.trunc(ranura) - 1) % RANURAS_CATEGORICAS + RANURAS_CATEGORICAS) %
    RANURAS_CATEGORICAS
  return PALETA_CATEGORICA[indice]
}

/**
 * Ranura estable derivada del identificador de la temática. Se usa solo cuando
 * el backend no ha guardado color todavía: el color debe seguir a la entidad, y
 * ordenar o filtrar la lista no puede repintar nada.
 */
function ranuraDeIdentificador(id: string): number {
  let suma = 0
  for (let i = 0; i < id.length; i += 1) suma = (suma * 31 + id.charCodeAt(i)) % 100_000
  return (suma % RANURAS_CATEGORICAS) + 1
}

const FUNCIONES_COLOR = /^(#|rgb|hsl|oklch|oklab|lab|lch|color\(|color-mix\(|var\()/i

/**
 * Traduce el `color` de una temática a un color CSS utilizable.
 * Acepta ranura (`"3"`), token (`"cat-3"`, `"--c-cat-3"`), color literal
 * (`"#568EF9"`, `"rgb(...)"`) y nada en absoluto.
 */
export function colorDeCategoria(color: string | null | undefined, categoriaId = ''): string {
  const valor = (color ?? '').trim()
  if (!valor) return tokenDeRanura(ranuraDeIdentificador(categoriaId))
  if (FUNCIONES_COLOR.test(valor)) return valor
  if (/^\d+$/.test(valor)) return tokenDeRanura(Number(valor))
  const ranura = valor.match(/^(?:--c-)?cat-?(\d+)$/i)
  if (ranura) return tokenDeRanura(Number(ranura[1]))
  if (valor.startsWith('--')) return `var(${valor})`
  // Un nombre de color CSS ("tomato") o cualquier otra cosa que el navegador
  // sepa interpretar; si no la entiende, el tramo se queda transparente y sigue
  // leyéndose por el nombre, que va siempre junto al color.
  return valor
}

/** Mezcla sobre el carril: el hue de la temática al `pct %` de saturación. */
export function sobreCarril(color: string, pct: number): string {
  return `color-mix(in oklab, ${color} ${pct}%, var(--c-track))`
}

/**
 * Realce de hover: el mismo hue movido un `pct %` hacia la tinta principal.
 *
 * Se mezcla contra `--c-text-1` y no contra `white` a propósito. El token se
 * invierte con el tema (casi blanco en oscuro, casi negro en claro), así que en
 * oscuro cumple el «color-mix con blanco al 8 %» del §6.5 y en claro oscurece,
 * que es la dirección correcta: aclarar sobre una tarjeta blanca deslavaba el
 * hue en vez de destacarlo.
 */
export function aclarado(color: string, pct = 8): string {
  return `color-mix(in oklab, var(--c-text-1) ${pct}%, ${color})`
}
