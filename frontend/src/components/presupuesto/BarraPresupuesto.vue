<script setup lang="ts">
/**
 * BudgetBar: los ingresos del mes como una barra que se reparte por temáticas y
 * se va consumiendo con el uso.
 *
 * Tres informaciones en un solo objeto, cada una por un canal distinto:
 *   · lo asignado por temática → la ANCHURA del segmento
 *   · lo gastado dentro de lo asignado → la SATURACIÓN dentro del segmento
 *   · lo que sobra por repartir → una cola NEUTRA al final
 * y el exceso, que al ser el dato que más duele, se lleva cuatro canales a la
 * vez: color, borde, patrón de rayas e icono con texto.
 *
 * Sobre la anchura: el denominador es `max(ingresos, asignado)`, como manda la
 * spec, más lo que el gasto se salga de ahí. Así una sobreasignación comprime la
 * barra en vez de desbordar el contenedor, y el gasto por encima de los ingresos
 * tiene sitio propio para su cola roja. Cuando no hay ninguna de las dos cosas,
 * el resultado coincide con el `porcentaje_de_la_barra` que calcula el backend.
 */
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { ArrowLeft, CircleAlert, Table2, TriangleAlert } from 'lucide-vue-next'

import { aNumero, euros, etiquetaPeriodo, periodoDe, porcentaje } from '@/lib/formato'
import BarraCategoria from './BarraCategoria.vue'
import { COLOR_OTROS, colorDeCategoria } from './colores'
import type {
  BarraPresupuesto as DatosBarra,
  CifrasMes,
  SegmentoBarra,
  TramoBarra,
} from './types'

const props = withDefaults(
  defineProps<{
    barra: DatosBarra | null
    cargando?: boolean
    /** Día del mes para la marca de ritmo. Si no se pasa, se deduce del periodo. */
    diaActual?: number
    diasDelMes?: number
    /** Tope de segmentos con nombre antes de plegar en «Otros». */
    maxSegmentos?: number
    mostrarLeyenda?: boolean
    mostrarCabecera?: boolean
    /** Avisos contextuales con acciones bajo el carril. */
    mostrarAvisos?: boolean
    /** Uso interno: la barra anidada de «Otros» no repite cabecera ni plegado. */
    anidada?: boolean
  }>(),
  {
    cargando: false,
    maxSegmentos: 8,
    mostrarLeyenda: true,
    mostrarCabecera: true,
    mostrarAvisos: true,
    anidada: false,
  },
)

const emit = defineEmits<{
  /** Clic o Enter en un segmento: llevar a Transacciones con el filtro puesto. */
  activar: [segmento: SegmentoBarra]
  /** Espacio en un segmento, o «Reasignar» en un aviso. */
  reasignar: [segmento: SegmentoBarra | null]
  repartir: []
  copiarMesAnterior: []
  ponerIngresos: []
}>()

/** Por debajo de este porcentaje del carril un segmento no se puede leer: se plega. */
const MINIMO_VISIBLE_PCT = 3
/** Ancho en píxeles a partir del cual cabe una etiqueta dentro del segmento. */
const ANCHO_PARA_ETIQUETA = 72

const id = useId()
const esMovil = useMediaQuery('(max-width: 639px)')

/* ------------------------------------------------------------------ *
 * Cifras
 * ------------------------------------------------------------------ */

const segmentos = computed(() => props.barra?.segmentos ?? [])

const cifras = computed<CifrasMes>(() => {
  const b = props.barra
  return {
    ingresos: aNumero(b?.ingresos),
    asignado: aNumero(b?.total_asignado),
    gastado: aNumero(b?.total_gastado),
    arrastrado: aNumero(b?.total_arrastrado),
    sinAsignar: aNumero(b?.sin_asignar),
    disponible: aNumero(b?.disponible),
    porcentajeAsignado: aNumero(b?.porcentaje_asignado),
    porcentajeGastado: aNumero(b?.porcentaje_gastado),
    sobreasignado: aNumero(b?.sin_asignar) < 0,
    enRojo: aNumero(b?.total_gastado) > aNumero(b?.ingresos) && aNumero(b?.ingresos) > 0,
    sobrepasadas: segmentos.value.filter((s) => s.estado === 'sobrepasado'),
  }
})

/** Base de la anchura y cuánto se sale el gasto de ella. */
const escala = computed(() => {
  const base = Math.max(cifras.value.ingresos, cifras.value.asignado)
  const desborde = Math.max(0, cifras.value.gastado - base)
  return { base, desborde, total: base + desborde }
})

const sinIngresos = computed(() => escala.value.base <= 0)
const sinRepartir = computed(() => !sinIngresos.value && cifras.value.asignado <= 0)

/* ------------------------------------------------------------------ *
 * Plegado en «Otros» (§6.4 F), determinista
 * ------------------------------------------------------------------ */

function porAsignado(a: SegmentoBarra, b: SegmentoBarra): number {
  const dif = aNumero(b.asignado) - aNumero(a.asignado)
  return dif !== 0 ? dif : a.nombre.localeCompare(b.nombre, 'es')
}

const plegado = computed(() => {
  const ordenados = [...segmentos.value].sort(porAsignado)
  if (props.anidada) return { visibles: ordenados, otros: [] as SegmentoBarra[] }

  const total = escala.value.total || 1
  const anchoDe = (s: SegmentoBarra) => (aNumero(s.asignado) / total) * 100

  // Una temática sobrepasada nunca se plega, aunque sea diminuta: si tiene
  // exceso, tiene sitio propio. Es la excepción explícita al mínimo del 3 %.
  const fijos = ordenados.filter((s) => s.estado === 'sobrepasado')
  const candidatos = ordenados.filter((s) => s.estado !== 'sobrepasado')
  const otros: SegmentoBarra[] = []

  const sobran = () => fijos.length + candidatos.length > props.maxSegmentos
  const hayMinusculos = () => candidatos.some((s) => anchoDe(s) < MINIMO_VISIBLE_PCT)
  while (candidatos.length > 0 && (sobran() || hayMinusculos())) {
    otros.push(candidatos.pop() as SegmentoBarra)
  }

  // «Otros (1)» no agrega nada y esconde un nombre: mejor dejarlo a la vista.
  if (otros.length === 1) candidatos.push(otros.pop() as SegmentoBarra)

  return { visibles: [...fijos, ...candidatos].sort(porAsignado), otros }
})

/* ------------------------------------------------------------------ *
 * Tramos del carril
 * ------------------------------------------------------------------ */

