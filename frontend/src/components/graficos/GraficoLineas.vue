<script setup lang="ts">
/**
 * Evolución mes a mes y precio de un producto.
 *
 * Para precios se usa `escalonada`: entre dos compras el precio no «sube poco a
 * poco», se mantiene y da un salto el día de la siguiente compra. Una recta
 * inclinada contaría algo que no ha pasado.
 */
import { computed, ref } from 'vue'
import { Line } from 'vue-chartjs'
import type { ChartData, ChartOptions, Plugin } from 'chart.js'

import { dinero } from '@/lib/formato'
import MarcoGrafico from './MarcoGrafico.vue'
import {
  colorDeSerie,
  conAlfa,
  crearCruzDeGuia,
  crearEtiquetasExtremos,
  escalaCategorias,
  escalaMonetaria,
  opcionesComunes,
  registrarChartJs,
  usarPaleta,
  type FilaTabla,
  type SerieLinea,
} from './base'

const props = withDefaults(
  defineProps<{
    etiquetas: string[]
    series: SerieLinea[]
    titulo?: string
    subtitulo?: string
    alto?: number
    /** Cabecera de la primera columna de la tabla gemela. */
    columnaEtiquetas?: string
    /** Se añade tras el importe en precios unitarios: `2,46 €/kg`. */
    unidad?: string
    /** Etiqueta el último valor, el máximo y el mínimo. Nunca todos los puntos. */
    etiquetarExtremos?: boolean
    resumen?: string
  }>(),
  { columnaEtiquetas: 'Periodo', etiquetarExtremos: true },
)

registrarChartJs()

const raiz = ref<HTMLElement | null>(null)
const { paleta, movimientoReducido } = usarPaleta(raiz)

/** Los precios unitarios llevan su unidad pegada al importe. */
function formatear(valor: number): string {
  return props.unidad ? `${dinero(valor)}/${props.unidad}` : dinero(valor)
}

const coloresSerie = computed(() =>
  props.series.map((serie, i) =>
    serie.contexto
      ? paleta.value.deenfasis
      : colorDeSerie(paleta.value, raiz.value, serie.color, i),
  ),
)

const datos = computed<ChartData<'line', (number | null)[], string>>(() => ({
  labels: props.etiquetas,
  datasets: props.series.map((serie, i) => {
    const color = coloresSerie.value[i]
    return {
      label: serie.nombre,
      data: serie.datos,
      borderColor: color,
      backgroundColor: serie.area ? conAlfa(color, 0.1) : color,
      borderWidth: 2,
      borderCapStyle: 'round' as const,
      borderJoinStyle: 'round' as const,
      tension: 0,
      stepped: serie.escalonada === true,
      fill: serie.area ? ('origin' as const) : false,
      pointRadius: 4,
      pointHoverRadius: 5,
      pointBorderWidth: 2,
      pointBorderColor: paleta.value.superficie,
      pointBackgroundColor: color,
      hitRadius: 12,
      order: serie.contexto ? 2 : 1,
    }
  }),
}))

const opciones = computed<ChartOptions<'line'>>(() => {
  const base = opcionesComunes<'line'>({
    paleta: paleta.value,
    movimientoReducido: movimientoReducido.value,
    series: props.series.length,
    interaccion: 'index',
    formatearValor: formatear,
  })
  return {
    ...base,
    scales: {
      x: escalaCategorias(paleta.value),
      y: escalaMonetaria(paleta.value),
    },
  }
})

const complementos = computed<Plugin<'line'>[]>(() => {
  const lista: Plugin<'line'>[] = [crearCruzDeGuia(() => paleta.value.bordeFuerte)]
  if (props.etiquetarExtremos) {
    lista.push(crearEtiquetasExtremos(() => paleta.value, formatear))
  }
  return lista
})

const columnas = computed(() => [props.columnaEtiquetas, ...props.series.map((s) => s.nombre)])

const filas = computed<FilaTabla[]>(() =>
  props.etiquetas.map((etiqueta, i) => ({
    clave: `${etiqueta}-${i}`,
    celdas: [
      etiqueta,
      ...props.series.map((serie) => {
        const valor = serie.datos[i]
        return typeof valor === 'number' ? formatear(valor) : '—'
      }),
    ],
  })),
)

const resumenAuto = computed(() => {
  if (props.resumen) return props.resumen
  const primera = props.series[0]
  const ultimo = [...(primera?.datos ?? [])].reverse().find((v) => typeof v === 'number')
  const rango =
    props.etiquetas.length > 1
      ? `de ${props.etiquetas[0]} a ${props.etiquetas[props.etiquetas.length - 1]}`
      : (props.etiquetas[0] ?? 'sin periodos')
  const cierre = typeof ultimo === 'number' ? `Último valor ${formatear(ultimo)}.` : ''
  return `${props.titulo ?? 'Gráfico de líneas'}: ${props.series.length} serie(s), ${rango}. ${cierre} Los datos están en la tabla siguiente.`
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
      <Line :data="datos" :options="opciones" :plugins="complementos" />
    </MarcoGrafico>
  </div>
</template>
