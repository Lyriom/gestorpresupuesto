<script setup lang="ts">
/**
 * Página de demostración de la BudgetBar y de los gráficos, sin backend.
 *
 * Recorre todos los estados de la sección 6 del sistema de diseño para poder
 * revisarlos de un vistazo: mes vacío, sin ingresos, dos temáticas, quince,
 * sobreasignado, con sobrepasos, con arrastre y cargando.
 *
 * `crearBarra` reproduce el cálculo de `services/presupuesto.py` (estados,
 * porcentajes, orden y avisos) para que los datos de ejemplo sean exactamente
 * de la forma que llega de la API, incluidos los importes como cadena decimal.
 * Los avisos aquí se escriben con `euros()`; el backend interpola el Decimal en
 * bruto, así que en producción se verán con punto decimal hasta que se arregle
 * allí.
 */
import { computed, ref, watch } from 'vue'

import { euros, periodoDe } from '@/lib/formato'
import BarraPresupuesto from './BarraPresupuesto.vue'
import BarraCategoria from './BarraCategoria.vue'
import ResumenPresupuesto from './ResumenPresupuesto.vue'
import type { BarraPresupuesto as DatosBarra, EstadoSegmento, SegmentoBarra } from './types'
import GraficoLineas from '@/components/graficos/GraficoLineas.vue'
import GraficoBarras from '@/components/graficos/GraficoBarras.vue'
import GraficoDonut from '@/components/graficos/GraficoDonut.vue'
import GraficoAreaCashFlow from '@/components/graficos/GraficoAreaCashFlow.vue'

interface EntradaDemo {
  nombre: string
  asignado: number
  gastado: number
  arrastrado?: number
  ranura?: number
}

const PERIODO = periodoDe(new Date(2026, 7, 1))

function dos(valor: number): string {
  return (Math.round(valor * 100) / 100).toFixed(2)
}

function estadoDe(efectivo: number, gastado: number, disponible: number): EstadoSegmento {
  if (efectivo === 0) return gastado > 0 ? 'sin_asignar' : 'sin_gasto'
  if (gastado === 0) return 'sin_gasto'
  if (disponible < 0) return 'sobrepasado'
  if (disponible === 0) return 'agotado'
  return gastado / efectivo >= 0.8 ? 'ajustado' : 'en_margen'
}

function crearBarra(ingresos: number, entradas: EntradaDemo[], periodo = PERIODO): DatosBarra {
  const totalAsignado = entradas.reduce((t, e) => t + e.asignado, 0)
  const totalGastado = entradas.reduce((t, e) => t + e.gastado, 0)
  const totalArrastrado = entradas.reduce((t, e) => t + (e.arrastrado ?? 0), 0)
  const base = Math.max(ingresos, totalAsignado)

  const segmentos: SegmentoBarra[] = entradas.map((e, i) => {
    const arrastrado = e.arrastrado ?? 0
    const efectivo = e.asignado + arrastrado
    const disponible = efectivo - e.gastado
    return {
      categoria_id: `cat-${i + 1}-${e.nombre.toLowerCase().replace(/\s+/g, '-')}`,
      nombre: e.nombre,
      color: String(e.ranura ?? (i % 12) + 1),
      icono: null,
      categoria_padre_id: null,
      asignado: dos(e.asignado),
      gastado: dos(e.gastado),
      arrastrado: dos(arrastrado),
      disponible: dos(disponible),
      porcentaje_consumido: dos(efectivo > 0 ? (e.gastado / efectivo) * 100 : 0),
      porcentaje_de_la_barra: dos(base > 0 ? (e.asignado / base) * 100 : 0),
      estado: estadoDe(efectivo, e.gastado, disponible),
      sobrepaso: dos(disponible < 0 ? -disponible : 0),
    }
  })

  segmentos.sort((a, b) => Number(b.asignado) - Number(a.asignado) || a.nombre.localeCompare(b.nombre, 'es'))

  const sinAsignar = ingresos - totalAsignado
  const avisos: string[] = []
  if (ingresos === 0) {
    avisos.push(
      'No has registrado ingresos este mes: añade tu nómina o ingresos para poder repartir el presupuesto.',
    )
  } else if (sinAsignar < 0) {
    avisos.push(`Has repartido ${euros(-sinAsignar)} más de lo que has ingresado este mes.`)
  }

  const sobrepasadas = segmentos.filter((s) => s.estado === 'sobrepasado')
  if (sobrepasadas.length === 1) {
    avisos.push(`Te has pasado ${euros(sobrepasadas[0].sobrepaso)} en ${sobrepasadas[0].nombre}.`)
  } else if (sobrepasadas.length > 1) {
    const total = sobrepasadas.reduce((t, s) => t + Number(s.sobrepaso), 0)
    avisos.push(
      `Te has pasado del presupuesto en ${sobrepasadas.length} temáticas (${euros(total)} en total).`,
    )
  }

  const sinPresupuesto = segmentos.filter((s) => s.estado === 'sin_asignar')
  if (sinPresupuesto.length > 0) {
    const nombres = sinPresupuesto.slice(0, 3).map((s) => s.nombre).join(', ')
    const resto = sinPresupuesto.length <= 3 ? '' : ` y ${sinPresupuesto.length - 3} más`
    avisos.push(`Hay gasto sin presupuesto asignado en: ${nombres}${resto}.`)
  }

  return {
    periodo,
    ingresos: dos(ingresos),
    total_asignado: dos(totalAsignado),
    total_gastado: dos(totalGastado),
    total_arrastrado: dos(totalArrastrado),
    sin_asignar: dos(sinAsignar),
    disponible: dos(ingresos + totalArrastrado - totalGastado),
    porcentaje_asignado: dos(ingresos > 0 ? (totalAsignado / ingresos) * 100 : 0),
    porcentaje_gastado: dos(base > 0 ? (totalGastado / base) * 100 : 0),
    segmentos,
    avisos,
  }
}