function tramoDeSegmento(s: SegmentoBarra, total: number): TramoBarra {
  const asignado = aNumero(s.asignado)
  const arrastrado = aNumero(s.arrastrado)
  const efectivo = asignado + arrastrado
  const gastado = aNumero(s.gastado)
  const sobrepaso = aNumero(s.sobrepaso)
  const consumidoPct = aNumero(s.porcentaje_consumido)
  return {
    clave: s.categoria_id,
    tipo: 'categoria',
    nombre: s.nombre,
    color: colorDeCategoria(s.color, s.categoria_id),
    importe: asignado,
    anchoPct: total > 0 ? (asignado / total) * 100 : 0,
    llenadoPct: efectivo > 0 ? Math.min(gastado / efectivo, 1) * 100 : gastado > 0 ? 100 : 0,
    crestaPct: efectivo > 0 ? Math.min(sobrepaso / efectivo, 1) * 100 : sobrepaso > 0 ? 100 : 0,
    gastado,
    disponible: aNumero(s.disponible),
    arrastrado,
    sobrepaso,
    consumidoPct,
    estado: s.estado,
    segmentos: [s],
  }
}

const tramos = computed<TramoBarra[]>(() => {
  const total = escala.value.total
  if (total <= 0) return []
  const lista = plegado.value.visibles.map((s) => tramoDeSegmento(s, total))

  const otros = plegado.value.otros
  if (otros.length > 0) {
    const suma = (campo: (s: SegmentoBarra) => number) =>
      otros.reduce((acumulado, s) => acumulado + campo(s), 0)
    const asignado = suma((s) => aNumero(s.asignado))
    const arrastrado = suma((s) => aNumero(s.arrastrado))
    const gastado = suma((s) => aNumero(s.gastado))
    const efectivo = asignado + arrastrado
    lista.push({
      clave: '__otros',
      tipo: 'otros',
      nombre: `Otros (${otros.length})`,
      color: COLOR_OTROS,
      importe: asignado,
      anchoPct: (asignado / total) * 100,
      llenadoPct: efectivo > 0 ? Math.min(gastado / efectivo, 1) * 100 : 0,
      crestaPct: 0,
      gastado,
      disponible: efectivo - gastado,
      arrastrado,
      sobrepaso: 0,
      consumidoPct: efectivo > 0 ? (gastado / efectivo) * 100 : 0,
      estado: null,
      segmentos: otros,
    })
  }

  if (cifras.value.sinAsignar > 0) {
    lista.push({
      clave: '__sin-asignar',
      tipo: 'sin-asignar',
      nombre: 'Sin asignar',
      color: 'var(--c-track)',
      importe: cifras.value.sinAsignar,
      anchoPct: (cifras.value.sinAsignar / total) * 100,
      llenadoPct: 0,
      crestaPct: 0,
      gastado: 0,
      disponible: cifras.value.sinAsignar,
      arrastrado: 0,
      sobrepaso: 0,
      consumidoPct: 0,
      estado: 'sin_asignar',
      segmentos: [],
    })
  }

  if (escala.value.desborde > 0) {
    lista.push({
      clave: '__en-rojo',
      tipo: 'en-rojo',
      nombre: 'En rojo',
      color: 'var(--c-negative)',
      importe: escala.value.desborde,
      anchoPct: (escala.value.desborde / total) * 100,
      llenadoPct: 100,
      crestaPct: 0,
      gastado: escala.value.desborde,
      disponible: -escala.value.desborde,
      arrastrado: 0,
      sobrepaso: escala.value.desborde,
      consumidoPct: 100,
      estado: 'sobrepasado',
      segmentos: [],
    })
  }

  return lista
})

/** Posición izquierda de cada tramo, con los huecos de 2 px ya contados. */
const izquierdas = computed(() => {
  let acumulado = 0
  return tramos.value.map((t) => {
    const inicio = acumulado
    acumulado += t.anchoPct
    return inicio
  })
})

/**
 * El hueco de 2 px entre segmentos es un borde del color de la superficie, no un
 * `gap`: así la anchura de cada tramo sigue siendo su porcentaje exacto y las
 * marcas de la capa superior (crestas, límite de ingresos) caen donde deben.
 */
function estiloTramo(t: TramoBarra): Record<string, string> {
  return {
    width: `${t.anchoPct}%`,
    '--color-tramo': t.color,
    '--llenado': `${t.llenadoPct}%`,
  }
}

function posicion(i: number): string {
  return `${izquierdas.value[i]}%`
}

/**
 * La sobreasignación no es un tramo aparte: cada euro repartido ya pertenece a
 * una temática. Se marca con la línea del límite de ingresos y una trama de 45°
 * superpuesta sobre todo lo que queda a su derecha.
 */
const sobreasignacion = computed(() => {
  if (!cifras.value.sobreasignado || escala.value.total <= 0) return null
  const desdePct = (cifras.value.ingresos / escala.value.total) * 100
  return { desdePct, importe: -cifras.value.sinAsignar }
})

/** El límite de ingresos deja de coincidir con el final del carril; hay que marcarlo. */
const limiteIngresos = computed(() => {
  const { total } = escala.value
  if (total <= 0 || cifras.value.ingresos <= 0) return null
  const pct = (cifras.value.ingresos / total) * 100
  return pct < 99.5 ? pct : null
})

/* ------------------------------------------------------------------ *
 * Ritmo del mes
 * ------------------------------------------------------------------ */

const ritmo = computed(() => {
  const periodo = props.barra?.periodo
  if (!periodo) return null
  const esActual = periodo === periodoDe()
  const [anyo, mes] = periodo.split('-').map(Number)
  const diasDelMes = props.diasDelMes ?? (anyo && mes ? new Date(anyo, mes, 0).getDate() : 30)
  const diaActual = props.diaActual ?? (esActual ? new Date().getDate() : null)
  if (!diaActual || !diasDelMes) return null
  const dia = Math.min(Math.max(diaActual, 1), diasDelMes)
  return {
    dia,
    diasDelMes,
    diasRestantes: Math.max(diasDelMes - dia, 0),
    pct: (dia / diasDelMes) * 100,
    texto: `Día ${dia} de ${diasDelMes}`,
  }
})

/* ------------------------------------------------------------------ *
 * Interacción: puntero, teclado y tooltip
 * ------------------------------------------------------------------ */

const indiceActivo = ref(0)
const indiceFoco = ref<number | null>(null)
const indiceHover = ref<number | null>(null)
const hoverDiferido = ref<number | null>(null)
const anuncio = ref('')
let temporizador: ReturnType<typeof setTimeout> | null = null

const referencias = ref<(HTMLElement | null)[]>([])
function guardarReferencia(el: HTMLElement | null, i: number): void {
  referencias.value[i] = el
}

