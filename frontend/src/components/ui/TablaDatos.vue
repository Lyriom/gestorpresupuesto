<script setup lang="ts" generic="T extends Record<string, unknown>">
import { computed, ref } from 'vue'
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Rows3,
  Rows4,
  TriangleAlert,
} from 'lucide-vue-next'
import { useMedia } from '@/composables/useMedia'
import BotonBase from './BotonBase.vue'
import EstadoVacio from './EstadoVacio.vue'

export interface ColumnaTabla<F> {
  clave: string
  etiqueta: string
  /** Alinea a la derecha y aplica tabular-nums, cabecera incluida. */
  numerica?: boolean
  ordenable?: boolean
  ancho?: string
  /** Se fija al hacer scroll horizontal. */
  fija?: 'inicio' | 'fin'
  /** Texto de la celda cuando no se usa el slot `celda-<clave>`. */
  valor?: (fila: F) => string
  /** Oculta la columna en tableta para bajar de 8 a 6 o 4 columnas. */
  soloEscritorio?: boolean
}

export type DensidadTabla = 'comoda' | 'compacta'
export interface OrdenTabla {
  clave: string
  sentido: 'asc' | 'desc'
}

const props = withDefaults(
  defineProps<{
    columnas: ColumnaTabla<T>[]
    filas: T[]
    claveFila: (fila: T) => string | number
    /** Descripción de la tabla; puede quedar oculta visualmente. */
    titulo: string
    tituloOculto?: boolean
    densidad?: DensidadTabla
    orden?: OrdenTabla | null
    cargando?: boolean
    /** Recarga: el render anterior se mantiene al 55 %, nunca vuelve el esqueleto. */
    recargando?: boolean
    expandible?: boolean
    seleccionables?: boolean
    seleccionadas?: Array<string | number>
    /** Rótulo del pie de totales; debe reflejar el filtro activo. */
    rotuloTotales?: string
    /** Vacío por filtro en lugar de vacío por falta de datos. */
    vacioPorFiltro?: boolean
    error?: string
  }>(),
  { densidad: 'comoda', orden: null, seleccionadas: () => [] },
)

const emit = defineEmits<{
  'update:densidad': [valor: DensidadTabla]
  'update:orden': [valor: OrdenTabla | null]
  'update:seleccionadas': [valor: Array<string | number>]
  filaClic: [fila: T]
  reintentar: []
  quitarFiltros: []
}>()

const { esMovil, esTableta } = useMedia()
const abiertas = ref<Set<string | number>>(new Set())

const columnasVisibles = computed(() =>
  props.columnas.filter((c) => !(c.soloEscritorio && (esMovil.value || esTableta.value))),
)

const altoFila = computed(() => (props.densidad === 'compacta' ? '36px' : '48px'))
const hayFilas = computed(() => props.filas.length > 0)

function textoCelda(columna: ColumnaTabla<T> | undefined, fila: T): string {
  if (!columna) return ''
  if (columna.valor) return columna.valor(fila)
  const bruto = fila[columna.clave]
  return bruto === null || bruto === undefined || bruto === '' ? '—' : String(bruto)
}

/** Clic en la cabecera: asc → desc → sin orden. */
function ordenar(columna: ColumnaTabla<T>): void {
  if (!columna.ordenable) return
  const actual = props.orden
  if (!actual || actual.clave !== columna.clave) {
    emit('update:orden', { clave: columna.clave, sentido: 'asc' })
  } else if (actual.sentido === 'asc') {
    emit('update:orden', { clave: columna.clave, sentido: 'desc' })
  } else {
    emit('update:orden', null)
  }
}

function ariaOrden(columna: ColumnaTabla<T>): 'ascending' | 'descending' | 'none' | undefined {
  if (!columna.ordenable) return undefined
  if (props.orden?.clave !== columna.clave) return 'none'
  return props.orden.sentido === 'asc' ? 'ascending' : 'descending'
}

function alternarFila(clave: string | number): void {
  const copia = new Set(abiertas.value)
  copia.has(clave) ? copia.delete(clave) : copia.add(clave)
  abiertas.value = copia
}

const todasSeleccionadas = computed(
  () => hayFilas.value && props.seleccionadas.length === props.filas.length,
)
const algunaSeleccionada = computed(
  () => props.seleccionadas.length > 0 && !todasSeleccionadas.value,
)