/* ------------------------------------------------------------------ *
 * Escenarios
 * ------------------------------------------------------------------ */

const SANO: EntradaDemo[] = [
  { nombre: 'Vivienda', asignado: 850, gastado: 612 },
  { nombre: 'Alimentación', asignado: 520, gastado: 385 },
  { nombre: 'Ocio', asignado: 300, gastado: 142 },
  { nombre: 'Salud', asignado: 300, gastado: 55 },
  { nombre: 'Transporte', asignado: 180, gastado: 118 },
]

const QUINCE: EntradaDemo[] = [
  { nombre: 'Vivienda', asignado: 850, gastado: 612 },
  { nombre: 'Alimentación', asignado: 520, gastado: 498 },
  { nombre: 'Ocio', asignado: 300, gastado: 142 },
  { nombre: 'Transporte', asignado: 180, gastado: 118 },
  { nombre: 'Salud', asignado: 120, gastado: 40 },
  { nombre: 'Suscripciones', asignado: 95, gastado: 95 },
  { nombre: 'Ropa', asignado: 80, gastado: 12 },
  { nombre: 'Educación', asignado: 60, gastado: 60 },
  { nombre: 'Mascotas', asignado: 45, gastado: 38 },
  { nombre: 'Regalos', asignado: 35, gastado: 0 },
  { nombre: 'Cuidado personal', asignado: 30, gastado: 21 },
  { nombre: 'Impuestos', asignado: 25, gastado: 25 },
  { nombre: 'Libros', asignado: 20, gastado: 34 },
  { nombre: 'Café', asignado: 15, gastado: 14 },
  { nombre: 'Donaciones', asignado: 10, gastado: 10 },
]