// El tooltip aparece al instante con el foco (el teclado ya es deliberado) y a
// los 120 ms con el puntero, para no dispararlo al cruzar la barra de paso.
function entrar(i: number): void {
  indiceHover.value = i
  if (temporizador) clearTimeout(temporizador)
  temporizador = setTimeout(() => {
    hoverDiferido.value = i
  }, 120)
}

function salir(): void {
  indiceHover.value = null
  hoverDiferido.value = null
  if (temporizador) clearTimeout(temporizador)
}

onBeforeUnmount(() => {
  if (temporizador) clearTimeout(temporizador)
})

const indiceResaltado = computed(() => indiceFoco.value ?? indiceHover.value)
const indiceTooltip = computed(() => indiceFoco.value ?? hoverDiferido.value)
const tramoTooltip = computed(() =>
  indiceTooltip.value === null ? null : (tramos.value[indiceTooltip.value] ?? null),
)

watch(tramos, () => {
  if (indiceActivo.value >= tramos.value.length) indiceActivo.value = 0
  referencias.value.length = tramos.value.length
})

async function mover(i: number): Promise<void> {
  const n = tramos.value.length
  if (n === 0) return
  const destino = Math.min(Math.max(i, 0), n - 1)
  indiceActivo.value = destino
  await nextTick()
  referencias.value[destino]?.focus()
  anuncio.value = `${etiquetaTramo(tramos.value[destino], destino)}`
}

function alTeclado(evento: KeyboardEvent): void {
  const n = tramos.value.length
  if (n === 0) return
  const actual = indiceFoco.value ?? indiceActivo.value
  switch (evento.key) {
    case 'ArrowRight':
      evento.preventDefault()
      void mover(actual + 1)
      break
    case 'ArrowLeft':
      evento.preventDefault()
      void mover(actual - 1)
      break
    case 'Home':
      evento.preventDefault()
      void mover(0)
      break
    case 'End':
      evento.preventDefault()
      void mover(n - 1)
      break
    case 'Enter':
      evento.preventDefault()
      activarTramo(tramos.value[actual])
      break
    case ' ':
    case 'Spacebar':
      evento.preventDefault()
      emit('reasignar', tramos.value[actual]?.segmentos[0] ?? null)
      break
    default:
      break
  }
}

const otrosAbierto = ref(false)

function activarTramo(t: TramoBarra | undefined): void {
  if (!t) return
  if (t.tipo === 'otros') {
    otrosAbierto.value = true
    return
  }
  if (t.tipo === 'sin-asignar') {
    emit('repartir')
    return
  }
  const segmento = t.segmentos[0]
  if (segmento) emit('activar', segmento)
}

/** Barra anidada de «Otros»: los mismos datos, con las temáticas plegadas dentro. */
const barraOtros = computed<DatosBarra | null>(() => {
  const grupo = plegado.value.otros
  if (grupo.length === 0 || !props.barra) return null
  const suma = (campo: (s: SegmentoBarra) => number) =>
    grupo.reduce((acumulado, s) => acumulado + campo(s), 0)
  const asignado = suma((s) => aNumero(s.asignado))
  const gastado = suma((s) => aNumero(s.gastado))
  const arrastrado = suma((s) => aNumero(s.arrastrado))
  return {
    periodo: props.barra.periodo,
    // Dentro del grupo el 100 % es lo que el grupo tiene asignado: no hay más
    // ingresos que repartir en este nivel.
    ingresos: asignado.toFixed(2),
    total_asignado: asignado.toFixed(2),
    total_gastado: gastado.toFixed(2),
    total_arrastrado: arrastrado.toFixed(2),
    sin_asignar: '0.00',
    disponible: (asignado + arrastrado - gastado).toFixed(2),
    porcentaje_asignado: '100.00',
    porcentaje_gastado: (asignado > 0 ? (gastado / asignado) * 100 : 0).toFixed(2),
    segmentos: grupo,
    avisos: [],
  }
})

/* ------------------------------------------------------------------ *
 * Textos
 * ------------------------------------------------------------------ */

const nombreMes = computed(() =>
  props.barra ? etiquetaPeriodo(props.barra.periodo) : etiquetaPeriodo(periodoDe()),
)

const titulo = computed(() => {
  const mes = nombreMes.value
  return `Presupuesto de ${mes.charAt(0).toLowerCase()}${mes.slice(1)}`
})

const resumenTexto = computed(() => {
  const c = cifras.value
  return `${euros(c.ingresos)} de ingresos. ${euros(c.asignado)} asignados. ${euros(c.gastado)} gastados. ${euros(c.disponible)} disponibles.`
})

function etiquetaTramo(t: TramoBarra | undefined, i: number): string {
  if (!t) return ''
  const posicionTexto = `segmento ${i + 1} de ${tramos.value.length}`
  const delTotal = `${porcentaje(t.anchoPct / 100)} del presupuesto`
  if (t.tipo === 'sin-asignar') {
    return `Sin asignar: ${euros(t.importe)}, ${delTotal}, ${posicionTexto}.`
  }
  if (t.tipo === 'en-rojo') {
    return `En rojo: ${euros(t.importe)} gastados por encima de los ingresos, ${posicionTexto}.`
  }
  const efectivo = t.importe + t.arrastrado
  const base = `${t.nombre}: ${euros(t.gastado)} gastados de ${euros(efectivo)} asignados, ${porcentaje(t.consumidoPct / 100)} de lo asignado, ${delTotal}`
  const exceso = t.sobrepaso > 0 ? `, sobrepasada en ${euros(t.sobrepaso)}` : ''
  const grupo = t.tipo === 'otros' ? `, agrupa ${t.segmentos.length} temáticas` : ''
  return `${base}${exceso}${grupo}, ${posicionTexto}.`
}

/** «Ritmo: 12,42 €/día · vas bien» — la parte del tooltip que da el contexto. */
function textoRitmo(t: TramoBarra): string | null {
  const r = ritmo.value
  if (!r || r.diasRestantes <= 0 || t.tipo === 'sin-asignar') return null
  const porDia = t.disponible / r.diasRestantes
  const transcurrido = r.pct
  const juicio =
    t.sobrepaso > 0
      ? 'te has pasado'
      : t.consumidoPct > transcurrido + 10
        ? 'vas rápido'
        : 'vas bien'
  return `Ritmo: ${euros(porDia)}/día · ${juicio}`
}

const tramoOtros = computed(() => tramos.value.find((t) => t.tipo === 'otros') ?? null)

const excesosVisibles = computed(() =>
  tramos.value
    .map((t, i) => ({ t, i }))
    .filter(({ t }) => t.tipo === 'categoria' && t.sobrepaso > 0),
)

