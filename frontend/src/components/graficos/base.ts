/**
 * Configuración común de Chart.js: la sección 7 del sistema de diseño escrita en
 * código, para que ningún gráfico tenga que recordarla.
 *
 * Dos decisiones que conviene entender antes de tocar nada:
 *
 * 1. Los colores viven en variables CSS y el lienzo no entiende `var()`, así que
 *    hay que resolverlos con `getComputedStyle` **contra el propio elemento del
 *    gráfico** (no contra `<html>`): así funciona también dentro de una zona con
 *    tema propio, como la página de demostración.
 * 2. Los ejes y los tooltips formatean con `lib/formato`, nunca con
 *    `toLocaleString` a mano: el eje va compacto (`1,2 mil €`) y el tooltip
 *    completo (`1.234,56 €`), que es la regla del sistema.
 */

import {
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  Filler,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
  type ChartOptions,
  type ChartType,
  type Plugin,
  type ScaleOptions,
  type TooltipItem,
} from 'chart.js'
import { computed, onBeforeUnmount, onMounted, ref, type ComputedRef, type Ref } from 'vue'

import { dinero, dineroCompacto } from '@/lib/formato'

export { PALETA_CATEGORICA, COLOR_OTROS, colorDeCategoria, tokenDeRanura } from
  '@/components/presupuesto/colores'

/* ------------------------------------------------------------------ *
 * Registro
 * ------------------------------------------------------------------ */

let registrado = false

/**
 * `vue-chartjs` registra solo el controlador de cada tipo; escalas, elementos y
 * plugins hay que declararlos. Se hace bajo llamada para que importar este
 * módulo desde un componente que no dibuja nada no arrastre el registro.
 */
export function registrarChartJs(): void {
  if (registrado) return
  Chart.register(
    BarController,
    LineController,
    CategoryScale,
    LinearScale,
    BarElement,
    LineElement,
    PointElement,
    ArcElement,
    Filler,
    Tooltip,
    Legend,
  )
  registrado = true
}

/* ------------------------------------------------------------------ *
 * Tokens y paleta
 * ------------------------------------------------------------------ */

export interface PaletaGrafico {
  texto1: string
  texto2: string
  texto3: string
  superficie: string
  superficie2: string
  borde: string
  bordeFuerte: string
  rejilla: string
  eje: string
  ejeTexto: string
  carril: string
  deenfasis: string
  acento: string
  positivo: string
  negativo: string
  aviso: string
  info: string
  categorias: string[]
  otros: string
  secuencial: string[]
  /** Ámbar ↔ azul, del extremo cálido al frío. Verde/rojo no vale como divergente. */
  divergente: string[]
}

/**
 * Lee un token CSS resuelto. El respaldo es siempre un color con nombre del
 * navegador: si el sistema de diseño no está cargado el gráfico se ve gris pero
 * se ve, en vez de quedarse en blanco.
 */
export function leerToken(elemento: Element | null, nombre: string, respaldo: string): string {
  if (typeof window === 'undefined') return respaldo
  const objetivo = elemento ?? document.documentElement
  const valor = getComputedStyle(objetivo).getPropertyValue(nombre).trim()
  return valor || respaldo
}

