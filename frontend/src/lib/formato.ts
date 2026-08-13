/**
 * Formateo de importes, fechas y porcentajes en español de España.
 *
 * Los Intl.*Format se crean una sola vez porque construirlos es caro y en las
 * tablas de transacciones se llaman cientos de veces por render.
 */

const LOCALE = 'es-ES'
const MONEDA_POR_DEFECTO = 'EUR'

const cacheMoneda = new Map<string, Intl.NumberFormat>()

function formateadorMoneda(moneda: string, decimales: boolean): Intl.NumberFormat {
  const clave = `${moneda}:${decimales}`
  let f = cacheMoneda.get(clave)
  if (!f) {
    f = new Intl.NumberFormat(LOCALE, {
      style: 'currency',
      currency: moneda,
      minimumFractionDigits: decimales ? 2 : 0,
      maximumFractionDigits: decimales ? 2 : 0,
    })
    cacheMoneda.set(clave, f)
  }
  return f
}

const fmtCompacto = new Intl.NumberFormat(LOCALE, {
  notation: 'compact',
  maximumFractionDigits: 1,
})

const fmtPorcentaje = new Intl.NumberFormat(LOCALE, {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

const fmtFechaCorta = new Intl.DateTimeFormat(LOCALE, {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})

const fmtFechaLarga = new Intl.DateTimeFormat(LOCALE, {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})

const fmtMesAnyo = new Intl.DateTimeFormat(LOCALE, { month: 'long', year: 'numeric' })

/**
 * Los importes llegan de la API como cadena decimal ("1234.56") para no perder
 * precisión al serializar. Esta función acepta ambos y nunca devuelve NaN.
 */
export function aNumero(valor: string | number | null | undefined): number {
  if (valor === null || valor === undefined || valor === '') return 0
  const n = typeof valor === 'number' ? valor : Number.parseFloat(valor)
  return Number.isFinite(n) ? n : 0
}

/** `1.234,56 €` */
export function euros(
  valor: string | number | null | undefined,
  opciones: { decimales?: boolean; moneda?: string; signoSiempre?: boolean } = {},
): string {
  const { decimales = true, moneda = MONEDA_POR_DEFECTO, signoSiempre = false } = opciones
  const n = aNumero(valor)
  const texto = formateadorMoneda(moneda, decimales).format(n)
  return signoSiempre && n > 0 ? `+${texto}` : texto
}

/** `1,2 mil €` — para ejes de gráficos y cifras grandes en poco espacio. */
export function eurosCompactos(
  valor: string | number | null | undefined,
  moneda = MONEDA_POR_DEFECTO,
): string {
  const simbolo = moneda === 'EUR' ? '€' : moneda
  return `${fmtCompacto.format(aNumero(valor))} ${simbolo}`
}

/** Recibe una proporción (0,153) y devuelve `15,3 %`. */
export function porcentaje(proporcion: number | null | undefined): string {
  if (proporcion === null || proporcion === undefined || !Number.isFinite(proporcion)) {
    return '—'
  }
  return fmtPorcentaje.format(proporcion)
}

/**
 * Variación entre dos valores, para las subidas de precio.
 * Devuelve el texto con signo y el sentido, que la UI usa para el color y el icono.
 */
export function variacion(
  anterior: string | number | null | undefined,
  actual: string | number | null | undefined,
): { texto: string; proporcion: number | null; sentido: 'sube' | 'baja' | 'igual' | 'nuevo' } {
  const a = aNumero(anterior)
  const b = aNumero(actual)
  if (a === 0) {
    return { texto: 'Nuevo', proporcion: null, sentido: 'nuevo' }
  }
  const p = (b - a) / a
  const sentido = Math.abs(p) < 0.0005 ? 'igual' : p > 0 ? 'sube' : 'baja'
  const signo = p > 0 ? '+' : ''
  return { texto: `${signo}${fmtPorcentaje.format(p)}`, proporcion: p, sentido }
}

function aFecha(valor: string | Date): Date {
  return valor instanceof Date ? valor : new Date(valor)
}

/** `13 ago 2026` */
export function fechaCorta(valor: string | Date | null | undefined): string {
  if (!valor) return '—'
  return fmtFechaCorta.format(aFecha(valor))
}

/** `13 de agosto de 2026` */
export function fechaLarga(valor: string | Date | null | undefined): string {
  if (!valor) return '—'
  return fmtFechaLarga.format(aFecha(valor))
}

/** `agosto de 2026`, con la inicial en mayúscula. */
export function mesAnyo(valor: string | Date | null | undefined): string {
  if (!valor) return '—'
  const texto = fmtMesAnyo.format(aFecha(valor))
  return texto.charAt(0).toUpperCase() + texto.slice(1)
}

/** Convierte un periodo `2026-08` en su etiqueta legible. */
export function etiquetaPeriodo(periodo: string): string {
  const [anyo, mes] = periodo.split('-').map(Number)
  if (!anyo || !mes) return periodo
  return mesAnyo(new Date(anyo, mes - 1, 1))
}

/** Periodo `AAAA-MM` de una fecha; el mes actual si no se pasa nada. */
export function periodoDe(fecha: Date = new Date()): string {
  return `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, '0')}`
}

/** Suma meses a un periodo `AAAA-MM`. Acepta desplazamientos negativos. */
export function desplazarPeriodo(periodo: string, meses: number): string {
  const [anyo, mes] = periodo.split('-').map(Number)
  const d = new Date(anyo, mes - 1 + meses, 1)
  return periodoDe(d)
}

/** `hace 3 días`, `en 2 meses`. */
export function tiempoRelativo(valor: string | Date | null | undefined): string {
  if (!valor) return '—'
  const rtf = new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto' })
  const diffMs = aFecha(valor).getTime() - Date.now()
  const dias = Math.round(diffMs / 86_400_000)
  if (Math.abs(dias) < 1) return 'hoy'
  if (Math.abs(dias) < 30) return rtf.format(dias, 'day')
  if (Math.abs(dias) < 365) return rtf.format(Math.round(dias / 30), 'month')
  return rtf.format(Math.round(dias / 365), 'year')
}

/**
 * Convierte lo que el usuario escribe en un campo de importe a número.
 * Acepta `1.234,56`, `1234,56`, `1234.56` y `1 234,56`.
 */
export function parsearImporte(entrada: string): number | null {
  const limpio = entrada.trim().replace(/[\s€]/g, '')
  if (!limpio) return null
  const tieneComa = limpio.includes(',')
  const tienePunto = limpio.includes('.')
  let normalizado = limpio
  if (tieneComa && tienePunto) {
    // El último separador que aparece es el decimal.
    normalizado =
      limpio.lastIndexOf(',') > limpio.lastIndexOf('.')
        ? limpio.replace(/\./g, '').replace(',', '.')
        : limpio.replace(/,/g, '')
  } else if (tieneComa) {
    normalizado = limpio.replace(',', '.')
  }
  const n = Number.parseFloat(normalizado)
  return Number.isFinite(n) ? n : null
}
