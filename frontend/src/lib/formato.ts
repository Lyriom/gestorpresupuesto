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

import { ref } from 'vue'

/** Lo que se usa hasta que `/meta` responde. Coincide con el valor por defecto del backend. */
const LOCALE_INICIAL = 'es-EC'
const MONEDA_INICIAL = 'USD'

/**
 * Son `ref` y no dos variables sueltas **porque la moneda se cambia en marcha**.
 *
 * Con una variable normal, cambiarla en Ajustes no repinta nada: Vue no tiene
 * cómo enterarse. Quedaba la interfaz a medias —el logotipo de la barra con el
 * euro, los importes ya en dólares— hasta recargar la página, y el símbolo del
 * campo de importes no cambiaba nunca, porque su `computed` no dependía de nada
 * y se quedaba con el primer valor calculado. Siendo `ref`, cualquier plantilla
 * que llame a `dinero()` o a `simboloDe()` se suscribe sola.
 */
const locale = ref(LOCALE_INICIAL)
const monedaPorDefecto = ref(MONEDA_INICIAL)

/** De cuánto en cuánto presupuesta el hogar. Manda sobre lo que enseña la interfaz. */
const granularidadPresupuesto = ref<'month' | 'week'>('month')

const cache = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat>()

function memo<T extends Intl.NumberFormat | Intl.DateTimeFormat>(clave: string, crear: () => T): T {
  let f = cache.get(`${locale.value}|${clave}`) as T | undefined
  if (!f) {
    f = crear()
    cache.set(`${locale.value}|${clave}`, f)
  }
  return f
}

/**
 * Fija el idioma y la moneda de toda la interfaz.
 *
 * Se llama al cargar `/meta` y otra vez cuando se conoce el hogar, porque la
 * moneda del hogar manda sobre la de la instalación.
 */
export function configurarFormato(opciones: {
  locale?: string
  moneda?: string
  granularidad?: 'month' | 'week'
}): void {
  const antes = `${locale.value}|${monedaPorDefecto.value}`
  if (opciones.locale) locale.value = opciones.locale
  if (opciones.moneda) monedaPorDefecto.value = opciones.moneda
  if (opciones.granularidad) granularidadPresupuesto.value = opciones.granularidad
  if (`${locale.value}|${monedaPorDefecto.value}` !== antes) cache.clear()
}

export function granularidadActual(): 'month' | 'week' {
  return granularidadPresupuesto.value
}

export function monedaActual(): string {
  return monedaPorDefecto.value
}

export function localeActual(): string {
  return locale.value
}

/**
 * Los separadores de millar y de decimales del idioma en uso: en es-EC, `.` y `,`.
 *
 * Los necesita la máscara del campo de importes, que tiene que escribir el número
 * con los mismos separadores con los que `parsearImporte()` lo va a leer después.
 * Salen de `Intl` en vez de escribirse a mano, que es lo que hacía que el campo
 * agrupara a la española aunque la instalación estuviera en otro idioma.
 */
export function separadores(): { millar: string; decimal: string } {
  const partes = memo('separadores', () => new Intl.NumberFormat(locale.value)).formatToParts(11111.1)
  return {
    millar: partes.find((parte) => parte.type === 'group')?.value ?? '.',
    decimal: partes.find((parte) => parte.type === 'decimal')?.value ?? ',',
  }
}