function resolverPaleta(elemento: Element | null): PaletaGrafico {
  const t = (nombre: string, respaldo: string) => leerToken(elemento, nombre, respaldo)
  return {
    texto1: t('--c-text-1', 'black'),
    texto2: t('--c-text-2', 'dimgray'),
    texto3: t('--c-text-3', 'gray'),
    superficie: t('--c-surface', 'white'),
    superficie2: t('--c-surface-2', 'white'),
    borde: t('--c-border', 'lightgray'),
    bordeFuerte: t('--c-border-strong', 'darkgray'),
    rejilla: t('--c-grid', 'gainsboro'),
    eje: t('--c-axis', 'darkgray'),
    ejeTexto: t('--c-axis-text', 'gray'),
    carril: t('--c-track', 'whitesmoke'),
    deenfasis: t('--c-deemphasis', 'darkgray'),
    acento: t('--c-accent', 'royalblue'),
    positivo: t('--c-positive', 'seagreen'),
    negativo: t('--c-negative', 'crimson'),
    aviso: t('--c-warning', 'darkorange'),
    info: t('--c-info', 'steelblue'),
    categorias: Array.from({ length: 12 }, (_, i) => t(`--c-cat-${i + 1}`, 'gray')),
    otros: t('--c-cat-other', 'gray'),
    secuencial: [300, 400, 500, 600, 700].map((paso) => t(`--c-seq-${paso}`, 'steelblue')),
    divergente: [
      t('--c-div-warm-3', 'goldenrod'),
      t('--c-div-warm-2', 'darkgoldenrod'),
      t('--c-div-warm-1', 'sienna'),
      t('--c-div-neutral', 'gray'),
      t('--c-div-cool-1', 'steelblue'),
      t('--c-div-cool-2', 'royalblue'),
      t('--c-div-cool-3', 'lightsteelblue'),
    ],
  }
}

/** `prefers-reduced-motion`, compartido por todos los gráficos de la página. */
const movimientoReducidoRef = ref(false)
let consultaMovimiento: MediaQueryList | null = null

function iniciarConsultaMovimiento(): void {
  if (consultaMovimiento || typeof window === 'undefined' || !window.matchMedia) return
  consultaMovimiento = window.matchMedia('(prefers-reduced-motion: reduce)')
  movimientoReducidoRef.value = consultaMovimiento.matches
  consultaMovimiento.addEventListener('change', (evento) => {
    movimientoReducidoRef.value = evento.matches
  })
}

/**
 * Paleta reactiva del gráfico. Se recalcula al montar, al cambiar el tema
 * (`data-theme` en `<html>`) y al cambiar la preferencia del sistema.
 */
export function usarPaleta(elemento: Ref<HTMLElement | null>): {
  paleta: ComputedRef<PaletaGrafico>
  movimientoReducido: Ref<boolean>
} {
  const version = ref(0)
  let observador: MutationObserver | null = null
  let consultaTema: MediaQueryList | null = null
  const revisar = () => {
    version.value += 1
  }

  onMounted(() => {
    iniciarConsultaMovimiento()
    revisar()
    if (typeof window === 'undefined') return
    observador = new MutationObserver(revisar)
    observador.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme', 'class', 'style'],
    })
    if (window.matchMedia) {
      consultaTema = window.matchMedia('(prefers-color-scheme: dark)')
      consultaTema.addEventListener('change', revisar)
    }
  })

  onBeforeUnmount(() => {
    observador?.disconnect()
    consultaTema?.removeEventListener('change', revisar)
  })

  const paleta = computed(() => {
    void version.value
    return resolverPaleta(elemento.value)
  })

  return { paleta, movimientoReducido: movimientoReducidoRef }
}

/* ------------------------------------------------------------------ *
 * Utilidades de color
 * ------------------------------------------------------------------ */

/**
 * Aplica opacidad a un color. El lienzo no entiende `color-mix()`, así que hay
 * que llegar a `rgb(... / a)` a mano. Si el color no se reconoce se devuelve tal
 * cual: mejor un relleno opaco que un gráfico sin serie.
 */
export function conAlfa(color: string, alfa: number): string {
  const valor = color.trim()
  const hex = valor.match(/^#([0-9a-f]{3,8})$/i)
  if (hex) {
    const d = hex[1]
    const corto = d.length === 3 || d.length === 4
    const [r, g, b] = [0, 1, 2].map((i) =>
      parseInt(corto ? d[i].repeat(2) : d.slice(i * 2, i * 2 + 2), 16),
    )
    return `rgb(${r} ${g} ${b} / ${alfa})`
  }
  const rgb = valor.match(/^rgba?\(([^)]+)\)$/i)
  if (rgb) {
    const partes = rgb[1].split(/[\s,/]+/).filter(Boolean).slice(0, 3)
    if (partes.length === 3) return `rgb(${partes.join(' ')} / ${alfa})`
  }
  return valor
}

/**
 * Convierte el color que trae un dato (ranura `3`, token `cat-3` o `var(--x)`,
 * o un color literal) en algo que el lienzo sepa pintar: `var()` no vale ahí.
 */
