<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeft, ChevronRight, LoaderCircle } from 'lucide-vue-next'

/** Cifras no monetarias: `1.284 movimientos`. formato.ts solo formatea dinero. */
const fmtEnteros = new Intl.NumberFormat('es-ES')

const props = withDefaults(
  defineProps<{
    /** Página actual, empezando en 1. */
    pagina: number
    tamanyoPagina: number
    total: number
    tamanyos?: number[]
    cargando?: boolean
    /** Nombre de lo que se cuenta, para el rótulo: «de 1.284 movimientos». */
    unidad?: string
  }>(),
  { tamanyos: () => [25, 50, 100, 200] },
)

const emit = defineEmits<{
  'update:pagina': [pagina: number]
  'update:tamanyoPagina': [tamanyo: number]
}>()

const paginas = computed(() => Math.max(1, Math.ceil(props.total / props.tamanyoPagina)))
const desde = computed(() => (props.total === 0 ? 0 : (props.pagina - 1) * props.tamanyoPagina + 1))
const hasta = computed(() => Math.min(props.total, props.pagina * props.tamanyoPagina))

const rotulo = computed(() => {
  if (props.total === 0) return 'Sin resultados'
  const cola = props.unidad ? ` ${props.unidad}` : ''
  return `Mostrando ${fmtEnteros.format(desde.value)}–${fmtEnteros.format(hasta.value)} de ${fmtEnteros.format(props.total)}${cola}`
})

/** Máximo 7 números visibles con elisión: `1 … 4 5 6 … 43`. */
const numeros = computed<Array<number | '…'>>(() => {
  const total = paginas.value
  const actual = props.pagina
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  if (actual <= 4) return [1, 2, 3, 4, 5, '…', total]
  if (actual >= total - 3) return [1, '…', total - 4, total - 3, total - 2, total - 1, total]
  return [1, '…', actual - 1, actual, actual + 1, '…', total]
})

function ir(destino: number): void {
  const p = Math.min(paginas.value, Math.max(1, destino))
  if (p !== props.pagina) emit('update:pagina', p)
}
</script>

<template>
  <nav aria-label="Paginación" class="paginacion">
    <p class="rotulo">{{ rotulo }}</p>

    <div class="controles">
      <label class="tamanyo">
        <span>Por página</span>
        <select
          :value="tamanyoPagina"
          @change="emit('update:tamanyoPagina', Number(($event.target as HTMLSelectElement).value))"
        >
          <option v-for="t in tamanyos" :key="t" :value="t">{{ t }}</option>
        </select>
      </label>

      <template v-if="paginas > 1">
        <button
          type="button"
          class="paso"
          aria-label="Página anterior"
          :disabled="pagina <= 1 || cargando"
          @click="ir(pagina - 1)"
        >
          <ChevronLeft :size="16" aria-hidden="true" />
        </button>

        <ul class="numeros" :class="{ atenuado: cargando }">
          <li v-for="(n, i) in numeros" :key="`${n}-${i}`">
            <span v-if="n === '…'" class="elision" aria-hidden="true">…</span>
            <button
              v-else
              type="button"
              class="numero num"
              :class="{ activa: n === pagina }"
              :aria-current="n === pagina ? 'page' : undefined"
              :aria-label="`Página ${n}`"
              @click="ir(n)"
            >
              <LoaderCircle v-if="cargando && n === pagina" :size="14" class="girando" aria-hidden="true" />
              <template v-else>{{ n }}</template>
            </button>
          </li>
        </ul>

        <button
          type="button"
          class="paso"
          aria-label="Página siguiente"
          :disabled="pagina >= paginas || cargando"
          @click="ir(pagina + 1)"
        >
          <ChevronRight :size="16" aria-hidden="true" />
        </button>
      </template>
    </div>

    <span class="oculto-visualmente" aria-live="polite">
      Página {{ pagina }} de {{ paginas }}
    </span>
  </nav>
</template>

<style scoped>
.paginacion {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding-block: var(--sp-3);
}
.rotulo {
  margin: 0;
  font-size: var(--t-caption);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}
.controles {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.tamanyo {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--t-caption);
  color: var(--c-text-3);
}
.tamanyo select {
  height: 32px;
  padding-inline: var(--sp-2);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background-color: var(--c-surface-2);
  color: var(--c-text-1);
  font-family: inherit;
  font-size: var(--t-caption);
}

.numeros {
  display: flex;
  align-items: center;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.numeros.atenuado .numero:not(.activa) {
  opacity: 0.55;
}
.elision {
  display: inline-flex;
  justify-content: center;
  width: 24px;
  color: var(--c-text-3);
}

.numero,
.paso {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  /* Objetivo táctil de 44 px (§10); antes 32. */
  min-width: 44px;
  height: 44px;
  padding-inline: var(--sp-1);
  border: 1px solid transparent;
  border-radius: var(--r-md);
  background: none;
  color: var(--c-text-2);
  font-family: inherit;
  font-size: var(--t-caption);
  font-weight: 600;
  cursor: pointer;
}
.numero:hover:not(.activa),
.paso:hover:not(:disabled) {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}
.numero.activa {
  background-color: var(--c-accent);
  color: var(--c-text-on-fill);
}
.numero.activa:focus-visible {
  outline-color: var(--c-text-1);
}
.paso:disabled {
  color: var(--c-text-disabled);
  cursor: not-allowed;
}

.girando {
  animation: giro 900ms linear infinite;
}
@keyframes giro {
  to {
    rotate: 360deg;
  }
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