const escenarios = computed(() => [
  {
    id: 'sano',
    titulo: 'A · Estado sano',
    nota: 'Cinco temáticas, parte gastada, cola sin asignar y marca del día del mes.',
    barra: crearBarra(2450, SANO),
    conResumen: true,
  },
  {
    id: 'sobrepaso',
    titulo: 'B · Una temática sobrepasada',
    nota: 'Cuatro canales para el exceso: color, borde superior, cresta rayada e icono con texto.',
    barra: crearBarra(2450, [
      { nombre: 'Vivienda', asignado: 850, gastado: 612 },
      { nombre: 'Alimentación', asignado: 520, gastado: 588.4 },
      { nombre: 'Ocio', asignado: 300, gastado: 210 },
      { nombre: 'Transporte', asignado: 180, gastado: 118 },
    ]),
    conResumen: true,
  },
  {
    id: 'sobrepasos',
    titulo: 'B bis · Varias sobrepasadas, una diminuta',
    nota: 'Una temática sobrepasada nunca se plega, aunque no llegue al 3 % del carril.',
    barra: crearBarra(2450, [
      { nombre: 'Vivienda', asignado: 850, gastado: 902 },
      { nombre: 'Alimentación', asignado: 520, gastado: 588.4 },
      { nombre: 'Ocio', asignado: 300, gastado: 140 },
      { nombre: 'Café', asignado: 15, gastado: 41.2 },
    ]),
  },
  {
    id: 'sobreasignado',
    titulo: 'C · Sobreasignación',
    nota: 'Asignado 2.700 € de 2.450 €: la barra se comprime, aparece la trama ámbar «de más» y la línea del límite de ingresos.',
    barra: crearBarra(2450, [
      { nombre: 'Vivienda', asignado: 900, gastado: 640 },
      { nombre: 'Alimentación', asignado: 600, gastado: 410 },
      { nombre: 'Ahorro', asignado: 700, gastado: 0 },
      { nombre: 'Ocio', asignado: 320, gastado: 180 },
      { nombre: 'Transporte', asignado: 180, gastado: 118 },
    ]),
    conResumen: true,
  },
  {
    id: 'en-rojo',
    titulo: 'D · Gasto por encima de los ingresos',
    nota: 'Cola roja rayada y borde de la tarjeta en negativo. Es el único momento en que la barra alza la voz.',
    barra: crearBarra(2450, [
      { nombre: 'Vivienda', asignado: 900, gastado: 900 },
      { nombre: 'Alimentación', asignado: 600, gastado: 700 },
      { nombre: 'Suscripciones', asignado: 550, gastado: 700 },
      { nombre: 'Ocio', asignado: 250, gastado: 312 },
      { nombre: 'Transporte', asignado: 150, gastado: 150 },
    ]),
  },
  {
    id: 'dos',
    titulo: 'E · Solo dos temáticas',
    nota: 'Carril de 56 px con nombre, importe y porcentaje del total dentro del propio segmento.',
    barra: crearBarra(2450, [
      { nombre: 'Vivienda', asignado: 1400, gastado: 980 },
      { nombre: 'Todo lo demás', asignado: 1050, gastado: 310 },
    ]),
  },
  {
    id: 'quince',
    titulo: 'F · Quince temáticas',
    nota: 'Plegado determinista a ocho más «Otros»; «Otros» abre una barra anidada en el sitio.',
    barra: crearBarra(2450, QUINCE),
  },
  {
    id: 'arrastre',
    titulo: 'Con arrastre del mes anterior',
    nota: 'El presupuesto efectivo incluye lo arrastrado, y el tooltip lo dice.',
    barra: crearBarra(2450, [
      { nombre: 'Vivienda', asignado: 850, gastado: 612 },
      { nombre: 'Vacaciones', asignado: 200, gastado: 90, arrastrado: 430 },
      { nombre: 'Alimentación', asignado: 520, gastado: 402 },
      { nombre: 'Ocio', asignado: 300, gastado: 305 },
    ]),
    conResumen: true,
  },
  {
    id: 'vacio',
    titulo: 'G · Mes vacío, ingresos sin repartir',
    nota: 'El carril entero es «sin asignar» y aparecen las dos acciones de arranque.',
    barra: crearBarra(2450, []),
  },
  {
    id: 'sin-ingresos',
    titulo: 'H · Sin ingresos declarados',
    nota: 'Carril con el único borde discontinuo de todo el sistema.',
    barra: crearBarra(0, []),
    conResumen: true,
  },
  {
    id: 'gasto-sin-presupuesto',
    titulo: 'H bis · Gasto sin presupuesto ni ingresos',
    nota: 'Sin barra que repartir, pero el gasto no se esconde: sale en la lista compacta y en los avisos.',
    barra: crearBarra(0, [
      { nombre: 'Alimentación', asignado: 0, gastado: 210.4 },
      { nombre: 'Transporte', asignado: 0, gastado: 42 },
    ]),
  },
])

