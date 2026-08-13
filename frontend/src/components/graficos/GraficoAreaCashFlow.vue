<script setup lang="ts">
/**
 * «¿Entra más de lo que sale?»
 *
 * Barras divergentes sobre la línea cero —ingresos arriba, gastos abajo— y
 * encima el saldo acumulado como línea con su área al 10 %. Las dos magnitudes
 * son euros, así que comparten eje: aquí no hay doble eje Y, nunca lo hay.
 *
 * El color no es verde/rojo sino la rampa divergente ámbar↔azul: es una escala,
 * y verde/rojo colapsa bajo daltonismo. La dirección de la barra y el signo del
 * importe son los canales que llevan el significado.
 */
import { computed, ref } from 'vue'
import { Bar } from 'vue-chartjs'
import type { ChartData, ChartOptions, Plugin } from 'chart.js'

import { euros } from '@/lib/formato'
import MarcoGrafico from './MarcoGrafico.vue'
import {
  conAlfa,
  crearLineaCero,
  escalaCategorias,
  escalaMonetaria,
  opcionesComunes,
  registrarChartJs,
  usarPaleta,
  type FilaTabla,
  type PuntoCashFlow,
} from './base'

const props = withDefaults(
  defineProps<{
    puntos: PuntoCashFlow[]
    titulo?: string
    subtitulo?: string
    alto?: number
    /** Saldo con el que arranca el acumulado. */
    saldoInicial?: number
    columnaEtiquetas?: string
    resumen?: string
  }>(),
  { saldoInicial: 0, columnaEtiquetas: 'Mes' },
)

registrarChartJs()

const raiz = ref<HTMLElement | null>(null)
const { paleta, movimientoReducido } = usarPaleta(raiz)

const saldos = computed(() => {
  let acumulado = props.saldoInicial
  return props.puntos.map((punto) => {
    acumulado += punto.ingresos - punto.gastos
    return acumulado
  })
})

const datos = computed<ChartData<'bar', (number | null)[], string>>(() => {
  const frio = paleta.value.divergente[5]
  const calido = paleta.value.divergente[1]
  const mixto = {
    labels: props.puntos.map((p) => p.etiqueta),
    datasets: [
      {
        label: 'Ingresos',
        data: props.puntos.map((p) => p.ingresos),
        backgroundColor: frio,
        maxBarThickness: 24,
        borderRadius: { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
        borderSkipped: false,
        order: 2,
      },
      {
        label: 'Gastos',
        // Se dibujan hacia abajo: la posición respecto al cero es el canal principal.
        data: props.puntos.map((p) => -p.gastos),
        backgroundColor: calido,
        maxBarThickness: 24,
        borderRadius: { topLeft: 0, topRight: 0, bottomLeft: 4, bottomRight: 4 },
        borderSkipped: false,
        order: 2,
      },
      {
        type: 'line',
        label: 'Saldo acumulado',
        data: saldos.value,
        borderColor: paleta.value.info,
        backgroundColor: conAlfa(paleta.value.info, 0.1),
        borderWidth: 2,
        borderCapStyle: 'round',
        borderJoinStyle: 'round',
        tension: 0,
        fill: 'origin',
        pointRadius: 4,
        pointHoverRadius: 5,
        pointBorderWidth: 2,
        pointBorderColor: paleta.value.superficie,
        pointBackgroundColor: paleta.value.info,
        hitRadius: 12,
        order: 1,
      },
    ],
  }
  // Chart.js modela los gráficos mixtos con `type` por conjunto de datos, y eso
  // no encaja en `ChartData<'bar'>`; la afirmación se queda aquí, en un sitio.
  return mixto as unknown as ChartData<'bar', (number | null)[], string>
})

const opciones = computed<ChartOptions<'bar'>>(() => {
  const base = opcionesComunes<'bar'>({
    paleta: paleta.value,
    movimientoReducido: movimientoReducido.value,
    series: 3,
    interaccion: 'index',
  })
  return {
    ...base,
    scales: {
      // Apilados en la misma ranura: uno sube y otro baja desde el cero.
      x: { ...escalaCategorias(paleta.value), stacked: true },
      y: { ...escalaMonetaria(paleta.value), stacked: true },
    },
  }
})

const complementos = computed<Plugin<'bar'>[]>(() => [
  crearLineaCero(() => paleta.value.eje),
])

const columnas = computed(() => [
  props.columnaEtiquetas,
  'Ingresos',
  'Gastos',
  'Saldo del mes',
  'Acumulado',
])

const filas = computed<FilaTabla[]>(() =>
  props.puntos.map((punto, i) => ({
    clave: `${punto.etiqueta}-${i}`,
    celdas: [
      punto.etiqueta,
      euros(punto.ingresos, { signoSiempre: true }),
      euros(-punto.gastos),
      euros(punto.ingresos - punto.gastos, { signoSiempre: true }),
      euros(saldos.value[i]),
    ],
  })),
)

const resumenAuto = computed(() => {
  if (props.resumen) return props.resumen
  const ultimo = saldos.value[saldos.value.length - 1]
  const cierre =
    typeof ultimo === 'number' ? ` El saldo acumulado termina en ${euros(ultimo)}.` : ''
  return `${props.titulo ?? 'Entradas y salidas'}: ${props.puntos.length} periodos con ingresos, gastos y saldo acumulado.${cierre} Los datos están en la tabla siguiente.`
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
      <Bar :data="datos" :options="opciones" :plugins="complementos" />
    </MarcoGrafico>
  </div>
</template>
