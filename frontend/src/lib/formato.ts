/**
 * Formateo de importes, fechas y porcentajes.
 *
 * El idioma y la moneda **no están fijos en el código**: los publica el servidor
 * en `/meta` (`DEFAULT_LOCALE` y `DEFAULT_CURRENCY`) y luego manda la moneda del
 * hogar. `configurarFormato()` los cambia y vacía las cachés, así que la misma
 * instalación sirve para euros o para dólares sin recompilar nada.
 *
 * Los `Intl.*Format` se memorizan porque construirlos es caro y en las tablas de
 * movimientos se llaman cientos de veces por render. La clave de la memoria
 * incluye el idioma, para que al cambiarlo no se reutilice el formateador viejo.
 */

/** Lo que se usa hasta que `/meta` responde. Coincide con el valor por defecto del backend. */
const LOCALE_INICIAL = 'es-EC'
const MONEDA_INICIAL = 'USD'

let locale = LOCALE_INICIAL
let monedaPorDefecto = MONEDA_INICIAL

const cache = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat>()

function memo<T extends Intl.NumberFormat | Intl.DateTimeFormat>(clave: string, crear: () => T): T {
  let f = cache.get(`${locale}|${clave}`) as T | undefined
  if (!f) {
    f = crear()
    cache.set(`${locale}|${clave}`, f)
  }
  return f
}

/**
 * Fija el idioma y la moneda de toda la interfaz.
 *
 * Se llama al cargar `/meta` y otra vez cuando se conoce el hogar, porque la
 * moneda del hogar manda sobre la de la instalación.
 */
export function configurarFormato(opciones: { locale?: string; moneda?: string }): void {
  const antes = `${locale}|${monedaPorDefecto}`
  if (opciones.locale) locale = opciones.locale
  if (opciones.moneda) monedaPorDefecto = opciones.moneda
  if (`${locale}|${monedaPorDefecto}` !== antes) cache.clear()
}

export function monedaActual(): string {
  return monedaPorDefecto
}

export function localeActual(): string {
  return locale
}

function formateadorMoneda(moneda: string, decimales: boolean): Intl.NumberFormat {
  return memo(
    `moneda:${moneda}:${decimales}`,
    () =>
      new Intl.NumberFormat(locale, {
        style: 'currency',
        currency: moneda,
        minimumFractionDigits: decimales ? 2 : 0,
        maximumFractionDigits: decimales ? 2 : 0,
      }),
  )
}

function formateadorPorcentaje(decimales: number): Intl.NumberFormat {
  return memo(
    `pct:${decimales}`,
    () =>
      new Intl.NumberFormat(locale, {
        style: 'percent',
        minimumFractionDigits: decimales,
        maximumFractionDigits: decimales,
      }),
  )
}

/**
 * Los importes llegan de la API como cadena decimal ("1234.56") para no perder
 * precisión al serializar. Esta función acepta ambos y nunca devuelve NaN.
 */
export function aNumero(valor: string | number | null | undefined): number {
  if (valor === null || valor === undefined || valor === '') return 0
  const n = typeof valor === 'number' ? valor : Number.parseFloat(valor)
  return Number.isFinite(n) ? n : 0
}

/** `$1.234,56` en dólares, `1.234,56 €` en euros. */
export function dinero(
  valor: string | number | null | undefined,
  opciones: { decimales?: boolean; moneda?: string; signoSiempre?: boolean } = {},
): string {
  const { decimales = true, moneda = monedaPorDefecto, signoSiempre = false } = opciones
  const n = aNumero(valor)
  const texto = formateadorMoneda(moneda, decimales).format(n)
  return signoSiempre && n > 0 ? `+${texto}` : texto
}

/** `1,2 mil $` — para ejes de gráficos y cifras grandes en poco espacio. */
export function dineroCompacto(
  valor: string | number | null | undefined,
  moneda = monedaPorDefecto,
): string {
  // `notation: 'compact'` con `style: 'currency'` da resultados desiguales entre
  // navegadores, así que se compone: número compacto más el símbolo de la moneda.
  const compacto = memo(
    'compacto',
    () => new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }),
  ).format(aNumero(valor))
  return `${compacto} ${simboloDe(moneda)}`
}

/**
 * El símbolo de una moneda según el idioma en uso, sin escribirlo a mano.
 *
 * Se saca de `Intl` en vez de una tabla propia: formatea el cero y se queda con
 * lo que no es número. Así `USD` da `$`, `EUR` da `€` y una moneda que el
 * navegador no conozca da su propio código, que es lo correcto.
 */
export function simboloDe(moneda = monedaPorDefecto): string {
  return formateadorMoneda(moneda, false)
    .formatToParts(0)
    .filter((parte) => parte.type === 'currency')
    .map((parte) => parte.value)
    .join('')
}

/**
 * El importe dicho con palabras: `1.234,56 dólares estadounidenses`.
 *
 * Para los lectores de pantalla, que con el símbolo solo leerían «mil doscientos
 * treinta y cuatro coma cincuenta y seis signo de dólar». `Intl` conjuga el
 * plural él mismo: `1,00 dólar estadounidense` y `2,00 dólares estadounidenses`.
 */