const cargando = ref(false)

/* ------------------------------------------------------------------ *
 * Datos de los gráficos
 * ------------------------------------------------------------------ */

const meses = ['mar', 'abr', 'may', 'jun', 'jul', 'ago']
const gastoPorMes = [2180, 2360, 2090, 2410, 2280, 1312.45]
const gastoAnterior = [2050, 2210, 2280, 2190, 2320, 2260]

const precioAceite = [4.29, 4.29, 4.65, 4.65, 4.89, 5.19]

const nombresTematica = SANO.map((e) => e.nombre)
const gastoPorTematica = SANO.map((e) => e.gastado)
const coloresTematica = SANO.map((_, i) => String((i % 12) + 1))

const comercios = ['Mercadona', 'Lidl', 'Alcampo', 'Carrefour', 'Aldi']
const cestaPorComercio = [42.35, 39.8, 44.1, 45.6, 38.95]

const cashFlow = meses.map((etiqueta, i) => ({
  etiqueta,
  ingresos: 2450,
  gastos: gastoPorMes[i],
}))

const reparto = SANO.map((e, i) => ({
  nombre: e.nombre,
  valor: e.asignado,
  color: String((i % 12) + 1),
}))

/* ------------------------------------------------------------------ *
 * Tema
 * ------------------------------------------------------------------ */

const temaClaro = ref(false)

// El tema real se marca en el <html>, que es como lo hace la aplicación; la
// demostración además lleva sus propios tokens para poder verse suelta.
watch(temaClaro, (claro) => {
  document.documentElement.dataset.theme = claro ? 'light' : 'dark'
})

function registrar(nombre: string, valor: unknown): void {
  // eslint-disable-next-line no-console
  console.log(`[demo] ${nombre}`, valor)
}
</script>

<template>
  <div class="demo" :data-tema="temaClaro ? 'claro' : 'oscuro'">
    <header class="demo-cabecera">
      <div>
        <h1>BudgetBar · estados</h1>
        <p class="demo-nota">
          Datos de ejemplo con la forma exacta de la API: importes como cadena decimal, porcentajes
          de 0 a 100 y avisos ya redactados.
        </p>
      </div>
      <div class="demo-controles">
        <label class="interruptor">
          <input v-model="temaClaro" type="checkbox" />
          Tema claro
        </label>
        <label class="interruptor">
          <input v-model="cargando" type="checkbox" />
          Cargando
        </label>
      </div>
    </header>

    <section class="bloque">
      <h2>Cargando</h2>
      <p class="demo-nota">Un solo bloque a la altura real del carril, nunca segmentos falsos.</p>
      <BarraPresupuesto :barra="null" cargando />
    </section>

    <section v-for="e in escenarios" :key="e.id" class="bloque">
      <h2>{{ e.titulo }}</h2>
      <p class="demo-nota">{{ e.nota }}</p>
      <BarraPresupuesto
        :barra="e.barra"
        :cargando="cargando"
        @activar="registrar('activar', $event.nombre)"
        @reasignar="registrar('reasignar', $event?.nombre ?? 'todas')"
        @repartir="registrar('repartir', null)"
        @copiar-mes-anterior="registrar('copiarMesAnterior', null)"
        @poner-ingresos="registrar('ponerIngresos', null)"
      />
      <ResumenPresupuesto v-if="e.conResumen" :barra="e.barra" class="separado" />
    </section>

    <section class="bloque">
      <h2>Versión compacta por temática</h2>
      <p class="demo-nota">
        Fila de 48 px, carril de 8 px, muesca del día y sobrepaso que continúa más allá del 100 %
        hasta un tope visual del 130 %.
      </p>
      <ul class="lista">
        <li v-for="s in escenarios[7].barra.segmentos" :key="s.categoria_id">
          <BarraCategoria
            :segmento="s"
            :dia-actual="13"
            :dias-del-mes="31"
            @activar="registrar('fila activar', $event.nombre)"
            @asignar="registrar('fila asignar', $event.nombre)"
          />
        </li>
        <li v-for="s in escenarios[10].barra.segmentos" :key="`sin-${s.categoria_id}`">
          <BarraCategoria
            :segmento="s"
            :dia-actual="13"
            :dias-del-mes="31"
            @asignar="registrar('fila asignar', $event.nombre)"
          />
        </li>
      </ul>
    </section>

    <section class="bloque">
      <h2>Gráficos</h2>
      <div class="rejilla-graficos">
        <GraficoLineas
          titulo="Gasto mes a mes"
          subtitulo="Este año frente al anterior"
          columna-etiquetas="Mes"
          :etiquetas="meses"
          :series="[
            { nombre: '2026', datos: gastoPorMes, color: 'cat-1', area: true },
            { nombre: '2025', datos: gastoAnterior, contexto: true },
          ]"
        />
        <GraficoLineas
          titulo="Aceite de oliva 1 l"
          subtitulo="Precio por unidad en cada compra"
          columna-etiquetas="Mes"
          :etiquetas="meses"
          :series="[{ nombre: 'Precio', datos: precioAceite, color: 'cat-1', escalonada: true }]"
          unidad="l"
        />
        <GraficoBarras
          titulo="¿En qué se me va el dinero?"
          subtitulo="Gasto del mes por temática"
          :etiquetas="nombresTematica"
          :series="[{ nombre: 'Gastado', datos: gastoPorTematica }]"
          :colores-etiquetas="coloresTematica"
          colorear="categorico"
        />
        <GraficoBarras
          titulo="Dónde compro más barato"
          subtitulo="La misma cesta en cinco comercios"
          columna-etiquetas="Comercio"
          :etiquetas="comercios"
          :series="[{ nombre: 'Cesta', datos: cestaPorComercio }]"
        />
        <GraficoDonut
          titulo="Reparto del mes"
          subtitulo="Máximo cinco porciones más «Otros»"
          :porciones="reparto"
        />
        <GraficoAreaCashFlow
          titulo="¿Entra más de lo que sale?"
          subtitulo="Ingresos, gastos y saldo acumulado"
          :puntos="cashFlow"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