function alternarTodas(): void {
  emit(
    'update:seleccionadas',
    todasSeleccionadas.value ? [] : props.filas.map((f) => props.claveFila(f)),
  )
}

function alternarSeleccion(clave: string | number): void {
  const set = new Set(props.seleccionadas)
  set.has(clave) ? set.delete(clave) : set.add(clave)
  emit('update:seleccionadas', [...set])
}

const anchoTotal = computed(
  () => columnasVisibles.value.length + (props.expandible ? 1 : 0) + (props.seleccionables ? 1 : 0),
)
</script>

<template>
  <section class="tabla-datos">
    <div v-if="$slots.herramientas || !esMovil" class="herramientas">
      <div class="izquierda"><slot name="herramientas" /></div>
      <div v-if="!esMovil" class="densidad" role="group" aria-label="Densidad de las filas">
        <button
          type="button"
          :aria-pressed="densidad === 'comoda'"
          aria-label="Densidad cómoda"
          @click="emit('update:densidad', 'comoda')"
        >
          <Rows3 :size="16" aria-hidden="true" />
        </button>
        <button
          type="button"
          :aria-pressed="densidad === 'compacta'"
          aria-label="Densidad compacta"
          @click="emit('update:densidad', 'compacta')"
        >
          <Rows4 :size="16" aria-hidden="true" />
        </button>
      </div>
    </div>

    <!-- Error de carga: una sola fila con causa y reintento. -->
    <div v-if="error" class="error tarjeta" role="alert">
      <TriangleAlert :size="18" aria-hidden="true" />
      <span>{{ error }}</span>
      <BotonBase variante="contorno" tamanyo="sm" @click="emit('reintentar')">Reintentar</BotonBase>
    </div>

    <!-- Móvil: tarjetas apiladas. Nunca scroll horizontal. -->
    <ul v-else-if="esMovil" class="tarjetas" :class="{ recargando }" :aria-busy="cargando">
      <template v-if="cargando">
        <li v-for="n in 6" :key="`e${n}`" class="ficha tarjeta">
          <span class="esqueleto" style="height: 14px; width: 60%" />
          <span class="esqueleto" style="height: 15px; width: 88px" />
        </li>
      </template>
      <template v-else>
        <li v-for="fila in filas" :key="claveFila(fila)" class="ficha tarjeta">
          <button type="button" class="ficha-boton" @click="emit('filaClic', fila)">
            <span class="ficha-titulo">
              <slot
                :name="`celda-${columnasVisibles[0]?.clave}`"
                :fila="fila"
                :valor="textoCelda(columnasVisibles[0], fila)"
              >
                {{ textoCelda(columnasVisibles[0], fila) }}
              </slot>
            </span>
            <span class="ficha-meta">
              <template v-for="c in columnasVisibles.slice(1, 3)" :key="c.clave">
                <span>{{ textoCelda(c, fila) }}</span>
              </template>
            </span>
          </button>
          <span
            v-for="c in columnasVisibles.filter((c) => c.numerica).slice(0, 1)"
            :key="c.clave"
            class="ficha-importe num"
          >
            <slot :name="`celda-${c.clave}`" :fila="fila" :valor="textoCelda(c, fila)">
              {{ textoCelda(c, fila) }}
            </slot>
          </span>
          <ChevronRight :size="16" class="ficha-chevron" aria-hidden="true" />
        </li>
      </template>
      <li v-if="!cargando && !hayFilas" class="ficha-vacia">
        <slot name="vacio">
          <EstadoVacio
            :tipo="vacioPorFiltro ? 'sin-filtros' : 'primer-uso'"
            :titulo="vacioPorFiltro ? 'Ningún resultado con estos filtros' : 'Todavía no hay datos'"
          />
        </slot>
      </li>
    </ul>

    <!-- Escritorio y tableta: tabla semántica. -->
    <div v-else class="marco" tabindex="0">
      <table :class="[`d-${densidad}`, { recargando }]" :aria-busy="cargando">
        <caption :class="{ 'oculto-visualmente': tituloOculto }">
          {{ titulo }}
        </caption>
        <thead>
          <tr :style="{ '--alto': altoFila }">
            <th v-if="seleccionables" scope="col" class="estrecha fija-inicio">
              <input
                type="checkbox"
                :checked="todasSeleccionadas"
                :indeterminate="algunaSeleccionada"
                aria-label="Seleccionar todas las filas"
                @change="alternarTodas"
              />
            </th>
            <th v-if="expandible" scope="col" class="estrecha" />
            <th
              v-for="columna in columnasVisibles"
              :key="columna.clave"
              scope="col"
              :class="[
                { numerica: columna.numerica, ordenable: columna.ordenable },
                columna.fija ? `fija-${columna.fija}` : '',
              ]"
              :style="columna.ancho ? { width: columna.ancho } : undefined"
              :aria-sort="ariaOrden(columna)"
              :data-numeric="columna.numerica ? '' : undefined"
            >
              <button v-if="columna.ordenable" type="button" @click="ordenar(columna)">
                {{ columna.etiqueta }}
                <ArrowUp
                  v-if="orden?.clave === columna.clave && orden.sentido === 'asc'"
                  :size="12"
                  aria-hidden="true"
                />
                <ArrowDown
                  v-else-if="orden?.clave === columna.clave"
                  :size="12"
                  aria-hidden="true"
                />
                <ArrowUp v-else :size="12" class="pista-orden" aria-hidden="true" />
              </button>
              <span v-else>{{ columna.etiqueta }}</span>
            </th>
          </tr>
        </thead>

        <!-- Cargando: 8 filas con las anchuras reales de columna. -->
        <tbody v-if="cargando">
          <tr v-for="n in 8" :key="`e${n}`" :style="{ '--alto': altoFila }">
            <td v-if="seleccionables" />
            <td v-if="expandible" />
            <td v-for="columna in columnasVisibles" :key="columna.clave">
              <span
                class="esqueleto"
                :style="{ height: '14px', width: columna.numerica ? '88px' : '70%' }"
              />
            </td>
          </tr>
        </tbody>

        <tbody v-else-if="hayFilas">
          <template v-for="fila in filas" :key="claveFila(fila)">
            <tr
              :style="{ '--alto': altoFila }"
              :aria-selected="seleccionables ? seleccionadas.includes(claveFila(fila)) : undefined"
              :class="{ elegida: seleccionadas.includes(claveFila(fila)) }"
              @click="emit('filaClic', fila)"
            >
              <td v-if="seleccionables" class="estrecha fija-inicio">
                <input
                  type="checkbox"
                  :checked="seleccionadas.includes(claveFila(fila))"
                  :aria-label="`Seleccionar la fila ${textoCelda(columnasVisibles[0], fila)}`"
                  @click.stop
                  @change="alternarSeleccion(claveFila(fila))"
                />
              </td>
              <td v-if="expandible" class="estrecha">
                <button
                  type="button"
                  class="expandir"
                  :aria-expanded="abiertas.has(claveFila(fila))"
                  :aria-controls="`detalle-${claveFila(fila)}`"
                  :aria-label="abiertas.has(claveFila(fila)) ? 'Ocultar detalle' : 'Ver detalle'"
                  @click.stop="alternarFila(claveFila(fila))"
                >
                  <ChevronDown v-if="abiertas.has(claveFila(fila))" :size="16" aria-hidden="true" />
                  <ChevronRight v-else :size="16" aria-hidden="true" />
                </button>
              </td>
              <td
                v-for="columna in columnasVisibles"
                :key="columna.clave"
                :class="[
                  { numerica: columna.numerica },
                  columna.fija ? `fija-${columna.fija}` : '',
                ]"
                :data-numeric="columna.numerica ? '' : undefined"
              >
                <slot
                  :name="`celda-${columna.clave}`"
                  :fila="fila"
                  :valor="textoCelda(columna, fila)"
                >
                  {{ textoCelda(columna, fila) }}
                </slot>
              </td>
            </tr>
            <tr
              v-if="expandible && abiertas.has(claveFila(fila))"
              :id="`detalle-${claveFila(fila)}`"
              class="detalle"
            >
              <td :colspan="anchoTotal"><slot name="detalle" :fila="fila" /></td>
            </tr>
          </template>
        </tbody>

        <tfoot v-if="rotuloTotales || $slots.pie">
          <tr>
            <td v-if="seleccionables" />
            <td v-if="expandible" />
            <slot name="pie">
              <td :colspan="columnasVisibles.length">{{ rotuloTotales }}</td>
            </slot>
          </tr>
        </tfoot>
      </table>

      <div v-if="!cargando && !hayFilas" class="vacio">
        <slot name="vacio">
          <EstadoVacio
            :tipo="vacioPorFiltro ? 'sin-filtros' : 'primer-uso'"
            :titulo="vacioPorFiltro ? 'Ningún resultado con estos filtros' : 'Todavía no hay datos'"
            :descripcion="
              vacioPorFiltro
                ? 'Prueba a relajar algún criterio para ver más resultados.'
                : 'Cuando registres el primer movimiento aparecerá en esta tabla.'
            "
          >
            <template v-if="vacioPorFiltro" #accion>
              <BotonBase variante="contorno" @click="emit('quitarFiltros')">
                Quitar filtros
              </BotonBase>
            </template>
          </EstadoVacio>
        </slot>
      </div>
    </div>
  </section>