export function dineroHablado(
  valor: string | number | null | undefined,
  moneda = monedaPorDefecto,
): string {
  return memo(
    `hablado:${moneda}`,
    () =>
      new Intl.NumberFormat(locale, {
        style: 'currency',
        currency: moneda,
        currencyDisplay: 'name',
      }),
  ).format(aNumero(valor))
}

/** El nombre de la moneda: `dólar estadounidense`, `euro`. */
export function nombreMoneda(moneda = monedaPorDefecto): string {
  try {
    return new Intl.DisplayNames([locale], { type: 'currency' }).of(moneda) ?? moneda
  } catch {
    return moneda
  }
}

/**
 * Precio unitario: `$2,459/kg` (§8.1).
 *
 * Existe aparte de `dinero()` porque un precio por unidad conserva hasta cuatro
 * decimales significativos (así llega en el contrato: `"2.1900"`), mientras que
 * un importe siempre lleva exactamente dos.
 */
export function precioUnitario(
  valor: string | number | null | undefined,
  unidad?: string | null,
  moneda = monedaPorDefecto,
): string {
  if (valor === null || valor === undefined || valor === '') return '—'
  const texto = memo(
    `precio:${moneda}`,
    () =>
      new Intl.NumberFormat(locale, {
        style: 'currency',
        currency: moneda,
        minimumFractionDigits: 2,
        maximumFractionDigits: 4,
      }),
  ).format(aNumero(valor))
  return unidad ? `${texto}/${unidad}` : texto
}

/**
 * Cantidad con su unidad: `1,24 kg`, `750 ml`, `2 uds.` (§8.4).
 *
 * El contrato manda las cantidades como cadena decimal con punto, así que
 * pintarlas tal cual («1.240») se lee en español como mil doscientos cuarenta.
 */
export function cantidad(
  valor: string | number | null | undefined,
  unidad?: string | null,
): string {
  if (valor === null || valor === undefined || valor === '') return '—'
  const n = aNumero(valor)
  const texto = memo(
    'cantidad',
    () =>
      new Intl.NumberFormat(locale, { minimumFractionDigits: 0, maximumFractionDigits: 3 }),
  ).format(n)
  if (!unidad) return n === 1 ? `${texto} ud.` : `${texto} uds.`
  return `${texto} ${unidad}`
}

/**
 * Recibe una proporción (0,153) y devuelve `15,3 %`.
 *
 * Un decimal por defecto (§8.3). Se admite `decimales = 0` para los indicadores
 * gruesos donde los wireframes piden entero —la confianza de una línea de
 * factura, el umbral de aviso—, para que ni esos se compongan a mano.
 */
export function porcentaje(proporcion: number | null | undefined, decimales = 1): string {
  if (proporcion === null || proporcion === undefined || !Number.isFinite(proporcion)) {
    return '—'
  }
  return formateadorPorcentaje(decimales).format(proporcion)
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
  return { texto: `${signo}${formateadorPorcentaje(1).format(p)}`, proporcion: p, sentido }
}

function aFecha(valor: string | Date): Date {
  return valor instanceof Date ? valor : new Date(valor)
}

/** `13 ago 2026` */
export function fechaCorta(valor: string | Date | null | undefined): string {
  if (!valor) return '—'
  return memo(
    'fechaCorta',
    () => new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric' }),
  ).format(aFecha(valor))
}

/** `13 de agosto de 2026` */
export function fechaLarga(valor: string | Date | null | undefined): string {
  if (!valor) return '—'
  return memo(
    'fechaLarga',
    () => new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'long', year: 'numeric' }),
  ).format(aFecha(valor))
}

/** `agosto de 2026`, con la inicial en mayúscula. */
export function mesAnyo(valor: string | Date | null | undefined): string {
  if (!valor) return '—'
  const texto = memo(
    'mesAnyo',
    () => new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }),
  ).format(aFecha(valor))
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
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  const diffMs = aFecha(valor).getTime() - Date.now()
  const dias = Math.round(diffMs / 86_400_000)
  if (Math.abs(dias) < 1) return 'hoy'
  if (Math.abs(dias) < 30) return rtf.format(dias, 'day')
  if (Math.abs(dias) < 365) return rtf.format(Math.round(dias / 30), 'month')
  return rtf.format(Math.round(dias / 365), 'year')
}

/**
 * Convierte lo que el usuario escribe en un campo de importe a número.
 * Acepta `1.234,56`, `1234,56`, `1234.56`, `1 234,56`, `$1.234,56` y `25 €`.
 */
export function parsearImporte(entrada: string): number | null {
  // Se quita cualquier cosa que no sea cifra, separador o signo: así valen el
  // símbolo delante, el símbolo detrás y el código de tres letras.
  const limpio = entrada.trim().replace(/[^\d.,-]/g, '')
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