function formateadorMoneda(moneda: string, decimales: boolean): Intl.NumberFormat {
  return memo(
    `moneda:${moneda}:${decimales}`,
    () =>
      new Intl.NumberFormat(locale.value, {
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
      new Intl.NumberFormat(locale.value, {
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
  const { decimales = true, moneda = monedaPorDefecto.value, signoSiempre = false } = opciones
  const n = aNumero(valor)
  const texto = formateadorMoneda(moneda, decimales).format(n)
  return signoSiempre && n > 0 ? `+${texto}` : texto
}

/** `1,2 mil $` — para ejes de gráficos y cifras grandes en poco espacio. */
export function dineroCompacto(
  valor: string | number | null | undefined,
  moneda = monedaPorDefecto.value,
): string {
  // `notation: 'compact'` con `style: 'currency'` da resultados desiguales entre
  // navegadores, así que se compone: número compacto más el símbolo de la moneda.
  const compacto = memo(
    'compacto',
    () => new Intl.NumberFormat(locale.value, { notation: 'compact', maximumFractionDigits: 1 }),
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
export function simboloDe(moneda = monedaPorDefecto.value): string {
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
  moneda = monedaPorDefecto.value,
): string {
  return memo(
    `hablado:${moneda}`,
    () =>
      new Intl.NumberFormat(locale.value, {
        style: 'currency',
        currency: moneda,
        currencyDisplay: 'name',
      }),
  ).format(aNumero(valor))
}

/** El nombre de la moneda: `dólar estadounidense`, `euro`. */
export function nombreMoneda(moneda = monedaPorDefecto.value): string {
  try {
    return new Intl.DisplayNames([locale.value], { type: 'currency' }).of(moneda) ?? moneda
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
  moneda = monedaPorDefecto.value,
): string {
  if (valor === null || valor === undefined || valor === '') return '—'
  const texto = memo(
    `precio:${moneda}`,
    () =>
      new Intl.NumberFormat(locale.value, {
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
      new Intl.NumberFormat(locale.value, { minimumFractionDigits: 0, maximumFractionDigits: 3 }),
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
    () => new Intl.DateTimeFormat(locale.value, { day: 'numeric', month: 'short', year: 'numeric' }),
  ).format(aFecha(valor))
}

/** `13 de agosto de 2026` */
export function fechaLarga(valor: string | Date | null | undefined): string {
  if (!valor) return '—'
  return memo(
    'fechaLarga',
    () => new Intl.DateTimeFormat(locale.value, { day: 'numeric', month: 'long', year: 'numeric' }),
  ).format(aFecha(valor))
}

/** `agosto de 2026`, con la inicial en mayúscula. */
export function mesAnyo(valor: string | Date | null | undefined): string {
  if (!valor) return '—'
  const texto = memo(
    'mesAnyo',
    () => new Intl.DateTimeFormat(locale.value, { month: 'long', year: 'numeric' }),
  ).format(aFecha(valor))
  return texto.charAt(0).toUpperCase() + texto.slice(1)
}

/* ---------- Periodos: un mes o una semana ISO --------------------------- */

const PATRON_SEMANA = /^(\d{4})-W(\d{2})$/

/** El jueves de la semana de una fecha, que es lo que decide su año ISO. */
function juevesDeLaSemana(fecha: Date): Date {
  const d = new Date(fecha.getFullYear(), fecha.getMonth(), fecha.getDate())
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7) + 3)
  return d
}

/**
 * Año y número de la semana ISO de una fecha.
 *
 * Se resuelve por el jueves porque es el día que la norma usa para decidir de qué
 * año es una semana: el 31 de diciembre de 2025 es miércoles y su jueves cae ya en
 * 2026, así que esa semana es la 1 de 2026 y no la 53 de 2025. Y el 4 de enero está
 * siempre en la semana 1, así que su jueves sirve de origen para contar.
 */
function semanaIsoDe(fecha: Date): [number, number] {
  const jueves = juevesDeLaSemana(fecha)
  const anyo = jueves.getFullYear()
  const primero = juevesDeLaSemana(new Date(anyo, 0, 4))
  return [anyo, 1 + Math.round((jueves.getTime() - primero.getTime()) / 604_800_000)]
}

/** El lunes de una semana ISO, o `null` si ese año no tiene esa semana. */
function lunesDeSemanaIso(anyo: number, semana: number): Date | null {
  const jueves = juevesDeLaSemana(new Date(anyo, 0, 4))
  jueves.setDate(jueves.getDate() + (semana - 1) * 7)
  const lunes = new Date(jueves)
  lunes.setDate(lunes.getDate() - 3)
  // 2025 tiene 52 semanas: pedir la 53 daría un lunes de 2026, que ya es otra cosa.
  const [anyoReal, semanaReal] = semanaIsoDe(lunes)
  return anyoReal === anyo && semanaReal === semana ? lunes : null
}

export type GranularidadPeriodo = 'month' | 'week'

/** De qué clase es un periodo, deducido de su forma. */
export function granularidadDe(periodo: string): GranularidadPeriodo {
  return PATRON_SEMANA.test(periodo) ? 'week' : 'month'
}

/** Primer y último día de un periodo, los dos incluidos. */
export function rangoDePeriodo(periodo: string): [Date, Date] | null {
  const semana = PATRON_SEMANA.exec(periodo)
  if (semana) {
    const lunes = lunesDeSemanaIso(Number(semana[1]), Number(semana[2]))
    if (!lunes) return null
    const domingo = new Date(lunes)
    domingo.setDate(domingo.getDate() + 6)
    return [lunes, domingo]
  }
  const [anyo, mes] = periodo.split('-').map(Number)
  if (!anyo || !mes) return null
  return [new Date(anyo, mes - 1, 1), new Date(anyo, mes, 0)]
}

/**
 * La etiqueta legible de un periodo: `Agosto de 2026` o `10 – 16 de ago de 2026`.
 *
 * El rango de la semana lo escribe `formatRange`, que resuelve él solo los casos
 * que se escriben distinto —una semana a caballo entre dos meses o entre dos años—
 * y en el idioma en uso. Se enseña el rango y no «semana 33» porque lo que hace
 * falta saber es qué días se están presupuestando, no el número que le toca.
 */
export function etiquetaPeriodo(periodo: string): string {
  const rango = rangoDePeriodo(periodo)
  if (!rango) return periodo
  if (granularidadDe(periodo) === 'month') return mesAnyo(rango[0])
  return memo(
    'semana',
    () =>
      new Intl.DateTimeFormat(locale.value, {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      }),
  ).formatRange(rango[0], rango[1])
}

/**
 * El periodo al que pertenece una fecha; el de hoy si no se pasa ninguna.
 *
 * La granularidad sale del hogar, igual que la moneda, porque «el periodo actual»
 * no significa lo mismo en una instalación que presupuesta por meses que en una que
 * lo hace por semanas.
 */
export function periodoDe(
  fecha: Date = new Date(),
  granularidad: GranularidadPeriodo = granularidadPresupuesto.value,
): string {
  if (granularidad === 'week') {
    const [anyo, semana] = semanaIsoDe(fecha)
    return `${anyo}-W${String(semana).padStart(2, '0')}`
  }
  return `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, '0')}`
}

/**
 * Las palabras con las que se nombra un periodo dentro de una frase.
 *
 * «Ingresos del mes» y «Ingresos de la semana» dicen lo mismo cada una en su caso;
 * «Ingresos del periodo» no dice ninguna de las dos y suena a documentación técnica.
 * Y no basta con la palabra suelta porque el género cambia la preposición: *del*
 * mes pero *de la* semana. Se resuelve una vez aquí y no en cada componente.
 */
export function palabrasDe(periodo: string): {
  unidad: string
  este: string
  del: string
  anterior: string
} {
  return granularidadDe(periodo) === 'week'
    ? {
        unidad: 'semana',
        este: 'esta semana',
        del: 'de la semana',
        anterior: 'de la semana anterior',
      }
    : { unidad: 'mes', este: 'este mes', del: 'del mes', anterior: 'del mes anterior' }
}

/**
 * Suma periodos a un periodo. Acepta desplazamientos negativos.
 *
 * Qué se suma lo dice el propio periodo: meses a un mes y semanas a una semana. Así
 * las flechas de la barra lateral no tienen que saber en qué modo está el hogar.
 */
export function desplazarPeriodo(periodo: string, cuantos: number): string {
  if (granularidadDe(periodo) === 'week') {
    const rango = rangoDePeriodo(periodo)
    if (!rango) return periodo
    const lunes = new Date(rango[0])
    lunes.setDate(lunes.getDate() + cuantos * 7)
    return periodoDe(lunes, 'week')
  }
  const [anyo, mes] = periodo.split('-').map(Number)
  return periodoDe(new Date(anyo, mes - 1 + cuantos, 1), 'month')
}

/** `hace 3 días`, `en 2 meses`. */
export function tiempoRelativo(valor: string | Date | null | undefined): string {
  if (!valor) return '—'
  const rtf = new Intl.RelativeTimeFormat(locale.value, { numeric: 'auto' })
  const diffMs = aFecha(valor).getTime() - Date.now()
  const dias = Math.round(diffMs / 86_400_000)
  if (Math.abs(dias) < 1) return 'hoy'
  if (Math.abs(dias) < 30) return rtf.format(dias, 'day')
  if (Math.abs(dias) < 365) return rtf.format(Math.round(dias / 30), 'month')
  return rtf.format(Math.round(dias / 365), 'year')
}

/**
 * Un entero con separador de millar y nada más: `2.800`, `1.234.567`, `2,800`.
 *
 * Con un único separador y **exactamente tres cifras detrás** no hay ambigüedad
 * en un importe, porque un importe tiene dos decimales como mucho: `2.800` son
 * dos mil ochocientos, no dos con ocho. Es al revés que en `numeros.py`, que lee
 * `1,234` a la española porque ahí sí puede ser un precio unitario de cuatro
 * decimales; aquí no, aquí son euros o dólares con sus céntimos.
 *
 * El primer grupo va de una a tres cifras y no empieza por cero, que es lo que
 * separa un millar de verdad de un `0.800` mal escrito, que sí son ocho décimas.
 */
const MILLARES = { ',': /^-?[1-9]\d{0,2}(,\d{3})+$/, '.': /^-?[1-9]\d{0,2}(\.\d{3})+$/ }

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
  } else if (tieneComa || tienePunto) {
    const sep = tieneComa ? ',' : '.'
    normalizado = MILLARES[sep].test(limpio)
      ? limpio.split(sep).join('')
      : limpio.replace(sep, '.')
  }
  const n = Number.parseFloat(normalizado)
  return Number.isFinite(n) ? n : null
}