export function colorDeSerie(
  paleta: PaletaGrafico,
  elemento: Element | null,
  color: string | null | undefined,
  indice = 0,
): string {
  const valor = (color ?? '').trim()
  if (!valor) return paleta.categorias[indice % paleta.categorias.length]
  if (/^(?:var\(\s*)?(?:--c-)?cat-other\s*\)?$/i.test(valor)) return paleta.otros
  const ranura = valor.match(/^(?:var\(\s*)?(?:--c-)?cat-?(\d+)\s*\)?$/i)
  if (ranura) return paleta.categorias[(Number(ranura[1]) - 1) % paleta.categorias.length]
  if (/^\d+$/.test(valor)) return paleta.categorias[(Number(valor) - 1) % paleta.categorias.length]
  const variable = valor.match(/^var\(\s*(--[\w-]+)\s*(?:,[^)]*)?\)$/)
  if (variable) return leerToken(elemento, variable[1], paleta.texto3)
  if (valor.startsWith('--')) return leerToken(elemento, valor, paleta.texto3)
  return valor
}

/* ------------------------------------------------------------------ *
 * Opciones comunes
 * ------------------------------------------------------------------ */

export interface OpcionesComunes {
  paleta: PaletaGrafico
  movimientoReducido: boolean
  /** La leyenda solo aparece con dos o más series: con una, el título ya la nombra. */
  series: number
  /** `index` en gráficos temporales, `nearest` en barras. */
  interaccion?: 'index' | 'nearest'
  posicionLeyenda?: 'top' | 'bottom' | 'right'
  /** Importes de menos de un euro (precio unitario) piden más decimales. */
  formatearValor?: (valor: number) => string
}

const FUENTE_EJE = { size: 12, family: 'var(--font-sans, system-ui)' } as const

function tituloTooltip(items: TooltipItem<ChartType>[]): string {
  return items[0]?.label ?? ''
}

/**
 * El valor del punto. `parsed` cambia de forma según el tipo de gráfico
 * (número en tarta, `{x, y}` en cartesianos), así que se comprueba en ejecución.
 */
function valorDelPunto(item: TooltipItem<ChartType>): number {
  const bruto: unknown = item.parsed
  if (typeof bruto === 'number') return bruto
  if (bruto && typeof bruto === 'object' && 'y' in bruto) {
    const y = (bruto as { y?: unknown }).y
    if (typeof y === 'number') return y
  }
  return 0
}

/**
 * Base común: sin marco, sin rejilla vertical, animación de 180 ms y moneda en
 * todo. Las opciones de Chart.js no se pueden construir de forma polimórfica
 * (dependen del tipo de gráfico), así que la parte común se declara una vez y se
 * afirma al tipo concreto en el único punto donde ocurre, aquí.
 */
export function opcionesComunes<T extends ChartType = ChartType>(
  config: OpcionesComunes,
): ChartOptions<T> {
  const { paleta, movimientoReducido, series, interaccion = 'index' } = config
  const formatear = config.formatearValor ?? ((valor: number) => dinero(valor))

  const comunes: ChartOptions<ChartType> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: movimientoReducido ? false : { duration: 180 },
    // Cada serie tiene su color; el punto y la barra ya bastan como identidad.
    interaction: { mode: interaccion, intersect: false },
    layout: { padding: { top: 8, right: 8, bottom: 0, left: 0 } },
    plugins: {
      legend: {
        display: series >= 2,
        position: config.posicionLeyenda ?? 'top',
        align: 'start',
        labels: {
          boxWidth: 12,
          boxHeight: 12,
          borderRadius: 2,
          useBorderRadius: true,
          color: paleta.texto2,
          font: FUENTE_EJE,
          padding: 16,
        },
      },
      tooltip: {
        backgroundColor: paleta.superficie2,
        borderColor: paleta.borde,
        borderWidth: 1,
        cornerRadius: 12,
        padding: 12,
        titleColor: paleta.texto1,
        titleFont: { size: 15, weight: 600 },
        bodyColor: paleta.texto2,
        bodyFont: { size: 13 },
        bodySpacing: 6,
        displayColors: true,
        // Caja baja y ancha: es la «llave de línea» del color de la serie.
        boxWidth: 10,
        boxHeight: 3,
        boxPadding: 6,
        usePointStyle: false,
        callbacks: {
          title: tituloTooltip,
          label: (item: TooltipItem<ChartType>) => {
            const valor = valorDelPunto(item)
            const etiqueta = item.dataset?.label
            // El signo se conserva: un gasto se lee «-1.234,56 €», no en positivo.
            const importe = formatear(valor)
            return etiqueta ? `${etiqueta}: ${importe}` : importe
          },
        },
      },
    },
  }
  return comunes as ChartOptions<T>
}

