<script setup lang="ts">
import { computed, type Component } from 'vue'
import { X } from 'lucide-vue-next'

const props = withDefaults(
  defineProps<{
    nombre: string
    /**
     * Ranura persistente de la temática, 1..12. `0` es «Otros»: gris, nunca un
     * hue 13. Las subcategorías heredan la ranura de la madre.
     */
    ranura: number
    /** Nombre de la temática madre; se pinta `Madre · Hija`. */
    madre?: string
    /** Nivel de subcategoría 0..3: aclara el hue sin cambiarlo. */
    nivel?: number
    icono?: Component
    eliminable?: boolean
    seleccionable?: boolean
    seleccionada?: boolean
    tamanyo?: 'sm' | 'md'
  }>(),
  { nivel: 0, tamanyo: 'md' },
)

const emit = defineEmits<{ quitar: []; alternar: [valor: boolean] }>()

/** Mezcla ordinal dentro de la temática: 100, 78, 60 y 46 % sobre el carril. */
const MEZCLAS = [100, 78, 60, 46]

const color = computed(() => {
  const base = props.ranura >= 1 && props.ranura <= 12 ? `var(--c-cat-${props.ranura})` : 'var(--c-cat-other)'
  const mezcla = MEZCLAS[Math.min(props.nivel, MEZCLAS.length - 1)]
  return mezcla === 100 ? base : `color-mix(in oklab, ${base} ${mezcla}%, var(--c-track))`
})
</script>

<template>
  <component
    :is="seleccionable && !eliminable ? 'button' : 'span'"
    class="chip"
    :class="[`t-${tamanyo}`, { seleccionada, pulsable: seleccionable }]"
    :type="seleccionable ? 'button' : undefined"
    :aria-pressed="seleccionable ? seleccionada : undefined"
    :style="{ '--hue': color }"
    @click="seleccionable && emit('alternar', !seleccionada)"
  >
    <component :is="icono" v-if="icono" :size="14" aria-hidden="true" class="icono" />
    <span v-else class="punto" aria-hidden="true" />
    <span class="nombre">
      <span v-if="madre" class="madre">{{ madre }} · </span>{{ nombre }}
    </span>
    <button
      v-if="eliminable"
      type="button"
      class="quitar toque-44"
      :aria-label="`Quitar filtro ${nombre}`"
      @click.stop="emit('quitar')"
    >
      <X :size="16" aria-hidden="true" />
    </button>
  </component>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  max-width: 100%;
  border: 1px solid var(--c-border-soft);
  border-radius: var(--r-full);
  background-color: var(--c-surface-3);
  /* El texto NUNCA lleva el hue de la categoría: el color vive en el punto. */
  color: var(--c-text-1);
  font-family: inherit;
  font-weight: 500;
  text-align: left;
}
.t-md {
  height: 24px;
  padding-inline: var(--sp-2) var(--sp-3);
  font-size: var(--t-caption);
}
.t-sm {
  height: 20px;
  padding-inline: var(--sp-1) var(--sp-2);
  font-size: var(--t-micro);
}
.pulsable {
  position: relative;
  cursor: pointer;
  transition: border-color var(--dur-instant) var(--ease-in-out);
}
.pulsable:hover {
  border-color: var(--c-border-strong);
}
.seleccionada {
  background-color: var(--c-accent-wash);
  border-color: var(--c-accent);
}

.punto {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: var(--r-full);
  background-color: var(--hue);
}
.icono {
  flex: none;
  color: var(--hue);
}
.nombre {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.madre {
  color: var(--c-text-3);
}

.quitar {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  margin-right: calc(-1 * var(--sp-1));
  border: 0;
  border-radius: var(--r-full);
  background: none;
  color: var(--c-text-3);
  cursor: pointer;
}
.quitar:hover {
  color: var(--c-text-1);
}
</style>
