<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { LoaderCircle, Search, SlidersHorizontal, X } from 'lucide-vue-next'
import { useAtajos } from '@/composables/useAtajos'
import EtiquetaCategoria from './EtiquetaCategoria.vue'

export interface ChipFiltro {
  clave: string
  etiqueta: string
  /** Ranura de categoría 1..12 si el chip representa una temática. */
  ranura?: number
}

const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    /** Antirrebote antes de emitir `buscar`. */
    retardo?: number
    minimoCaracteres?: number
    buscando?: boolean
    /** Nº de resultados; se anuncia por aria-live cuando se estabiliza. */
    resultados?: number | null
    /** Nº de filtros aplicados: badge en «Más filtros». */
    filtrosActivos?: number
    chips?: ChipFiltro[]
  }>(),
  {
    placeholder: 'Buscar concepto, comercio o importe…',
    retardo: 250,
    minimoCaracteres: 2,
    resultados: null,
    filtrosActivos: 0,
    chips: () => [],
  },
)

const emit = defineEmits<{
  'update:modelValue': [texto: string]
  buscar: [texto: string]
  limpiar: []
  quitarChip: [clave: string]
  quitarTodos: []
  abrirFiltros: []
}>()

const campo = ref<HTMLInputElement | null>(null)
let reloj: ReturnType<typeof setTimeout> | null = null

/** Si el término parece un importe, también se busca por importe. */
const pareceImporte = computed(() => /^\d{1,7}([.,]\d{1,2})?$/.test(props.modelValue.trim()))

const rotuloAmbito = computed(() => {
  const t = props.modelValue.trim()
  if (!t || t.length < props.minimoCaracteres) return null
  return pareceImporte.value
    ? `Buscando «${t}» en conceptos e importes`
    : `Buscando «${t}» en conceptos y comercios`
})

function alEscribir(valor: string): void {
  emit('update:modelValue', valor)
}

function limpiar(): void {
  emit('update:modelValue', '')
  emit('limpiar')
}

watch(
  () => props.modelValue,
  (valor) => {
    if (reloj !== null) clearTimeout(reloj)
    const t = valor.trim()
    if (t.length > 0 && t.length < props.minimoCaracteres) return
    reloj = setTimeout(() => emit('buscar', t), props.retardo)
  },
)

useAtajos([
  {
    combinacion: '/',
    descripcion: 'Enfocar la búsqueda',
    grupo: 'Buscar',
    accion: () => campo.value?.focus(),
  },
])

defineExpose({ enfocar: () => campo.value?.focus() })
</script>

<template>
  <div role="search" class="barra">
    <div class="fila">
      <div class="caja">
        <Search :size="16" class="afijo" aria-hidden="true" />
        <input
          ref="campo"
          :value="modelValue"
          type="search"
          autocomplete="off"
          :placeholder="placeholder"
          aria-label="Buscar"
          @input="alEscribir(($event.target as HTMLInputElement).value)"
          @keydown.escape="limpiar"
        />
        <LoaderCircle v-if="buscando" :size="16" class="afijo girando" aria-hidden="true" />
        <button
          v-else-if="modelValue"
          type="button"
          class="limpiar toque-44"
          aria-label="Limpiar la búsqueda"
          @click="limpiar"
        >
          <X :size="16" aria-hidden="true" />
        </button>
        <span v-if="resultados !== null && !buscando" class="cuenta num">{{ resultados }}</span>
      </div>

      <slot name="filtros" />

      <button type="button" class="mas-filtros" @click="emit('abrirFiltros')">
        <SlidersHorizontal :size="16" aria-hidden="true" />
        Más filtros
        <span v-if="filtrosActivos > 0" class="badge num">{{ filtrosActivos }}</span>
      </button>

      <div v-if="$slots.acciones" class="acciones"><slot name="acciones" /></div>
    </div>

    <p v-if="rotuloAmbito" class="ambito">{{ rotuloAmbito }}</p>

    <div v-if="chips.length > 0" class="chips">
      <EtiquetaCategoria
        v-for="chip in chips"
        :key="chip.clave"
        :nombre="chip.etiqueta"
        :ranura="chip.ranura ?? 0"
        eliminable
        @quitar="emit('quitarChip', chip.clave)"
      />
      <button type="button" class="quitar-todos" @click="emit('quitarTodos')">Quitar todos</button>
    </div>

    <span class="oculto-visualmente" aria-live="polite">
      {{ resultados === null ? '' : `${resultados} resultados` }}
    </span>
  </div>
</template>

<style scoped>
.barra {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
/* Una sola fila de filtros encima de todo lo que afecta. */
.fila {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  overflow-x: auto;
  scrollbar-width: none;
}
.fila::-webkit-scrollbar {
  display: none;
}

.caja {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex: 1 1 260px;
  min-width: 180px;
  height: 40px;
  padding-inline: var(--sp-3);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background-color: var(--c-surface-2);
}
.caja:hover {
  border-color: var(--c-border-strong);
}
.caja:focus-within {
  border-color: var(--c-accent);
  box-shadow: var(--glow-accent);
}
/* Anillo de foco real (§5, §10): 2 px de acento con 2 px de separación. El
   input hace `outline: none` y el brillo de --glow-accent es de 1 px, por
   debajo del 3:1 exigido al indicador. Se ancla al input para que enfocar un
   botón de dentro de la caja no ilumine el campo entero. */
.caja:has(input:focus-visible) {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}
input {
  flex: 1 1 auto;
  min-width: 0;
  height: 100%;
  border: 0;
  padding: 0;
  background: none;
  color: var(--c-text-1);
  font-family: inherit;
  font-size: var(--t-body);
}
input:focus {
  outline: none;
}
input::-webkit-search-cancel-button {
  display: none;
}
.afijo {
  flex: none;
  color: var(--c-text-3);
}
.limpiar {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: var(--r-full);
  background: none;
  color: var(--c-text-3);
  cursor: pointer;
}
.limpiar:hover {
  color: var(--c-text-1);
}
.cuenta {
  flex: none;
  font-size: var(--t-caption);
  color: var(--c-text-3);
}

.mas-filtros {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  height: 40px;
  padding-inline: var(--sp-3);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
  font-family: inherit;
  font-size: var(--t-body);
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
}
.mas-filtros:hover {
  border-color: var(--c-border-strong);
}
.badge {
  min-width: 18px;
  padding-inline: var(--sp-1);
  border-radius: var(--r-full);
  background-color: var(--c-accent);
  color: var(--c-text-on-fill);
  font-size: var(--t-micro);
  text-align: center;
}
.acciones {
  flex: none;
  display: flex;
  gap: var(--sp-2);
}

.ambito {
  margin: 0;
  font-size: var(--t-caption);
  color: var(--c-text-3);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
}
.quitar-todos {
  border: 0;
  background: none;
  padding: 0;
  color: var(--c-accent-text);
  font-family: inherit;
  font-size: var(--t-caption);
  font-weight: 600;
  cursor: pointer;
}
.quitar-todos:hover {
  text-decoration: underline;
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