/* Tokens del sistema de diseño (sección 2.1 del documento) aplicados al
   contenedor de la demostración: así esta página se ve bien suelta, sin
   depender de la hoja global de la aplicación, y se puede comparar el tema
   oscuro con el claro en el mismo sitio. */
.demo {
  color-scheme: dark;

  --c-app-bg: #0e1116;
  --c-surface: #151a21;
  --c-surface-2: #1c222b;
  --c-surface-3: #232b36;
  --c-surface-sunken: #0a0d12;
  --c-border: #2a323d;
  --c-border-strong: #3a4552;
  --c-border-soft: #1e2530;

  --c-text-1: #f2f5f9;
  --c-text-2: #a7b2c0;
  --c-text-3: #7e8a99;
  --c-text-disabled: #5a6472;
  --c-text-on-fill: #0a0e14;

  --c-accent: #4e7fff;
  --c-accent-hover: #6b92ff;
  --c-accent-text: #7099ff;

  --c-positive: #3fbf6f;
  --c-negative: #f2555a;
  --c-warning: #e3a008;
  --c-info: #3fb6e8;
  --c-positive-wash: color-mix(in oklab, #3fbf6f 16%, transparent);
  --c-negative-wash: color-mix(in oklab, #f2555a 16%, transparent);
  --c-warning-wash: color-mix(in oklab, #e3a008 16%, transparent);
  --c-info-wash: color-mix(in oklab, #3fb6e8 16%, transparent);

  --c-grid: #232a34;
  --c-axis: #38414d;
  --c-axis-text: #7e8a99;
  --c-track: #1e2530;
  --c-deemphasis: #4a5462;

  --c-cat-1: #568ef9;
  --c-cat-2: #c2520b;
  --c-cat-3: #02a6ad;
  --c-cat-4: #ce3344;
  --c-cat-5: #3fac4a;
  --c-cat-6: #b343ad;
  --c-cat-7: #ac9008;
  --c-cat-8: #6f5ddf;
  --c-cat-9: #20a888;
  --c-cat-10: #9d6000;
  --c-cat-11: #d36c9d;
  --c-cat-12: #026fb9;
  --c-cat-other: #4a5462;

  --c-seq-300: #2552aa;
  --c-seq-400: #3368d0;
  --c-seq-500: #4680f1;
  --c-seq-600: #679cff;
  --c-seq-700: #91b7fe;

  --c-div-warm-3: #e8b14a;
  --c-div-warm-2: #c08a2a;
  --c-div-warm-1: #8a6014;
  --c-div-neutral: #39414d;
  --c-div-cool-1: #2c5a8e;
  --c-div-cool-2: #4a82c8;
  --c-div-cool-3: #8fb6f0;

  --font-sans: 'InterVariable', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto,
    'Helvetica Neue', Arial, sans-serif;

  min-height: 100vh;
  padding: 24px;
  background: var(--c-app-bg);
  color: var(--c-text-1);
  font-family: var(--font-sans);
}

.demo[data-tema='claro'] {
  color-scheme: light;

  --c-app-bg: #f2f5f8;
  --c-surface: #ffffff;
  --c-surface-2: #ffffff;
  --c-surface-3: #f7f9fb;
  --c-surface-sunken: #edf1f5;
  --c-border: #d5dde7;
  --c-border-strong: #b9c4d2;
  --c-border-soft: #e6ebf1;

  --c-text-1: #0f1419;
  --c-text-2: #4c5867;
  --c-text-3: #5e6b7e;
  --c-text-disabled: #9aa5b4;
  --c-text-on-fill: #ffffff;

  --c-accent: #2c5fe0;
  --c-accent-hover: #2451c7;
  --c-accent-text: #2c5fe0;

  --c-positive: #11803d;
  --c-negative: #c4283a;
  --c-warning: #8a5a00;
  --c-info: #0b6c9e;
  --c-positive-wash: color-mix(in oklab, #11803d 10%, transparent);
  --c-negative-wash: color-mix(in oklab, #c4283a 10%, transparent);
  --c-warning-wash: color-mix(in oklab, #8a5a00 10%, transparent);
  --c-info-wash: color-mix(in oklab, #0b6c9e 10%, transparent);

  --c-grid: #e8edf3;
  --c-axis: #c9d3df;
  --c-axis-text: #5e6b7e;
  --c-track: #edf1f5;
  --c-deemphasis: #aab6c4;

  --c-cat-1: #1e59cd;
  --c-cat-2: #da682c;
  --c-cat-3: #06949a;
  --c-cat-4: #e75f66;
  --c-cat-5: #026a1a;
  --c-cat-6: #cb5ac3;
  --c-cat-7: #aa8f02;
  --c-cat-8: #5737c8;
  --c-cat-9: #08987a;
  --c-cat-10: #cb862e;
  --c-cat-11: #d05b95;
  --c-cat-12: #015590;
  --c-cat-other: #8593a4;

  --c-seq-300: #81aaf7;
  --c-seq-400: #5a8ff3;
  --c-seq-500: #3672e9;
  --c-seq-600: #1e59cd;
  --c-seq-700: #1043a8;

  --c-div-warm-3: #7a4e00;
  --c-div-warm-2: #b07a18;
  --c-div-warm-1: #e0b871;
  --c-div-neutral: #dce3eb;
  --c-div-cool-1: #9bbce8;
  --c-div-cool-2: #3d74be;
  --c-div-cool-3: #10437f;
}

.demo-cabecera {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  max-width: 1200px;
  margin: 0 auto 24px;
}

h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--c-text-2);
}

.demo-nota {
  margin: 4px 0 0;
  max-width: 70ch;
  color: var(--c-text-3);
  font-size: 0.875rem;
}

.demo-controles {
  display: flex;
  gap: 16px;
}

.interruptor {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  color: var(--c-text-2);
  font-size: 0.875rem;
  cursor: pointer;
}

.bloque {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 1200px;
  margin: 0 auto 32px;
  padding-top: 16px;
  border-top: 1px solid var(--c-border);
}

.separado {
  margin-top: 8px;
}

.lista {
  margin: 0;
  padding: 0;
  list-style: none;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 16px;
  padding: 8px 16px;
}

.lista > li + li {
  border-top: 1px solid var(--c-border-soft);
}

.rejilla-graficos {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
}

@media (min-width: 1024px) {
  .rejilla-graficos {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