/** Eje monetario: siempre desde cero, compacto, rejilla horizontal fina. */
export function escalaMonetaria(
  paleta: PaletaGrafico,
  opciones: { horizontal?: boolean } = {},
): ScaleOptions<'linear'> {
  const { horizontal = false } = opciones
  return {
    type: 'linear',
    beginAtZero: true,
    border: { display: false },
    grid: {
      // En un gráfico temporal solo hay rejilla horizontal; si el valor va en el
      // eje X (barras horizontales) la rejilla vertical sí es la útil.
      display: true,
      color: paleta.rejilla,
      lineWidth: 1,
      drawOnChartArea: true,
      drawTicks: false,
      tickLength: 8,
    },
    ticks: {
      color: paleta.ejeTexto,
      font: FUENTE_EJE,
      padding: 8,
      maxTicksLimit: horizontal ? 6 : 5,
      callback: (valor) => dineroCompacto(typeof valor === 'number' ? valor : Number(valor)),
    },
  }
}

/** Eje de etiquetas: sin rejilla y sin rotación; si no caben, se salta una. */
export function escalaCategorias(
  paleta: PaletaGrafico,
  opciones: { rejilla?: boolean } = {},
): ScaleOptions<'category'> {
  return {
    type: 'category',
    border: { display: true, color: paleta.eje, width: 1 },
    grid: { display: opciones.rejilla ?? false, color: paleta.rejilla, drawTicks: false },
    ticks: {
      color: paleta.ejeTexto,
      font: FUENTE_EJE,
      padding: 8,
      autoSkip: true,
      maxRotation: 0,
      minRotation: 0,
    },
  }
}

/* ------------------------------------------------------------------ *
 * Plugins
 * ------------------------------------------------------------------ */

/** Cruz de guía vertical de 1 px, ajustada al punto activo. */
export function crearCruzDeGuia(color: () => string): Plugin<'line'> {
  return {
    id: 'cruzDeGuia',
    afterDatasetsDraw(grafico) {
      const activos = grafico.getActiveElements()
      if (!activos.length) return
      const { ctx, chartArea } = grafico
      const x = Math.round(activos[0].element.x) + 0.5
      ctx.save()
      ctx.beginPath()
      ctx.lineWidth = 1
      ctx.strokeStyle = color()
      ctx.moveTo(x, chartArea.top)
      ctx.lineTo(x, chartArea.bottom)
      ctx.stroke()
      ctx.restore()
    },
  }
}

/** Línea base en el cero, para las barras divergentes de cash flow. */
export function crearLineaCero(color: () => string): Plugin<'bar'> {
  return {
    id: 'lineaCero',
    afterDatasetsDraw(grafico) {
      const escala = grafico.scales.y
      if (!escala) return
      const { ctx, chartArea } = grafico
      const y = Math.round(escala.getPixelForValue(0)) + 0.5
      ctx.save()
      ctx.beginPath()
      ctx.lineWidth = 1
      ctx.strokeStyle = color()
      ctx.moveTo(chartArea.left, y)
      ctx.lineTo(chartArea.right, y)
      ctx.stroke()
      ctx.restore()
    },
  }
}

export interface PuntosDestacados {
  ultimo?: boolean
  maximo?: boolean
  minimo?: boolean
}

/**
 * Etiqueta solo el último valor, el máximo y el mínimo de la primera serie.
 * Un número sobre cada punto convierte el gráfico en una tabla mal maquetada.
 */
