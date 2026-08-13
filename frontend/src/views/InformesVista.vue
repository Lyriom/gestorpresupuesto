<script setup lang="ts">
/**
 * Informes (§2.12).
 *
 * Cada pestaña carga su informe y falla por su cuenta: el selector de periodo y
 * las demás pestañas siguen operativos. La pestaña activa y el rango viajan en
 * la URL, así que un informe concreto es enlazable.
 */
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowUpRight } from 'lucide-vue-next'

import GraficoAreaCashFlow from '@/components/graficos/GraficoAreaCashFlow.vue'
import GraficoBarras from '@/components/graficos/GraficoBarras.vue'
import GraficoLineas from '@/components/graficos/GraficoLineas.vue'
import BotonBase from '@/components/ui/BotonBase.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import PestanyasBase from '@/components/ui/PestanyasBase.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import { aNumero, etiquetaPeriodo, euros, porcentaje, precioUnitario } from '@/lib/formato'
import { ranuraDeCategoria } from '@/stores/categorias'
import { PESTANYAS_INFORME, RANGOS, useInformes, type PestanyaInforme } from '@/stores/informes'
import BloqueError from './componentes/BloqueError.vue'

const route = useRoute()
const router = useRouter()
const informes = useInformes()

const opcionesRango = RANGOS.map((r) => ({ valor: r.valor, etiqueta: r.etiqueta }))

const errorActual = computed(() => informes.errores[informes.pestanya])

/* --- Series por pestaña ------------------------------------------------- */

const ingresos = computed(() => informes.ingresosYGastos)
const etiquetasMes = computed(() =>
  (ingresos.value?.rows ?? []).map((r) => etiquetaPeriodo(r.period)),
)
const serieIngresos = computed(() => (ingresos.value?.rows ?? []).map((r) => aNumero(r.income)))
const serieGastos = computed(() => (ingresos.value?.rows ?? []).map((r) => aNumero(r.expense)))

const tematicas = computed(() => informes.porTematica?.rows ?? [])
const nombresTematica = computed(() => tematicas.value.map((r) => r.category.name))
const gastoTematica = computed(() => tematicas.value.map((r) => aNumero(r.amount)))
const coloresTematica = computed(() =>
  tematicas.value.map((r) => String(ranuraDeCategoria(r.category.color, r.category.id))),
)

const subidas = computed(() => informes.subidas?.rows ?? [])

const cashFlow = computed(() =>
  (informes.cashFlow?.points ?? []).map((p) => ({
    etiqueta: etiquetaPeriodo(p.period),
    ingresos: aNumero(p.inflow),
    gastos: aNumero(p.outflow),
  })),
)

function cambiarPestanya(valor: string | number): void {
  const nueva = String(valor) as PestanyaInforme
  informes.cambiarPestanya(nueva)
  void router.replace({ query: { ...route.query, pestanya: nueva } })
}

function cambiarRango(valor: string | number | null): void {
  const meses = Number(valor ?? 6)
  informes.cambiarRango(meses)
  void router.replace({ query: { ...route.query, meses: String(meses) } })
}

function irAMovimientos(categoryId: string): void {
  void router.push({ name: 'movimientos', query: { tematica: categoryId } })
}

onMounted(() => {
  const pedida = route.query.pestanya
  const meses = Number(Array.isArray(route.query.meses) ? route.query.meses[0] : route.query.meses)
  if (typeof pedida === 'string' && PESTANYAS_INFORME.some((p) => p.valor === pedida)) {
    informes.pestanya = pedida as PestanyaInforme
  }
  if (Number.isFinite(meses) && meses > 0) informes.meses = meses
  void informes.cargar()
})
</script>