const totalSobrepasado = computed(() =>
  cifras.value.sobrepasadas.reduce((total, s) => total + aNumero(s.sobrepaso), 0),
)

/* ------------------------------------------------------------------ *
 * Medidas
 * ------------------------------------------------------------------ */

const pista = ref<HTMLElement | null>(null)
const anchoPista = ref(0)
let observador: ResizeObserver | null = null

watch(pista, (elemento) => {
  observador?.disconnect()
  if (!elemento || typeof ResizeObserver === 'undefined') return
  observador = new ResizeObserver((entradas) => {
    anchoPista.value = entradas[0]?.contentRect.width ?? 0
  })
  observador.observe(elemento)
  anchoPista.value = elemento.clientWidth
})

onBeforeUnmount(() => observador?.disconnect())

/** Con dos o tres temáticas la barra puede hacer el trabajo de una tarjeta. */
const modoTarjetas = computed(
  () =>
    !esMovil.value &&
    plegado.value.visibles.length >= 1 &&
    plegado.value.visibles.length <= 3,
)

function cabeEtiqueta(t: TramoBarra): boolean {
  if (esMovil.value) return false
  return (anchoPista.value * t.anchoPct) / 100 >= ANCHO_PARA_ETIQUETA
}

const tablaAbierta = ref(false)
</script>