</template>

<style scoped>
.tabla-datos {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.herramientas {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
}
.izquierda {
  flex: 1 1 auto;
  min-width: 0;
}
.densidad {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background-color: var(--c-surface);
}
.densidad button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 28px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--c-text-3);
  cursor: pointer;
}
.densidad button[aria-pressed='true'] {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}

.marco {
  overflow-x: auto;
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  background-color: var(--c-surface);
}
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: var(--t-body);
}
caption {
  padding: var(--sp-3);
  text-align: left;
  font-size: var(--t-caption);
  color: var(--c-text-3);
}

thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  height: 36px;
  padding-inline: var(--sp-3);
  border-bottom: 1px solid var(--c-border);
  background-color: var(--c-surface);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--c-text-3);
  text-align: left;
  white-space: nowrap;
}
thead th.numerica {
  text-align: right;
}
thead th button {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  letter-spacing: inherit;
  text-transform: inherit;
  cursor: pointer;
}
thead th.numerica button {
  flex-direction: row-reverse;
}
.pista-orden {
  opacity: 0;
}
thead th button:hover .pista-orden {
  opacity: 0.5;
}

tbody td {
  height: var(--alto);
  padding-inline: var(--sp-3);
  border-bottom: 1px solid var(--c-border-soft);
  color: var(--c-text-1);
  vertical-align: middle;
}
tbody td.numerica {
  text-align: right;
}
tbody tr:hover td {
  background-color: var(--c-surface-3);
}
tbody tr.elegida td {
  background-color: var(--c-accent-wash);
}
tbody tr.elegida td:first-child {
  box-shadow: inset 2px 0 0 0 var(--c-accent);
}

