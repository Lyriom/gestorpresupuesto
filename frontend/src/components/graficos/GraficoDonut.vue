<script setup lang="ts">
/**
 * Reparto de un todo, con un máximo de cinco porciones más «Otros».
 *
 * Un donut solo responde «¿qué peso tiene esto sobre el total?» de un vistazo.
 * Para comparar valores parecidos están las barras, así que aquí la tabla no es
 * opcional: va siempre al lado, y los porcentajes van en la leyenda.
 */
import { computed, ref } from 'vue'
import { Doughnut } from 'vue-chartjs'
import type { ChartData, ChartOptions, LegendItem, TooltipItem } from 'chart.js'

import { euros, porcentaje } from '@/lib/formato'
import MarcoGrafico from './MarcoGrafico.vue'
import {
  colorDeSerie,
  opcionesComunes,
  plegarPorciones,
  registrarChartJs,
  usarPaleta,
  type FilaTabla,
  type Porcion,
} from './base'

const props = withDefaults(
  defineProps<{
    porciones: Porcion[]
    titulo?: string
    subtitulo?: string
    alto?: number
    /** Tope de porciones con nombre. La spec no permite pasar de cinco. */
    maximo?: number
    columnaEtiquetas?: string
    resumen?: string
  }>(),
  { maximo: 5, columnaEtiquetas: 'Temática' },
)

registrarChartJs()

const raiz = ref<HTMLElement | null>(null)
const { paleta, movimientoReducido } = usarPaleta(raiz)

const plegadas = computed(() => plegarPorciones(props.porciones, props.maximo))
const total = computed(() => plegadas.value.reduce((suma, p) => suma + p.valor, 0))

const colores = computed(() =>
  plegadas.value.map((p, i) =>
    p.nombre.startsWith('Otros')
      ? paleta.value.otros
      : colorDeSerie(paleta.value, raiz.value, p.color, i),
  ),
)

function proporcion(valor: number): number {
  return total.value > 0 ? valor / total.value : 0
}

const datos = computed<ChartData<'doughnut', number[], string>>(() => ({
  labels: plegadas.value.map((p) => p.nombre),
  datasets: [
    {
      data: plegadas.value.map((p) => p.valor),
      backgroundColor: colores.value,
      // El hueco entre porciones es del color de la superficie, no un borde oscuro.
      borderColor: paleta.value.superficie,
      borderWidth: 2,
      hoverOffset: 0,
      hoverBorderColor: paleta.value.superficie,
    },
  ],
}))

const opciones = computed<ChartOptions<'doughnut'>>(() => {
  const base = opcionesComunes<'doughnut'>({
    paleta: paleta.value,
    movimientoReducido: movimientoReducido.value,
    series: 2, // la leyenda siempre hace falta: identifica cada porción
    interaccion: 'nearest',
    posicionLeyenda: 'bottom',
  })
  return {
    ...base,
    cutout: '62%',
    plugins: {
      ...base.plugins,
      legend: {
        ...base.plugins?.legend,
        labels: {
          ...base.plugins?.legend?.labels,
          // El porcentaje va en la leyenda porque el ojo no mide ángulos.
          generateLabels: (): LegendItem[] =>
            plegadas.value.map((p, i) => ({
              text: `${p.nombre} · ${porcentaje(proporcion(p.valor))}`,
              fillStyle: colores.value[i],
              strokeStyle: colores.value[i],
              lineWidth: 0,
              borderRadius: 2,
              index: i,
              hidden: false,
              fontColor: paleta.value.texto2,
            })),
        },
      },
      tooltip: {
        ...base.plugins?.tooltip,
        callbacks: {
          label: (item: TooltipItem<'doughnut'>) => {
            const valor = Number(item.parsed ?? 0)
            return `${euros(valor)} · ${porcentaje(proporcion(valor))} del total`
          },
        },
      },
    },
  }
})

const columnas = computed(() => [props.columnaEtiquetas, 'Importe', '% del total'])

const filas = computed<FilaTabla[]>(() => [
  ...plegadas.value.map((p, i) => ({
    clave: `${p.nombre}-${i}`,
    celdas: [p.nombre, euros(p.valor), porcentaje(proporcion(p.valor))],
  })),
  { clave: '__total', celdas: ['Total', euros(total.value), porcentaje(total.value > 0 ? 1 : 0)] },
])

const resumenAuto = computed(() => {
  if (props.resumen) return props.resumen
  const mayor = plegadas.value[0]
  const cabeza = mayor
    ? ` La porción mayor es ${mayor.nombre}, ${euros(mayor.valor)}, ${porcentaje(proporcion(mayor.valor))} del total.`
    : ''
  return `${props.titulo ?? 'Reparto'}: ${plegadas.value.length} porciones, total ${euros(total.value)}.${cabeza} Los datos están en la tabla contigua.`
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
      tabla-fija
      :desde-columna-numerica="1"
    >
      <p v-if="total === 0" class="vacio">Este periodo no tiene reparto todavía.</p>
      <Doughnut v-else :data="datos" :options="opciones" />
    </MarcoGrafico>
  </div>
</template>

<style scoped>
.vacio {
  display: grid;
  place-items: center;
  height: 100%;
  margin: 0;
  border: 1px dashed var(--c-border-strong);
  border-radius: var(--r-lg, 12px);
  color: var(--c-text-3);
  font-size: var(--t-sm, 0.875rem);
}
</style>
