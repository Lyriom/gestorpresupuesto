<script setup lang="ts">
/**
 * Panel (§2.3): en un vistazo, cuánto queda del mes, qué necesita atención y lo
 * último que ha pasado.
 *
 * Los tres módulos cargan de forma independiente y fallan de forma
 * independiente: si el presupuesto no llega, las temáticas y los movimientos se
 * pintan igual.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { CircleAlert, Info, TriangleAlert } from 'lucide-vue-next'

import { apiMovimientos, type Movimiento } from '@/api/movimientos'
import BarraPresupuesto from '@/components/presupuesto/BarraPresupuesto.vue'
import BarraCategoria from '@/components/presupuesto/BarraCategoria.vue'
import type { AsignacionTematica } from '@/components/presupuesto/types'
import BotonBase from '@/components/ui/BotonBase.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import EtiquetaCategoria from '@/components/ui/EtiquetaCategoria.vue'
import { euros, fechaCorta } from '@/lib/formato'
import { accionDe, useAlertas } from '@/stores/alertas'
import { mensajeDeError } from '@/stores/comun'
import { ranuraDeCategoria } from '@/stores/categorias'
import { usePresupuesto } from '@/stores/presupuesto'
import BloqueError from './componentes/BloqueError.vue'
import ModalMovimiento from './componentes/ModalMovimiento.vue'
import ModalReparto from './componentes/ModalReparto.vue'

const router = useRouter()
const presupuesto = usePresupuesto()
const alertas = useAlertas()

const ultimos = ref<Movimiento[]>([])
const cargandoUltimos = ref(false)
const errorUltimos = ref<string | null>(null)

const repartoAbierto = ref(false)
const destacadaEnReparto = ref<string | null>(null)
const altaAbierta = ref(false)
const categoriaParaAlta = ref<string | null>(null)

const mostrarComoTabla = ref(false)

const asignacionesConGasto = computed(() =>
  presupuesto.asignaciones.filter((a) => a.state !== 'sin_gasto' || a.allocated !== '0.00'),
)

async function cargarUltimos(): Promise<void> {
  cargandoUltimos.value = true
  errorUltimos.value = null
  try {
    const pag = await apiMovimientos.listar({
      size: 5,
      sort: '-date,-created_at',
      include: ['category', 'account', 'payee'],
    })
    ultimos.value = pag.items
  } catch (e) {
    ultimos.value = []
    errorUltimos.value = mensajeDeError(e, 'No se han podido cargar los movimientos.')
  } finally {
    cargandoUltimos.value = false
  }
}

function verMovimientosDe(asignacion: AsignacionTematica): void {
  // El mes activo viaja como rango de fechas, que es el filtro que entiende la lista.
  const [anyo, mes] = presupuesto.periodo.split('-').map(Number)
  const ultimo = new Date(anyo, mes, 0).getDate()
  void router.push({
    name: 'movimientos',
    query: {
      tematica: asignacion.category_id,
      desde: `${presupuesto.periodo}-01`,
      hasta: `${presupuesto.periodo}-${String(ultimo).padStart(2, '0')}`,
    },
  })
}

function abrirReparto(asignacion: AsignacionTematica | null): void {
  destacadaEnReparto.value = asignacion?.category_id ?? null
  repartoAbierto.value = true
}

function recargarTodo(): void {
  void presupuesto.cargar()
  void alertas.cargar(presupuesto.periodo)
  void cargarUltimos()
}

onMounted(() => {
  void presupuesto.cargar()
  void alertas.cargar(presupuesto.periodo)
  void cargarUltimos()
})

// El mes es el ámbito de todo el panel: al cambiarlo se recarga lo que depende de él.
watch(
  () => presupuesto.periodo,
  () => {
    void alertas.cargar(presupuesto.periodo)
  },
)
</script>

<template>
  <div class="panel">
    <!-- Presupuesto del mes -->
    <BloqueError
      v-if="presupuesto.error && !presupuesto.mes"
      :titulo="`No se ha podido cargar el presupuesto de ${presupuesto.periodo}`"
      :nivel="2"
      @reintentar="presupuesto.cargar()"
    />
    <BarraPresupuesto
      v-else
      :barra="presupuesto.mes"
      :cargando="presupuesto.cargando"
      @activar="verMovimientosDe"
      @reasignar="abrirReparto"
      @repartir="abrirReparto(null)"
      @copiar-mes-anterior="presupuesto.copiarDelMesAnterior()"
      @poner-ingresos="abrirReparto(null)"
    />

    <!-- Avisos ya redactados por el backend -->
    <section v-if="alertas.abiertas.length > 0" class="bloque" aria-labelledby="titulo-avisos">
      <h2 id="titulo-avisos" class="titulo-bloque">Avisos</h2>
      <ul class="avisos">
        <li
          v-for="a in alertas.abiertas"
          :key="a.id"
          class="aviso"
          :class="`aviso--${a.severity}`"
        >
          <TriangleAlert v-if="a.severity === 'critical'" :size="16" aria-hidden="true" />
          <CircleAlert v-else-if="a.severity === 'warning'" :size="16" aria-hidden="true" />
          <Info v-else :size="16" aria-hidden="true" />
          <span class="texto-aviso">{{ a.message }}</span>
          <BotonBase
            v-if="accionDe(a.type) === 'reasignar'"
            variante="secundaria"
            tamanyo="sm"
            @click="abrirReparto(null)"
          >
            Reasignar
          </BotonBase>
          <BotonBase
            v-else-if="accionDe(a.type) === 'asignar'"
            variante="secundaria"
            tamanyo="sm"
            @click="abrirReparto(null)"
          >
            Asignar
          </BotonBase>
          <BotonBase
            v-else-if="accionDe(a.type) === 'ver-movimientos'"
            variante="fantasma"
            tamanyo="sm"
            @click="router.push({ name: 'movimientos' })"
          >
            Ver movimientos
          </BotonBase>
          <BotonBase
            v-else-if="accionDe(a.type) === 'ver-producto' && a.product_id"
            variante="fantasma"
            tamanyo="sm"
            @click="router.push({ name: 'producto', params: { id: a.product_id } })"
          >
            Ver producto
          </BotonBase>
        </li>
      </ul>
    </section>

    <!-- Temáticas del mes -->
    <section class="bloque" aria-labelledby="titulo-tematicas">
      <div class="cabecera-bloque">
        <h2 id="titulo-tematicas" class="titulo-bloque">Temáticas</h2>
        <BotonBase variante="enlace" tamanyo="sm" @click="mostrarComoTabla = !mostrarComoTabla">
          {{ mostrarComoTabla ? 'Ver como lista' : 'Ver como tabla' }}
        </BotonBase>
      </div>

      <div v-if="presupuesto.cargando" class="tarjeta caja">
        <EsqueletoCarga variante="barra" :lineas="6" anuncio="Cargando las temáticas del mes" />
      </div>

      <div v-else-if="asignacionesConGasto.length === 0" class="tarjeta caja">
        <EstadoVacio
          titulo="Todavía no has creado ninguna temática."
          descripcion="Sin temáticas no hay barra que repartir."
          :nivel="3"
        >
          <template #accion>
            <BotonBase variante="primaria" @click="router.push({ name: 'tematicas' })">
              Crear la primera
            </BotonBase>
          </template>
        </EstadoVacio>
      </div>

      <div v-else-if="mostrarComoTabla" class="tarjeta envoltorio-tabla" tabindex="0">
        <table class="tabla">
          <caption class="oculto">Reparto del mes por temática</caption>
          <thead>
            <tr>
              <th scope="col">Temática</th>
              <th scope="col" class="num-col">Gastado</th>
              <th scope="col" class="num-col">Asignado</th>
              <th scope="col" class="num-col">Disponible</th>
              <th scope="col" class="num-col">Consumido</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in asignacionesConGasto" :key="a.category_id">
              <th scope="row">
                <EtiquetaCategoria
                  :nombre="a.category.name"
                  :ranura="ranuraDeCategoria(a.category.color, a.category_id)"
                  tamanyo="sm"
                />
              </th>
              <td class="num-col num">{{ euros(a.spent) }}</td>
              <td class="num-col num">{{ euros(a.allocated) }}</td>
              <td class="num-col num">{{ euros(a.available) }}</td>
              <td class="num-col num">{{ Math.round((a.spent_pct ?? 0) * 100) }} %</td>
            </tr>
          </tbody>
        </table>
      </div>

      <ul v-else class="tarjeta lista-tematicas">
        <li v-for="a in asignacionesConGasto" :key="a.category_id">
          <BarraCategoria
            :asignacion="a"
            :dia-actual="presupuesto.mes?.day_of_month"
            :dias-del-mes="presupuesto.mes?.days_in_month"
            @activar="verMovimientosDe"
            @asignar="abrirReparto"
          />
        </li>
      </ul>
    </section>

    <!-- Últimos movimientos -->
    <section class="bloque" aria-labelledby="titulo-ultimos">
      <div class="cabecera-bloque">
        <h2 id="titulo-ultimos" class="titulo-bloque">Últimos movimientos</h2>
        <BotonBase variante="enlace" tamanyo="sm" @click="router.push({ name: 'movimientos' })">
          Ver todos
        </BotonBase>
      </div>

      <div v-if="cargandoUltimos" class="tarjeta caja">
        <EsqueletoCarga variante="texto" :lineas="5" anuncio="Cargando los últimos movimientos" />
      </div>

      <BloqueError
        v-else-if="errorUltimos"
        titulo="No se han podido cargar los movimientos"
        @reintentar="cargarUltimos"
      />

      <div v-else-if="ultimos.length === 0" class="tarjeta caja">
        <EstadoVacio titulo="Todavía no has apuntado ningún movimiento." :nivel="3">
          <template #accion>
            <BotonBase variante="primaria" @click="altaAbierta = true">Añadir el primero</BotonBase>
          </template>
        </EstadoVacio>
      </div>

      <ul v-else class="tarjeta lista-movimientos">
        <li v-for="m in ultimos" :key="m.id">
          <span class="fecha">{{ fechaCorta(m.date) }}</span>
          <span class="concepto">{{ m.description || m.payee?.name || 'Sin concepto' }}</span>
          <EtiquetaCategoria
            v-if="m.category"
            :nombre="m.category.name"
            :ranura="ranuraDeCategoria(m.category.color, m.category.id)"
            tamanyo="sm"
          />
          <EtiquetaCategoria v-else-if="m.is_split" nombre="Repartido" :ranura="0" tamanyo="sm" />
          <span v-else class="sin-tematica">Sin clasificar</span>
          <span class="cuenta">{{ m.account?.name ?? '' }}</span>
          <span class="importe num" :class="m.kind === 'income' ? 'positivo' : 'negativo'">
            {{ euros(m.signed_amount, { signoSiempre: true }) }}
          </span>
        </li>
      </ul>
    </section>

    <ModalReparto
      v-model:abierto="repartoAbierto"
      :destacada="destacadaEnReparto"
      @guardado="recargarTodo"
    />
    <ModalMovimiento
      v-model:abierto="altaAbierta"
      :categoria-inicial="categoriaParaAlta"
      @guardado="recargarTodo"
    />
  </div>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
}
.bloque {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.cabecera-bloque {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
}
.titulo-bloque {
  margin: 0;
  font-size: var(--t-h2);
  line-height: var(--t-h2-lh);
  font-weight: 600;
}
.caja {
  padding: var(--sp-4);
}

.avisos {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.aviso {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3);
  border-radius: var(--r-lg);
  font-size: var(--t-sm);
}
.aviso--critical {
  background-color: var(--c-negative-wash);
  color: var(--c-negative);
}
.aviso--warning {
  background-color: var(--c-warning-wash);
  color: var(--c-warning);
}
.aviso--info {
  background-color: var(--c-info-wash);
  color: var(--c-info);
}
.texto-aviso {
  flex: 1 1 20ch;
}

.lista-tematicas,
.lista-movimientos {
  margin: 0;
  padding: var(--sp-2) var(--sp-4);
  list-style: none;
}
.lista-tematicas > li + li,
.lista-movimientos > li + li {
  border-top: 1px solid var(--c-border-soft);
}

.lista-movimientos > li {
  display: grid;
  grid-template-columns: 6.5rem minmax(0, 1fr) auto auto 8rem;
  align-items: center;
  gap: var(--sp-3);
  min-height: 44px;
}
.fecha,
.cuenta {
  color: var(--c-text-3);
  font-size: var(--t-caption);
}
.concepto {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sin-tematica {
  color: var(--c-text-3);
  font-size: var(--t-caption);
}
.importe {
  text-align: right;
  font-weight: 600;
}
.positivo {
  color: var(--c-positive);
}
.negativo {
  color: var(--c-text-1);
}

@media (max-width: 767px) {
  .lista-movimientos > li {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .cuenta {
    display: none;
  }
}

.envoltorio-tabla {
  overflow-x: auto;
}
.tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-sm);
}
.tabla th,
.tabla td {
  padding: var(--sp-2) var(--sp-3);
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