.d-compacta tbody td {
  font-size: var(--t-sm);
}

tr.detalle td {
  height: auto;
  padding: var(--sp-4);
  background-color: var(--c-surface-sunken);
}

tfoot td {
  height: 40px;
  padding-inline: var(--sp-3);
  border-top: 1px solid var(--c-border-strong);
  background-color: var(--c-surface);
  font-weight: 600;
  font-size: var(--t-caption);
  color: var(--c-text-2);
}

.estrecha {
  width: 40px;
  padding-inline: var(--sp-2) !important;
}
.fija-inicio {
  position: sticky;
  left: 0;
  z-index: 1;
  background-color: var(--c-surface);
  border-right: 1px solid var(--c-border-strong);
}
.fija-fin {
  position: sticky;
  right: 0;
  z-index: 1;
  background-color: var(--c-surface);
  border-left: 1px solid var(--c-border-strong);
}
thead th.fija-inicio,
thead th.fija-fin {
  z-index: 3;
}

.expandir {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--c-text-3);
  cursor: pointer;
}
.expandir:hover {
  background-color: var(--c-surface-2);
  color: var(--c-text-1);
}

input[type='checkbox'] {
  width: 18px;
  height: 18px;
  accent-color: var(--c-accent);
}

.error {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4);
  color: var(--c-negative);
  font-size: var(--t-sm);
}
.error span {
  flex: 1 1 auto;
}
.vacio {
  padding: var(--sp-4);
}

/* --- Tarjetas en móvil --------------------------------------------------- */
.tarjetas {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.ficha {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  min-height: 64px;
}
.ficha-boton {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 0;
  padding: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.ficha-titulo {
  font-size: var(--t-body);
  font-weight: 600;
  color: var(--c-text-1);
}
.ficha-meta {
  display: flex;
  gap: var(--sp-2);
  font-size: var(--t-caption);
  color: var(--c-text-3);
}
.ficha-importe {
  flex: none;
  font-weight: 600;
}
.ficha-chevron {
  flex: none;
  color: var(--c-text-3);
}
.ficha-vacia {
  padding: var(--sp-4);
}

.oculto-visualmente {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>
