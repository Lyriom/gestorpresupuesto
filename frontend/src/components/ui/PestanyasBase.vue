<script setup lang="ts">
import { nextTick, onMounted, ref, useId, watch } from 'vue'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { useResizeObserver } from '@vueuse/core'

export interface Pestanya {
  valor: string | number
  etiqueta: string
  contador?: number
  deshabilitada?: boolean
}

const props = defineProps<{
  modelValue: string | number
  pestanyas: Pestanya[]
  /** aria-label de la lista de pestañas. */
  etiqueta: string
}>()

const emit = defineEmits<{ 'update:modelValue': [valor: string | number] }>()

const base = useId()
const idPestanya = (v: string | number) => `${base}-tab-${v}`
const idPanel = `${base}-panel`

const barra = ref<HTMLElement | null>(null)
const indicador = ref({ left: 0, width: 0 })
const desbordado = ref(false)
const enfocada = ref<string | number>(props.modelValue)

function recolocar(): void {
  const contenedor = barra.value
  if (!contenedor) return
  const activa = contenedor.querySelector<HTMLElement>('[aria-selected="true"]')
  if (!activa) return
  indicador.value = { left: activa.offsetLeft, width: activa.offsetWidth }
  desbordado.value = contenedor.scrollWidth > contenedor.clientWidth + 1
}

function indiceDe(valor: string | number): number {
  return props.pestanyas.findIndex((p) => p.valor === valor)
}

/** Activación manual: las flechas mueven el foco, no la selección. */
function moverFoco(delta: number): void {
  const total = props.pestanyas.length
  if (total === 0) return
  let i = indiceDe(enfocada.value)
  for (let intento = 0; intento < total; intento++) {
    i = (i + delta + total) % total
    if (!props.pestanyas[i].deshabilitada) break
  }
  enfocada.value = props.pestanyas[i].valor
  void nextTick(() => {
    barra.value?.querySelector<HTMLElement>(`#${CSS.escape(idPestanya(enfocada.value))}`)?.focus()
  })
}

function alTeclear(evento: KeyboardEvent): void {
  switch (evento.key) {
    case 'ArrowRight':
      evento.preventDefault()
      moverFoco(1)
      break
    case 'ArrowLeft':
      evento.preventDefault()
      moverFoco(-1)
      break
    case 'Home': {
      evento.preventDefault()
      const primera = props.pestanyas.find((p) => !p.deshabilitada)
      if (primera) enfocada.value = primera.valor
      void nextTick(() => moverFoco(0))
      break
    }
    case 'End': {
      evento.preventDefault()
      const ultima = [...props.pestanyas].reverse().find((p) => !p.deshabilitada)
      if (ultima) enfocada.value = ultima.valor
      void nextTick(() => moverFoco(0))
      break
    }
  }
}

function activar(p: Pestanya): void {
  if (p.deshabilitada) return
  enfocada.value = p.valor
  emit('update:modelValue', p.valor)
}

function desplazar(delta: number): void {
  barra.value?.scrollBy({ left: delta, behavior: 'smooth' })
}

onMounted(recolocar)
useResizeObserver(barra, recolocar)
watch(() => [props.modelValue, props.pestanyas.length], () => void nextTick(recolocar))
</script>

<template>
  <div class="pestanyas">
    <div class="fila">
      <button
        v-if="desbordado"
        type="button"
        class="flecha"
        aria-label="Desplazar pestañas a la izquierda"
        @click="desplazar(-160)"
      >
        <ChevronLeft :size="16" aria-hidden="true" />
      </button>

      <div ref="barra" role="tablist" :aria-label="etiqueta" class="barra" @keydown="alTeclear">
        <button
          v-for="p in pestanyas"
          :id="idPestanya(p.valor)"
          :key="p.valor"
          type="button"
          role="tab"
          class="pestanya"
          :aria-selected="p.valor === modelValue"
          :aria-controls="idPanel"
          :aria-disabled="p.deshabilitada ? 'true' : undefined"
          :tabindex="p.valor === enfocada ? 0 : -1"
          @click="activar(p)"
          @keydown.enter.prevent="activar(p)"
          @keydown.space.prevent="activar(p)"
        >
          {{ p.etiqueta }}
          <span v-if="p.contador !== undefined" class="contador num">{{ p.contador }}</span>
        </button>
        <span
          class="indicador"
          aria-hidden="true"
          :style="{ translate: `${indicador.left}px 0`, width: `${indicador.width}px` }"
        />
      </div>

      <button
        v-if="desbordado"
        type="button"
        class="flecha"
        aria-label="Desplazar pestañas a la derecha"
        @click="desplazar(160)"
      >
        <ChevronRight :size="16" aria-hidden="true" />
      </button>
    </div>

    <!-- El panel toma su nombre de la pestaña activa (§5.10). -->
    <div
      :id="idPanel"
      role="tabpanel"
      :aria-labelledby="idPestanya(modelValue)"
      tabindex="-1"
      class="panel"
    >
      <slot />
    </div>
  </div>
</template>

<style scoped>
.fila {
  display: flex;
  align-items: center;
  border-bottom: 1px solid var(--c-border);
}
.barra {
  position: relative;
  display: flex;
  flex: 1 1 auto;
  overflow-x: auto;
  scrollbar-width: none;
  /* Desvanecido lateral cuando hay desbordamiento en táctil. */
  mask-image: linear-gradient(90deg, transparent 0, #000 12px, #000 calc(100% - 12px), transparent);
}
.barra::-webkit-scrollbar {
  display: none;
}

.pestanya {
  position: relative;
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  height: 40px;
  padding-inline: var(--sp-3);
  border: 0;
  background: none;
  color: var(--c-text-2);
  font-family: inherit;
  font-size: var(--t-body);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: color var(--dur-instant) var(--ease-in-out);
}
.pestanya:hover:not([aria-disabled='true']) {
  color: var(--c-text-1);
  box-shadow: inset 0 -2px 0 0 color-mix(in oklab, var(--c-accent) 30%, transparent);
}
.pestanya[aria-selected='true'] {
  color: var(--c-text-1);
  font-weight: 600;
}
.pestanya[aria-disabled='true'] {
  color: var(--c-text-disabled);
  cursor: not-allowed;
}
.contador {
  min-width: 18px;
  padding-inline: var(--sp-1);
  border-radius: var(--r-full);
  background-color: var(--c-surface-3);
  font-size: var(--t-micro);
  text-align: center;
}

.indicador {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2px;
  background-color: var(--c-accent);
  transition:
    translate var(--dur-base) var(--ease-in-out),
    width var(--dur-base) var(--ease-in-out);
}

.flecha {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 40px;
  border: 0;
  background: none;
  color: var(--c-text-3);
  cursor: pointer;
}
.flecha:hover {
  color: var(--c-text-1);
}
@media (max-width: 767px) {
  .flecha {
    display: none;
  }
}

.panel {
  padding-top: var(--sp-4);
}
.panel:focus-visible {
  outline-offset: -2px;
}
</style>