<template>
  <section
    class="tarjeta"
    :class="{
      'tarjeta--rojo': cifras.enRojo,
      'tarjeta--anidada': props.anidada,
    }"
    :aria-labelledby="`${id}-titulo`"
  >
    <!-- Cargando: un solo bloque a la altura real del carril. Inventar segmentos
         falsos que luego cambian produce un salto desagradable. -->
    <template v-if="props.cargando">
      <div class="esqueleto esqueleto--titulo" />
      <div class="esqueleto esqueleto--cifra" />
      <div class="esqueleto esqueleto--carril" />
      <div class="esqueleto esqueleto--leyenda" />
      <p class="solo-lectores" role="status">Cargando el presupuesto del mes.</p>
    </template>

    <template v-else>
      <header v-if="props.mostrarCabecera && !props.anidada" class="cabecera">
        <div>
          <h2 :id="`${id}-titulo`" class="titulo">{{ titulo }}</h2>
          <p class="cifra-heroe">{{ euros(cifras.ingresos) }}</p>
          <!-- Una frase seguida para el lector de pantalla: la línea de cifras de
               abajo está troceada en spans y se lee peor. -->
          <p :id="`${id}-resumen`" class="solo-lectores">{{ resumenTexto }}</p>
          <p class="linea-cifras">
            <span v-if="cifras.sobreasignado" class="alerta-suave">
              <CircleAlert :size="14" aria-hidden="true" />
              Asignado {{ euros(cifras.asignado) }} de {{ euros(cifras.ingresos) }}
            </span>
            <span v-else>Asignado {{ euros(cifras.asignado) }}</span>
            <span aria-hidden="true">·</span>
            <span :class="{ 'alerta-fuerte': cifras.enRojo }">
              Gastado {{ euros(cifras.gastado) }}
            </span>
            <span aria-hidden="true">·</span>
            <span>Disponible {{ euros(cifras.disponible) }}</span>
          </p>
        </div>
        <p class="etiqueta-ingresos">Ingresos del mes</p>
      </header>

      <!-- La barra anidada de «Otros» sustituye al carril en el sitio, sin
           cambiar de pantalla. -->
      <template v-if="otrosAbierto && barraOtros">
        <nav class="miga" aria-label="Migas de pan">
          <button type="button" class="boton-volver" @click="otrosAbierto = false">
            <ArrowLeft :size="16" aria-hidden="true" />
            Volver
          </button>
          <span class="miga-texto">
            Presupuesto <span aria-hidden="true">›</span> Otros ({{ plegado.otros.length }})
          </span>
        </nav>
        <BarraPresupuesto
          :barra="barraOtros"
          anidada
          :mostrar-cabecera="false"
          :mostrar-avisos="false"
          :dia-actual="props.diaActual"
          :dias-del-mes="props.diasDelMes"
          @activar="emit('activar', $event)"
          @reasignar="emit('reasignar', $event)"
        />
      </template>

      <template v-else>
        <!-- H. Sin ingresos declarados: carril vacío con el único borde
             discontinuo permitido en todo el sistema. -->
        <div v-if="sinIngresos" class="vacio">
          <div class="carril-vacio">Aún no has puesto los ingresos</div>
          <p class="texto-vacio">Sin ingresos no hay barra que repartir. Es un minuto.</p>
          <button type="button" class="boton-primario" @click="emit('ponerIngresos')">
            Poner ingresos de {{ nombreMes.split(' ')[0].toLowerCase() }}
          </button>
        </div>

        <template v-else>
          <p v-if="ritmo" class="marca-dia-texto" :style="{ left: `${ritmo.pct}%` }">
            {{ ritmo.texto }}
          </p>

          <div
            class="pista"
            :class="{ 'pista--tarjetas': modoTarjetas }"
            ref="pista"
            role="group"
            :aria-label="`Reparto por temáticas de ${nombreMes}`"
            :aria-describedby="props.mostrarCabecera && !props.anidada ? `${id}-resumen` : undefined"
            @keydown="alTeclado"
            @mouseleave="salir"
          >
            <div class="tramos">
              <div
                v-for="(t, i) in tramos"
                :key="t.clave"
                class="tramo"
                :class="[
                  `tramo--${t.tipo}`,
                  {
                    'tramo--sobrepasado': t.sobrepaso > 0,
                    'tramo--atenuado': indiceResaltado !== null && indiceResaltado !== i,
                    'tramo--resaltado': indiceResaltado === i,
                  },
                ]"
                :style="estiloTramo(t)"
                :ref="(el) => guardarReferencia(el as HTMLElement | null, i)"
                role="img"
                :aria-label="etiquetaTramo(t, i)"
                :tabindex="i === indiceActivo ? 0 : -1"
                @mouseenter="entrar(i)"
                @focus="indiceFoco = i"
                @blur="indiceFoco = null"
                @click="activarTramo(t)"
              >
                <span class="relleno" aria-hidden="true" />

                <!-- Modo tarjeta: con dos o tres temáticas cabe todo dentro. -->
                <span v-if="modoTarjetas" class="tarjeta-tramo" aria-hidden="true">
                  <span class="tarjeta-nombre">{{ t.nombre }}</span>
                  <span class="tarjeta-barra">
                    <span class="tarjeta-barra-relleno" />
                  </span>
                  <span class="tarjeta-cifras">
                    <template v-if="t.tipo === 'sin-asignar'">{{ euros(t.importe) }}</template>
                    <template v-else>
                      {{ euros(t.gastado) }} de {{ euros(t.importe + t.arrastrado) }}
                    </template>
                    <span class="tarjeta-pct">{{ porcentaje(t.anchoPct / 100) }}</span>
                  </span>
                </span>

                <span v-else-if="cabeEtiqueta(t)" class="etiqueta-interna" aria-hidden="true">
                  <span class="etiqueta-nombre">{{ t.nombre }}</span>
                  <span class="etiqueta-importe">{{ euros(t.importe, { decimales: false }) }}</span>
                </span>

                <TriangleAlert
                  v-if="t.sobrepaso > 0 && !modoTarjetas"
                  class="icono-exceso"
                  :size="12"
                  aria-hidden="true"
                />
              </div>
            </div>

            <!-- Capa de marcas: crestas de exceso, límite de ingresos, trama de
                 sobreasignación y marca del día. Nada de esto recibe puntero. -->
            <div class="marcas" aria-hidden="true">
              <span
                v-for="{ t, i } in excesosVisibles"
                :key="`cresta-${t.clave}`"
                class="cresta"
                :style="{
                  left: posicion(i),
                  width: `calc(${t.anchoPct}% * ${t.crestaPct / 100})`,
                }"
              />
              <span
                v-if="sobreasignacion"
                class="trama-de-mas"
                :style="{ left: `${sobreasignacion.desdePct}%` }"
              />
              <span
                v-if="limiteIngresos !== null"
                class="limite-ingresos"
                :style="{ left: `${limiteIngresos}%` }"
              />
              <span v-if="ritmo" class="marca-dia" :style="{ left: `${ritmo.pct}%` }" />
            </div>

            <!-- Tooltip: el valor manda, el nombre acompaña. Va oculto a los
                 lectores porque el `aria-label` del segmento ya lo cuenta. -->
            <div
              v-if="tramoTooltip && indiceTooltip !== null"
              class="tooltip"
              aria-hidden="true"
              :style="{ left: `${Math.min(Math.max(izquierdas[indiceTooltip] + tramoTooltip.anchoPct / 2, 12), 88)}%` }"
            >
              <p class="tooltip-valor">
                <template v-if="tramoTooltip.tipo === 'sin-asignar'">
                  {{ euros(tramoTooltip.importe) }}
                </template>
                <template v-else>
                  {{ euros(tramoTooltip.gastado) }}
                  <span class="tooltip-de">de {{ euros(tramoTooltip.importe + tramoTooltip.arrastrado) }}</span>
                </template>
              </p>
              <p class="tooltip-nombre">
                <span class="llave" :style="{ background: tramoTooltip.color }" />
                {{ tramoTooltip.nombre }}
              </p>
              <p v-if="tramoTooltip.tipo !== 'sin-asignar'" class="tooltip-linea">
                {{ porcentaje(tramoTooltip.consumidoPct / 100) }} de lo asignado
              </p>
              <p class="tooltip-linea">
                {{ porcentaje(tramoTooltip.anchoPct / 100) }} del presupuesto total
              </p>
              <p v-if="tramoTooltip.arrastrado !== 0" class="tooltip-linea">
                Incluye {{ euros(tramoTooltip.arrastrado) }} del mes anterior
              </p>
              <p v-if="ritmo" class="tooltip-linea">
                Quedan {{ euros(tramoTooltip.disponible) }} y {{ ritmo.diasRestantes }} días
              </p>
              <template v-if="textoRitmo(tramoTooltip)">
                <hr class="tooltip-regla" />
                <p class="tooltip-linea">{{ textoRitmo(tramoTooltip) }}</p>
              </template>
            </div>
          </div>

          <!-- Etiquetas de exceso bajo el carril: el importe del sobrepaso no
               puede vivir solo dentro de la barra. -->
          <div v-if="excesosVisibles.length > 0" class="excesos">
            <template v-if="excesosVisibles.length <= 2">
              <p
                v-for="{ t, i } in excesosVisibles"
                :key="`etiqueta-${t.clave}`"
                class="exceso-etiqueta"
                :style="{ left: posicion(i) }"
              >
                <span aria-hidden="true">▲</span>
                {{ euros(t.sobrepaso) }} de más
              </p>
            </template>
            <p v-else class="exceso-agregado">
              {{ excesosVisibles.length }} temáticas sobrepasadas ·
              {{ euros(totalSobrepasado) }} de más
            </p>
          </div>

          <p v-if="sobreasignacion" class="pie-de-mas">
            <span class="muestra-de-mas" aria-hidden="true" />
            De más: {{ euros(sobreasignacion.importe) }} por encima de los ingresos
          </p>

          <!-- Leyenda: gastado, asignado sin gastar y sin asignar. -->
          <ul v-if="props.mostrarLeyenda && !esMovil" class="clave" aria-hidden="true">
            <li><span class="muestra muestra--solida" />gastado</li>
            <li><span class="muestra muestra--tenue" />asignado sin gastar</li>
            <li><span class="muestra muestra--carril" />sin asignar</li>
          </ul>

          <!-- G. Ingresos sin repartir. -->
          <div v-if="sinRepartir" class="reparto-inicial">
            <p class="texto-vacio">
              Reparte tus ingresos entre temáticas para ver en qué se te va el mes.
            </p>
            <div class="acciones">
              <button type="button" class="boton-primario" @click="emit('repartir')">
                Repartir presupuesto
              </button>
              <button type="button" class="boton-secundario" @click="emit('copiarMesAnterior')">
                Usar el reparto del mes pasado
              </button>
            </div>
          </div>

          <!-- Avisos con su acción al lado, que es lo que uno quiere hacer justo
               después de leerlos. -->
          <div v-if="props.mostrarAvisos" class="avisos">
            <p v-if="cifras.sobrepasadas.length === 1" class="aviso aviso--negativo">
              <TriangleAlert :size="16" aria-hidden="true" />
              <span>
                {{ cifras.sobrepasadas[0].nombre }} sobrepasada en
                {{ euros(cifras.sobrepasadas[0].sobrepaso) }}
              </span>
              <span class="aviso-acciones">
                <button type="button" class="boton-secundario" @click="emit('reasignar', cifras.sobrepasadas[0])">
                  Reasignar
                </button>
                <button type="button" class="boton-secundario" @click="emit('activar', cifras.sobrepasadas[0])">
                  Ver movimientos
                </button>
              </span>
            </p>
            <p v-else-if="cifras.sobrepasadas.length > 1" class="aviso aviso--negativo">
              <TriangleAlert :size="16" aria-hidden="true" />
              <span>
                {{ cifras.sobrepasadas.length }} temáticas sobrepasadas ·
                {{ euros(totalSobrepasado) }} de más
              </span>
              <span class="aviso-acciones">
                <button type="button" class="boton-secundario" @click="emit('reasignar', null)">
                  Reasignar
                </button>
              </span>
            </p>
            <p v-if="cifras.sobreasignado" class="aviso aviso--aviso">
              <CircleAlert :size="16" aria-hidden="true" />
              <span>
                Has asignado {{ euros(-cifras.sinAsignar) }} más de lo que ingresas
              </span>
              <span class="aviso-acciones">
                <button type="button" class="boton-secundario" @click="emit('reasignar', null)">
                  Cambiar asignación
                </button>
              </span>
            </p>
            <p v-if="cifras.enRojo" class="aviso aviso--negativo">
              <TriangleAlert :size="16" aria-hidden="true" />
              <span>
                Este mes gastas {{ euros(cifras.gastado - cifras.ingresos) }} más de lo que ingresas
              </span>
            </p>
          </div>

          <!-- En móvil la leyenda se sustituye por la lista de barras compactas:
               un chip de 12 px no es un objetivo de toque. -->
          <ul v-if="esMovil && tramos.length > 0" class="lista-compacta">
            <li v-for="s in plegado.visibles" :key="s.categoria_id">
              <BarraCategoria
                :segmento="s"
                :dia-actual="ritmo?.dia"
                :dias-del-mes="ritmo?.diasDelMes"
                @activar="emit('activar', $event)"
                @asignar="emit('reasignar', $event)"
              />
            </li>
            <li v-if="tramoOtros">
              <button type="button" class="chip" @click="otrosAbierto = true">
                <span class="punto punto--cuadrado" :style="{ background: COLOR_OTROS }" aria-hidden="true" />
                {{ tramoOtros.nombre }}
                <span class="chip-importe">{{ euros(tramoOtros.importe) }}</span>
                <span class="chip-mas">Ver todas</span>
              </button>
            </li>
          </ul>

          <ul
            v-else-if="props.mostrarLeyenda && tramos.length > 0"
            class="leyenda"
            :aria-label="`Leyenda del presupuesto de ${nombreMes}`"
          >
            <li v-for="(t, i) in tramos" :key="`ley-${t.clave}`">
              <button
                type="button"
                class="chip"
                :class="{ 'chip--resaltado': indiceResaltado === i }"
                @mouseenter="entrar(i)"
                @mouseleave="salir"
                @focus="indiceFoco = i"
                @blur="indiceFoco = null"
                @click="activarTramo(t)"
              >
                <span
                  class="punto"
                  :class="{ 'punto--cuadrado': t.tipo !== 'categoria' }"
                  :style="{ background: t.color }"
                  aria-hidden="true"
                />
                <span class="chip-nombre">{{ t.nombre }}</span>
                <span v-if="t.tipo === 'sin-asignar' || t.tipo === 'en-rojo'" class="chip-importe">
                  {{ euros(t.importe) }}
                </span>
                <span v-else class="chip-importe">
                  {{ euros(t.gastado, { decimales: false }) }}/{{ euros(t.importe + t.arrastrado, { decimales: false }) }}
                </span>
                <span v-if="t.sobrepaso > 0 && t.tipo === 'categoria'" class="insignia">
                  <TriangleAlert :size="12" aria-hidden="true" />
                  Sobrepasado {{ euros(t.sobrepaso, { signoSiempre: true }) }}
                </span>
                <span v-if="t.tipo === 'otros'" class="chip-mas">Ver todas</span>
              </button>
            </li>
          </ul>
        </template>
      </template>

      <!-- Ninguna cifra vive solo dentro de un gráfico: la misma información,
           en tabla. -->
      <div v-if="tramos.length > 0" class="pie-tabla">
        <button
          type="button"
          class="boton-texto"
          :aria-expanded="tablaAbierta"
          :aria-controls="`${id}-tabla`"
          @click="tablaAbierta = !tablaAbierta"
        >
          <Table2 :size="16" aria-hidden="true" />
          {{ tablaAbierta ? 'Ocultar la tabla' : 'Ver como tabla' }}
        </button>
      </div>

      <div v-if="tablaAbierta" :id="`${id}-tabla`" class="envoltorio-tabla" tabindex="0">
        <table class="tabla">
          <caption class="solo-lectores">{{ titulo }}, reparto por temáticas</caption>
          <thead>
            <tr>
              <th scope="col">Temática</th>
              <th scope="col" class="numerica">Asignado</th>
              <th scope="col" class="numerica">Gastado</th>
              <th scope="col" class="numerica">Restante</th>
              <th scope="col" class="numerica">% del total</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in tramos" :key="`fila-${t.clave}`">
              <th scope="row" class="celda-nombre">
                <span class="punto" :style="{ background: t.color }" aria-hidden="true" />
                {{ t.nombre }}
              </th>
              <td class="numerica">{{ euros(t.importe + t.arrastrado) }}</td>
              <td class="numerica">{{ euros(t.gastado) }}</td>
              <td class="numerica" :class="{ 'texto-negativo': t.disponible < 0 }">
                {{ euros(t.disponible) }}
              </td>
              <td class="numerica">{{ porcentaje(t.anchoPct / 100) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <p class="solo-lectores" aria-live="polite">{{ anuncio }}</p>
    </template>
  </section>
</template>

<style scoped>
.tarjeta {
  --alto-carril: 44px;
  --min-tramo: 24px;
  --cresta: 6px;
  --radio-carril: 8px;
  --dur: var(--dur-fast, 120ms);

  position: relative;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 20px;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-xl, 16px);
  color: var(--c-text-1);
  font-family: var(--font-sans, system-ui, sans-serif);
}

@media (max-width: 1023px) {
  .tarjeta {
    --alto-carril: 40px;
    --min-tramo: 20px;
  }
}

@media (max-width: 639px) {
  .tarjeta {
    --alto-carril: 28px;
    --min-tramo: 8px;
    --cresta: 4px;
    --radio-carril: 6px;
    padding: 16px;
  }
}

.tarjeta--anidada {
  padding: 0;
  border: 0;
  background: none;
}

/* El único momento en que la barra alza la voz. */
.tarjeta--rojo {
  border-color: var(--c-negative);
  box-shadow: 0 0 0 3px var(--c-negative-wash);
}

.cabecera {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.titulo {
  margin: 0;
  font-size: var(--t-h2, 1.25rem);
  font-weight: 600;
  line-height: 1.3;
}

.cifra-heroe {
  margin: 4px 0 0;
  font-size: var(--t-hero, 2.5rem);
  font-weight: 600;
  line-height: 1.05;
  font-variant-numeric: tabular-nums;
}

.linea-cifras {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 6px 0 0;
  color: var(--c-text-2);
  font-size: var(--t-sm, 0.875rem);
  font-variant-numeric: tabular-nums;
}

.etiqueta-ingresos {
  margin: 0;
  color: var(--c-text-3);
  font-size: var(--t-sm, 0.875rem);
  white-space: nowrap;
}

/* Sobreasignar es un plan arriesgado, no un error consumado: ámbar, no rojo. */
.alerta-suave {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--c-warning);
  font-weight: 600;
}

.alerta-fuerte {
  color: var(--c-negative);
  font-weight: 600;
}

/* --- Carril ------------------------------------------------------- */

.marca-dia-texto {
  position: relative;
  margin: 0 0 -4px;
  padding-left: 6px;
  color: var(--c-text-3);
  font-size: var(--t-micro, 0.75rem);
  white-space: nowrap;
  transform: translateX(-50%);
  width: max-content;
}

.pista {
  position: relative;
  height: var(--alto-carril);
  margin-top: var(--cresta);
  background: var(--c-surface);
}

.pista--tarjetas {
  height: 56px;
}

.tramos {
  display: flex;
  height: 100%;
}

.tramo {
  position: relative;
  box-sizing: border-box;
  min-width: var(--min-tramo);
  height: 100%;
  /* El hueco entre segmentos, del color de la superficie. */
  border-right: 2px solid var(--c-surface);
  overflow: hidden;
  background: color-mix(in oklab, var(--color-tramo) 22%, var(--c-track));
  cursor: pointer;
  transition:
    opacity var(--dur) ease-out,
    filter var(--dur) ease-out;
}

.tramo:first-child {
  border-radius: var(--radio-carril) 0 0 var(--radio-carril);
}

.tramo:last-child {
  border-right: 0;
  border-radius: 0 var(--radio-carril) var(--radio-carril) 0;
}

.tramo:only-child {
  border-radius: var(--radio-carril);
}

.tramo:focus-visible {
  /* Hacia dentro, para no tapar a los vecinos. */
  outline: 2px solid var(--c-accent);
  outline-offset: -2px;
}

.relleno {
  position: absolute;
  inset: 0 auto 0 0;
  width: var(--llenado);
  background: var(--color-tramo);
}

.tramo--atenuado {
  opacity: 0.72;
}

.tramo--resaltado {
  filter: brightness(1.08);
}

.tramo--sin-asignar {
  background: var(--c-track);
  box-shadow: inset 0 0 0 1px var(--c-border-strong);
}

.tramo--otros {
  background: color-mix(in oklab, var(--c-cat-other) 22%, var(--c-track));
}

.tramo--sobrepasado {
  border-top: 2px solid var(--c-negative);
}

.tramo--en-rojo {
  background-color: var(--c-negative-wash);
  background-image: repeating-linear-gradient(45deg, var(--c-negative) 0 3px, transparent 3px 7px);
}

.tramo--en-rojo .relleno {
  display: none;
}

.etiqueta-interna {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 8px;
  color: var(--c-text-1);
  font-size: var(--t-caption, 0.8125rem);
  font-weight: 500;
  text-shadow: 0 1px 2px color-mix(in oklab, var(--c-app-bg) 60%, transparent);
  pointer-events: none;
}

.etiqueta-nombre {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.etiqueta-importe {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.icono-exceso {
  position: absolute;
  top: 4px;
  right: 2px;
  color: var(--c-negative);
}

/* Modo tarjeta con dos o tres temáticas. */
.tarjeta-tramo {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  padding: 6px 10px;
  pointer-events: none;
}

.pista--tarjetas .tramo {
  background: var(--c-track);
}

.pista--tarjetas .relleno {
  display: none;
}

.tarjeta-nombre {
  font-size: var(--t-caption, 0.8125rem);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tarjeta-barra {
  display: block;
  height: 8px;
  border-radius: var(--r-bar, 4px);
  background: color-mix(in oklab, var(--color-tramo) 22%, var(--c-track));
}

.tarjeta-barra-relleno {
  display: block;
  width: var(--llenado);
  height: 100%;
  border-radius: var(--r-bar, 4px);
  background: var(--color-tramo);
}

.tarjeta-cifras {
  display: flex;
  gap: 8px;
  color: var(--c-text-2);
  font-size: var(--t-micro, 0.75rem);
  font-variant-numeric: tabular-nums;
}

.tarjeta-pct {
  margin-left: auto;
}

/* --- Capa de marcas ---------------------------------------------- */

.marcas {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.cresta {
  position: absolute;
  top: calc(-1 * var(--cresta));
  height: var(--cresta);
  background-color: var(--c-negative);
  background-image: repeating-linear-gradient(
    45deg,
    color-mix(in oklab, var(--c-app-bg) 45%, transparent) 0 2px,
    transparent 2px 5px
  );
  border-radius: 2px 2px 0 0;
}

/* La sobreasignación se pinta encima, no como tramo aparte: cada euro repartido
   ya pertenece a una temática y contarlo dos veces sería mentir. */
.trama-de-mas {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  background-image: repeating-linear-gradient(45deg, var(--c-warning) 0 2px, transparent 2px 7px);
}

.limite-ingresos {
  position: absolute;
  top: calc(-1 * var(--cresta));
  bottom: -4px;
  width: 1px;
  border-left: 1px dotted var(--c-text-1);
}

.marca-dia {
  position: absolute;
  top: -2px;
  bottom: -2px;
  width: 2px;
  background: var(--c-text-3);
}

/* --- Tooltip ------------------------------------------------------ */

.tooltip {
  position: absolute;
  bottom: calc(100% + 10px);
  z-index: 20;
  min-width: 200px;
  max-width: 260px;
  padding: 12px;
  background: var(--c-surface-2);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg, 12px);
  transform: translateX(-50%);
  pointer-events: none;
}

.tooltip-valor {
  margin: 0;
  font-size: var(--t-h3, 1.125rem);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.tooltip-de {
  color: var(--c-text-2);
  font-weight: 500;
}

.tooltip-nombre {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0 6px;
  color: var(--c-text-2);
  font-size: var(--t-sm, 0.875rem);
}

.llave {
  width: 12px;
  height: 3px;
  border-radius: 2px;
}

.tooltip-linea {
  margin: 2px 0;
  color: var(--c-text-2);
  font-size: var(--t-caption, 0.8125rem);
  font-variant-numeric: tabular-nums;
}

.tooltip-regla {
  height: 1px;
  margin: 8px 0;
  border: 0;
  background: var(--c-border);
}

/* --- Excesos y pies ---------------------------------------------- */

.excesos {
  position: relative;
  min-height: 1.25rem;
}

.exceso-etiqueta {
  position: absolute;
  top: 0;
  margin: 0;
  color: var(--c-negative);
  font-size: var(--t-micro, 0.75rem);
  font-weight: 600;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.exceso-agregado {
  margin: 0;
  color: var(--c-negative);
  font-size: var(--t-micro, 0.75rem);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.pie-de-mas {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--c-warning);
  font-size: var(--t-caption, 0.8125rem);
  font-variant-numeric: tabular-nums;
}

.muestra-de-mas {
  width: 16px;
  height: 10px;
  border-radius: 2px;
  background-image: repeating-linear-gradient(45deg, var(--c-warning) 0 2px, transparent 2px 6px);
}

.clave {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--c-text-3);
  font-size: var(--t-micro, 0.75rem);
}

.clave li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.muestra {
  width: 14px;
  height: 8px;
  border-radius: 2px;
}

.muestra--solida {
  background: var(--c-cat-1);
}

.muestra--tenue {
  background: color-mix(in oklab, var(--c-cat-1) 22%, var(--c-track));
}

.muestra--carril {
  background: var(--c-track);
  box-shadow: inset 0 0 0 1px var(--c-border-strong);
}

/* --- Leyenda ------------------------------------------------------ */

.leyenda,
.lista-compacta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.lista-compacta {
  flex-direction: column;
  gap: 0;
}

.lista-compacta > li {
  border-bottom: 1px solid var(--c-border-soft);
}

.lista-compacta > li:last-child {
  border-bottom: 0;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  padding: 0 8px;
  border: 0;
  border-radius: var(--r-md, 8px);
  background: none;
  color: var(--c-text-2);
  font: inherit;
  font-size: var(--t-caption, 0.8125rem);
  cursor: pointer;
}

.chip:hover,
.chip--resaltado {
  background: var(--c-surface-3);
  color: var(--c-text-1);
}

.chip:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

.chip-nombre {
  max-width: 14ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-importe {
  color: var(--c-text-1);
  font-variant-numeric: tabular-nums;
}

.chip-mas {
  color: var(--c-accent-text);
  font-weight: 600;
}

.punto {
  flex: 0 0 auto;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.punto--cuadrado {
  border-radius: 2px;
}

.insignia {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border-radius: var(--r-full, 999px);
  background: var(--c-negative-wash);
  color: var(--c-negative);
  font-size: var(--t-micro, 0.75rem);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* --- Estados vacíos ---------------------------------------------- */

.vacio,
.reparto-inicial {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* El único borde discontinuo de todo el sistema: significa «esto está por
   rellenar». */
.carril-vacio {
  display: grid;
  place-items: center;
  height: var(--alto-carril);
  border: 1px dashed var(--c-border-strong);
  border-radius: var(--radio-carril);
  color: var(--c-text-3);
  font-size: var(--t-sm, 0.875rem);
}

.texto-vacio {
  margin: 0;
  color: var(--c-text-2);
  font-size: var(--t-sm, 0.875rem);
}

.acciones {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.boton-primario,
.boton-secundario,
.boton-texto,
.boton-volver {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 44px;
  padding: 0 16px;
  border-radius: var(--r-md, 10px);
  font: inherit;
  font-size: var(--t-sm, 0.875rem);
  font-weight: 600;
  cursor: pointer;
}

.boton-primario {
  border: 0;
  background: var(--c-accent);
  color: var(--c-text-on-fill);
}

.boton-primario:hover {
  background: var(--c-accent-hover);
}

.boton-secundario,
.boton-volver {
  border: 1px solid var(--c-border);
  background: transparent;
  color: var(--c-text-1);
}

.boton-secundario:hover,
.boton-volver:hover {
  background: var(--c-surface-3);
}

.boton-texto {
  border: 0;
  padding: 0 8px;
  background: none;
  color: var(--c-accent-text);
}

.boton-primario:focus-visible,
.boton-secundario:focus-visible,
.boton-texto:focus-visible,
.boton-volver:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

/* --- Avisos ------------------------------------------------------- */

.avisos {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.avisos:empty {
  display: none;
}

.aviso {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--r-lg, 12px);
  font-size: var(--t-sm, 0.875rem);
  font-variant-numeric: tabular-nums;
}

.aviso--negativo {
  background: var(--c-negative-wash);
  color: var(--c-negative);
}

.aviso--aviso {
  background: var(--c-warning-wash);
  color: var(--c-warning);
}

.aviso-acciones {
  display: inline-flex;
  gap: 8px;
  margin-left: auto;
}

.aviso .boton-secundario {
  min-height: 36px;
  color: inherit;
  border-color: currentcolor;
}

/* --- Miga y tabla ------------------------------------------------- */

.miga {
  display: flex;
  align-items: center;
  gap: 12px;
}

.miga-texto {
  color: var(--c-text-2);
  font-size: var(--t-sm, 0.875rem);
}

.pie-tabla {
  display: flex;
}

.envoltorio-tabla {
  overflow-x: auto;
  scroll-margin-top: 80px;
}

.envoltorio-tabla:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

.tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-sm, 0.875rem);
}

.tabla th,
.tabla td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--c-border-soft);
  white-space: nowrap;
}

.tabla thead th {
  color: var(--c-text-3);
  font-weight: 500;
}

.celda-nombre {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

.numerica {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.texto-negativo {
  color: var(--c-negative);
  font-weight: 600;
}

/* --- Esqueleto ---------------------------------------------------- */

.esqueleto {
  border-radius: var(--r-md, 8px);
  background: linear-gradient(
    90deg,
    var(--c-surface-3) 0%,
    var(--c-surface-2) 50%,
    var(--c-surface-3) 100%
  );
}

.esqueleto--titulo {
  width: 40%;
  height: 20px;
}

.esqueleto--cifra {
  width: 55%;
  height: 40px;
}

.esqueleto--carril {
  height: var(--alto-carril);
  border-radius: var(--radio-carril);
}

.esqueleto--leyenda {
  width: 70%;
  height: 16px;
}

.solo-lectores {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}

@media (prefers-reduced-motion: reduce) {
  .tramo {
    transition: none;
  }
}

/* Con más contraste, o cuando el sistema fuerza los colores, el patrón pasa a
   ser el canal principal. */
@media (prefers-contrast: more) {
  .tramo {
    box-shadow: inset 0 0 0 1px var(--c-border-strong);
  }

  .relleno {
    background-image: repeating-linear-gradient(
      135deg,
      color-mix(in oklab, var(--c-app-bg) 30%, transparent) 0 2px,
      transparent 2px 6px
    );
  }
}
</style>
