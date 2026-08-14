<script setup lang="ts">
/**
 * Gasto por temática (horizontales, ordenadas de mayor a menor) y comparativa de
 * comercios (agrupadas, cinco como mucho).
 *
 * Con una sola serie las barras van todas del mismo hue: la identidad ya la da
 * la etiqueta, y doce colores para una sola magnitud es ruido. Se pasa a
 * `colorear: 'categorico'` cuando cada barra *es* una temática y su color debe
 * coincidir con el de la BudgetBar.
 */
import { computed, ref } from 'vue'
import { Bar } from 'vue-chartjs'
import type { ChartData, ChartOptions } from 'chart.js'

import { dinero } from '@/lib/formato'
import MarcoGrafico from './MarcoGrafico.vue'
import {
  colorDeSerie,
  escalaCategorias,
  escalaMonetaria,
  opcionesComunes,
  registrarChartJs,
  usarPaleta,
  type FilaTabla,
  type SerieBarras,
} from './base'

const props = withDefaults(
  defineProps<{
    etiquetas: string[]
    series: SerieBarras[]
    titulo?: string
    subtitulo?: string
    alto?: number
    /** Horizontal para «¿en qué se me va el dinero?»; vertical para series por mes. */
    horizontal?: boolean
    /** Con una serie: un solo hue, o el color propio de cada temática. */
    colorear?: 'unico' | 'categorico'
    /** Colores por etiqueta (los de las temáticas) cuando `colorear` es categórico. */
    coloresEtiquetas?: (string | null)[]
    /** Ordena de mayor a menor. Solo tiene sentido con una serie. */
    ordenar?: boolean
    apiladas?: boolean
    columnaEtiquetas?: string
    resumen?: string
  }>(),
  {
    horizontal: true,
    colorear: 'unico',
    ordenar: true,
    apiladas: false,
    columnaEtiquetas: 'Temática',
  },
)

registrarChartJs()

const raiz = ref<HTMLElement | null>(null)
const { paleta, movimientoReducido } = usarPaleta(raiz)

const unaSerie = computed(() => props.series.length === 1)

/** Orden de lectura: con una serie, de mayor a menor; con varias, el que llega. */
const orden = computed(() => {
  const indices = props.etiquetas.map((_, i) => i)
  if (!props.ordenar || !unaSerie.value) return indices
  const valores = props.series[0]?.datos ?? []
  return indices.sort((a, b) => (Number(valores[b] ?? 0) - Number(valores[a] ?? 0)))
})

const etiquetasOrdenadas = computed(() => orden.value.map((i) => props.etiquetas[i]))

const datos = computed<ChartData<'bar', (number | null)[], string>>(() => {
  const categorico = props.colorear === 'categorico' && unaSerie.value
  return {
    labels: etiquetasOrdenadas.value,
    datasets: props.series.map((serie, s) => {
      const uniforme = serie.contexto
        ? paleta.value.deenfasis
        : colorDeSerie(paleta.value, raiz.value, serie.color, s)
      return {
        label: serie.nombre,
        data: orden.value.map((i) => serie.datos[i] ?? null),
        backgroundColor: categorico
          ? orden.value.map((i) =>
              colorDeSerie(paleta.value, raiz.value, props.coloresEtiquetas?.[i], i),
            )
          : uniforme,
        // El hueco de 2 px entre segmentos apilados es del color de la superficie.
        borderColor: paleta.value.superficie,
        borderWidth: props.apiladas
          ? props.horizontal
            ? { top: 0, bottom: 0, left: 0, right: 2 }
            : { top: 2, bottom: 0, left: 0, right: 0 }
          : 0,
        maxBarThickness: 24,
        borderRadius: props.horizontal
          ? { topLeft: 0, bottomLeft: 0, topRight: 4, bottomRight: 4 }
          : { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
        borderSkipped: false as const,
      }
    }),
  }
})

const opciones = computed<ChartOptions<'bar'>>(() => {
  const base = opcionesComunes<'bar'>({
    paleta: paleta.value,
    movimientoReducido: movimientoReducido.value,
    series: props.series.length,
    interaccion: 'nearest',
  })
  const monetaria = escalaMonetaria(paleta.value, { horizontal: props.horizontal })
  const categorias = escalaCategorias(paleta.value)
  return {
    ...base,
    indexAxis: props.horizontal ? 'y' : 'x',
    scales: props.horizontal
      ? {
          x: { ...monetaria, stacked: props.apiladas },
          // La rejilla útil aquí es la del eje de valores, que es el horizontal.
          y: { ...categorias, stacked: props.apiladas, grid: { display: false } },
        }
      : {
          x: { ...categorias, stacked: props.apiladas },
          y: { ...monetaria, stacked: props.apiladas },
        },
  }
})

const columnas = computed(() => [props.columnaEtiquetas, ...props.series.map((s) => s.nombre)])

const filas = computed<FilaTabla[]>(() =>
  orden.value.map((i) => ({
    clave: `${props.etiquetas[i]}-${i}`,
    celdas: [
      props.etiquetas[i],
      ...props.series.map((serie) => {
        const valor = serie.datos[i]
        return typeof valor === 'number' ? dinero(valor) : '—'
      }),
    ],
  })),
)

const resumenAuto = computed(() => {
  if (props.resumen) return props.resumen
  const primera = props.series[0]
  const mayor = orden.value[0]
  const cabeza =
    primera && mayor !== undefined && typeof primera.datos[mayor] === 'number'
      ? ` El valor más alto es ${props.etiquetas[mayor]}, ${dinero(primera.datos[mayor])}.`
      : ''
  return `${props.titulo ?? 'Gráfico de barras'}: ${props.etiquetas.length} categorías y ${props.series.length} serie(s).${cabeza} Los datos están en la tabla siguiente.`
})
</script>

<template>
  <div ref="raiz">
    <MarcoGrafico
      :titulo="props.titulo"
      :subtitulo="props.subtitulo"
      :resumen="resumenAuto"
      :columnas="columnas"
      :filas="filas"
      :alto="props.alto"
    >
      <Bar :data="datos" :options="opciones" />
    </MarcoGrafico>
  </div>
</template>