export function crearEtiquetasExtremos(
  paleta: () => PaletaGrafico,
  formatear: (valor: number) => string,
  cuales: PuntosDestacados = { ultimo: true, maximo: true, minimo: true },
): Plugin<'line'> {
  return {
    id: 'etiquetasExtremos',
    afterDatasetsDraw(grafico) {
      const meta = grafico.getDatasetMeta(0)
      if (!meta || meta.hidden) return
      const puntos = meta.data
      const valores = (grafico.data.datasets[0]?.data ?? []) as (number | null)[]
      if (puntos.length < 2) return

      const indices = new Set<number>()
      const definidos = valores
        .map((valor, indice) => ({ valor, indice }))
        .filter((par): par is { valor: number; indice: number } => typeof par.valor === 'number')
      if (!definidos.length) return
      if (cuales.ultimo) indices.add(definidos[definidos.length - 1].indice)
      if (cuales.maximo) {
        indices.add(definidos.reduce((a, b) => (b.valor > a.valor ? b : a)).indice)
      }
      if (cuales.minimo) {
        indices.add(definidos.reduce((a, b) => (b.valor < a.valor ? b : a)).indice)
      }

      const { ctx, chartArea } = grafico
      const colores = paleta()
      ctx.save()
      ctx.font = '600 12px var(--font-sans, system-ui)'
      ctx.fillStyle = colores.texto2
      ctx.textBaseline = 'bottom'
      for (const indice of indices) {
        const punto = puntos[indice]
        const valor = valores[indice]
        if (!punto || typeof valor !== 'number') continue
        const texto = formatear(valor)
        const ancho = ctx.measureText(texto).width
        const x = Math.min(Math.max(punto.x - ancho / 2, chartArea.left), chartArea.right - ancho)
        ctx.fillText(texto, x, Math.max(punto.y - 10, chartArea.top + 12))
      }
      ctx.restore()
    },
  }
}

/* ------------------------------------------------------------------ *
 * Plegado de series
 * ------------------------------------------------------------------ */

export interface Porcion {
  nombre: string
  valor: number
  color?: string
}

/* ------------------------------------------------------------------ *
 * Datos de entrada de los envoltorios
 *
 * Viven aquí y no en cada `.vue` porque `<script setup>` no exporta tipos y
 * porque quien pinta un gráfico solo necesita importar de un sitio.
 * ------------------------------------------------------------------ */

/** Fila de la tabla gemela de un gráfico: celdas ya formateadas. */
export interface FilaTabla {
  clave: string
  celdas: string[]
}

export interface SerieLinea {
  nombre: string
  datos: (number | null)[]
  /** Ranura de la paleta, token o color literal. Si falta, va por orden. */
  color?: string | null
  /** Línea escalonada: obligatoria en precios. */
  escalonada?: boolean
  /** Serie de contexto (el año pasado, la media): gris, sin protagonismo. */
  contexto?: boolean
  /** Relleno del área con el hue de la serie al 10 %. */
  area?: boolean
}

export interface SerieBarras {
  nombre: string
  datos: (number | null)[]
  color?: string | null
  contexto?: boolean
}

/** Un mes de cash flow: lo que entró, lo que salió y el saldo acumulado. */
export interface PuntoCashFlow {
  etiqueta: string
  ingresos: number
  gastos: number
}

/**
 * Deja `maximo` porciones con nombre y agrega el resto en «Otros», que nunca
 * recibe un hue. Sirve para el donut (5) y para cualquier gráfico categórico (8).
 */
export function plegarPorciones(porciones: Porcion[], maximo: number): Porcion[] {
  const ordenadas = [...porciones].sort((a, b) => b.valor - a.valor || a.nombre.localeCompare(b.nombre, 'es'))
  if (ordenadas.length <= maximo) return ordenadas
  const visibles = ordenadas.slice(0, maximo)
  const resto = ordenadas.slice(maximo)
  const suma = resto.reduce((total, p) => total + p.valor, 0)
  visibles.push({ nombre: `Otros (${resto.length})`, valor: suma })
  return visibles
}