<template>
  <div class="vista">
    <h1 class="titulo">Informes</h1>

    <PestanyasBase
      :model-value="informes.pestanya"
      etiqueta="Tipos de informe"
      :pestanyas="PESTANYAS_INFORME"
      @update:model-value="cambiarPestanya"
    >
      <div class="controles">
        <SelectorBase
          :model-value="String(informes.meses)"
          etiqueta="Periodo"
          etiqueta-oculta
          :opciones="opcionesRango"
          @update:model-value="cambiarRango"
        />
      </div>

      <div v-if="informes.cargando" class="tarjeta caja">
        <EsqueletoCarga variante="bloque" alto="260px" anuncio="Generando el informe" />
      </div>

      <BloqueError
        v-else-if="errorActual"
        titulo="No se ha podido generar este informe"
        :nivel="2"
        @reintentar="informes.cargar()"
      />

      <div v-else-if="informes.sinDatos" class="tarjeta caja">
        <EstadoVacio
          titulo="No hay movimientos en este periodo."
          :criterio="informes.etiquetaRango"
          tipo="sin-filtros"
          :nivel="2"
        >
          <template #accion>
            <BotonBase variante="contorno" @click="cambiarRango('12')">
              Elegir otro periodo
            </BotonBase>
          </template>
        </EstadoVacio>
      </div>

      <!-- Ingresos y gastos -->
      <template v-else-if="informes.pestanya === 'ingresos'">
        <div class="cifras tarjeta caja">
          <div>
            <p class="rotulo">Ingresos</p>
            <p class="valor num">{{ euros(ingresos?.income_total) }}</p>
          </div>
          <div>
            <p class="rotulo">Gastos</p>
            <p class="valor num">{{ euros(ingresos?.expense_total) }}</p>
          </div>
          <div>
            <p class="rotulo">Ahorro</p>
            <p class="valor num positivo">{{ euros(ingresos?.savings_total) }}</p>
          </div>
          <div>
            <p class="rotulo">Tasa de ahorro</p>
            <p class="valor num">{{ porcentaje(ingresos?.savings_rate ?? 0) }}</p>
          </div>
        </div>

        <GraficoLineas
          titulo="Evolución mensual"
          :subtitulo="informes.etiquetaRango"
          columna-etiquetas="Mes"
          :etiquetas="etiquetasMes"
          :series="[
            { nombre: 'Ingresos', datos: serieIngresos, color: 'cat-3', area: true },
            { nombre: 'Gastos', datos: serieGastos, color: 'cat-2' },
          ]"
          :resumen="`Ingresos y gastos mes a mes durante ${informes.etiquetaRango.toLowerCase()}.`"
        />
      </template>

      <!-- Gasto por temática -->
      <template v-else-if="informes.pestanya === 'tematicas'">
        <GraficoBarras
          titulo="En qué se te va el dinero"
          :subtitulo="informes.etiquetaRango"
          :etiquetas="nombresTematica"
          :series="[{ nombre: 'Gastado', datos: gastoTematica }]"
          :colores-etiquetas="coloresTematica"
          colorear="categorico"
          :resumen="`Gasto por temática durante ${informes.etiquetaRango.toLowerCase()}.`"
        />

        <section class="tarjeta" aria-labelledby="titulo-detalle-tematicas">
          <h2 id="titulo-detalle-tematicas" class="titulo-bloque">Detalle por temática</h2>
          <div class="envoltorio-tabla" tabindex="0">
            <table class="tabla">
              <caption class="oculto">Gasto por temática con su presupuesto</caption>
              <thead>
                <tr>
                  <th scope="col">Temática</th>
                  <th scope="col" class="num-col">Gastado</th>
                  <th scope="col" class="num-col">% del total</th>
                  <th scope="col" class="num-col">Presupuestado</th>
                  <th scope="col" class="num-col">Diferencia</th>
                  <th scope="col"><span class="oculto">Acciones</span></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in tematicas" :key="r.category.id">
                  <th scope="row">{{ r.category.name }}</th>
                  <td class="num-col num">{{ euros(r.amount) }}</td>
                  <td class="num-col num">{{ porcentaje(r.share_pct / 100) }}</td>
                  <td class="num-col num">{{ r.allocated ? euros(r.allocated) : '—' }}</td>
                  <td
                    class="num-col num"
                    :class="{ negativo: r.variance !== null && aNumero(r.variance) < 0 }"
                  >
                    {{ r.variance ? euros(r.variance) : '—' }}
                  </td>
                  <td>
                    <BotonBase
                      variante="enlace"
                      tamanyo="sm"
                      @click="irAMovimientos(r.category.id)"
                    >
                      Ver movimientos
                    </BotonBase>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>

      <!-- Comparativa de precios -->
      <template v-else-if="informes.pestanya === 'precios'">
        <p class="intro">
          Subidas detectadas en {{ informes.etiquetaRango.toLowerCase() }}, ordenadas por lo que
          cuestan al mes y no por el porcentaje.
        </p>
        <section class="tarjeta">
          <div class="envoltorio-tabla" tabindex="0">
            <table class="tabla">
              <caption class="oculto">Productos que han subido de precio</caption>
              <thead>
                <tr>
                  <th scope="col">Producto</th>
                  <th scope="col">Comercio</th>
                  <th scope="col" class="num-col">Antes</th>
                  <th scope="col" class="num-col">Ahora</th>
                  <th scope="col" class="num-col">Variación</th>
                  <th scope="col" class="num-col">Impacto mensual</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in subidas" :key="`${r.product.id}-${r.observed_at}`">
                  <th scope="row">
                    <BotonBase
                      variante="enlace"
                      tamanyo="sm"
                      @click="router.push({ name: 'producto', params: { id: r.product.id } })"
                    >
                      {{ r.product.name }}
                    </BotonBase>
                  </th>
                  <td>{{ r.payee?.name ?? '—' }}</td>
                  <td class="num-col num">{{ precioUnitario(r.previous_unit_price) }}</td>
                  <td class="num-col num">{{ precioUnitario(r.new_unit_price) }}</td>
                  <!-- Subida de precio: flecha + signo además del color (§2.3). -->
                  <td class="num-col num negativo">
                    <ArrowUpRight :size="14" aria-hidden="true" />
                    <span class="oculto">Ha subido</span>
                    +{{ porcentaje(r.change_pct / 100) }}
                  </td>
                  <td class="num-col num">
                    {{ r.estimated_monthly_impact ? euros(r.estimated_monthly_impact) : '—' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="pie-tabla num">
            Impacto total estimado
            <strong>{{ euros(informes.subidas?.total_estimated_impact) }}</strong>
          </p>
        </section>
      </template>

      <!-- Ahorro -->
      <template v-else>
        <GraficoAreaCashFlow
          titulo="¿Entra más de lo que sale?"
          :subtitulo="informes.etiquetaRango"
          :puntos="cashFlow"
          :resumen="`Ingresos, gastos y saldo acumulado durante ${informes.etiquetaRango.toLowerCase()}.`"
        />
        <p class="tarjeta caja num">
          Tasa de ahorro del periodo
          <strong>{{ porcentaje(informes.cashFlow?.savings_rate ?? 0) }}</strong>
          · Neto {{ euros(informes.cashFlow?.net) }}
        </p>
      </template>
    </PestanyasBase>
  </div>
</template>

<style scoped>
.vista {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.titulo {
  margin: 0;
  font-size: var(--t-h1);
  line-height: var(--t-h1-lh);
  font-weight: 600;
}
.titulo-bloque {
  margin: 0;
  padding: var(--sp-4) var(--sp-4) 0;
  font-size: var(--t-h2);
  font-weight: 600;
}
.controles {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--sp-4);
  max-width: 260px;
  margin-left: auto;
}
.caja {
  padding: var(--sp-5);
}

.cifras {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
}
.rotulo {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-3);
}
.valor {
  margin: var(--sp-1) 0 0;
  font-size: var(--t-h2);
  font-weight: 600;
}
.positivo {
  color: var(--c-positive);
}
.negativo {
  color: var(--c-negative);
}
.intro {
  margin: 0 0 var(--sp-3);
  font-size: var(--t-sm);
  color: var(--c-text-2);
}

.envoltorio-tabla {
  overflow-x: auto;
  padding: var(--sp-3) var(--sp-4);
}
.tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-sm);
}
.tabla th,
.tabla td {
  padding: var(--sp-2);
  text-align: left;
  border-bottom: 1px solid var(--c-border-soft);
  white-space: nowrap;
}
.tabla thead th {
  color: var(--c-text-3);
  font-weight: 500;
}
.num-col {
  text-align: right;
}
/* La flecha de variación acompaña a la cifra sin descolgarse de la línea base. */
.num-col svg {
  vertical-align: text-bottom;
}
.pie-tabla {
  margin: 0;
  padding: var(--sp-3) var(--sp-4) var(--sp-4);
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.oculto {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>
