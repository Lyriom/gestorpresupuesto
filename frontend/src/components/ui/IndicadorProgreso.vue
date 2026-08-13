<script setup lang="ts">
import { computed } from 'vue'
import { porcentaje } from '@/lib/formato'

const props = withDefaults(
  defineProps<{
    /** Valor actual. Con `indeterminado` se ignora. */
    valor?: number
    maximo?: number
    etiqueta: string
    /** Texto de estado que se anuncia por aria-live (p. ej. «Subiendo 2 de 5»). */
    estado?: string
    indeterminado?: boolean
    tono?: 'accent' | 'positive' | 'negative' | 'warning' | 'info'
    alto?: number
    mostrarTexto?: boolean
  }>(),
  { valor: 0, maximo: 100, tono: 'accent', alto: 8 },
)

const proporcion = computed(() => {
  if (props.maximo <= 0) return 0
  return Math.min(1, Math.max(0, props.valor / props.maximo))
})
const texto = computed(() => porcentaje(proporcion.value))
</script>

<template>
  <div class="envoltorio">
    <div v-if="mostrarTexto || estado" class="cabecera">
      <span class="etiqueta">{{ etiqueta }}</span>
      <span v-if="mostrarTexto && !indeterminado" class="num valor">{{ texto }}</span>
    </div>
    <div
      class="carril"
      :class="`tono-${tono}`"
      :style="{ height: `${alto}px` }"
      role="progressbar"
      :aria-label="etiqueta"
      :aria-valuemin="indeterminado ? undefined : 0"
      :aria-valuemax="indeterminado ? undefined : maximo"
      :aria-valuenow="indeterminado ? undefined : valor"
      :aria-valuetext="indeterminado ? undefined : texto"
    >
      <div
        class="relleno"
        :class="{ indeterminado }"
        :style="indeterminado ? undefined : { width: `${proporcion * 100}%` }"
      />
    </div>
    <p v-if="estado" class="estado" aria-live="polite">{{ estado }}</p>
  </div>
</template>

<style scoped>
.envoltorio {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.cabecera {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
}
.etiqueta {
  font-size: var(--t-caption);
  color: var(--c-text-2);
}
.valor {
  font-size: var(--t-caption);
  color: var(--c-text-1);
  font-weight: 600;
}
.estado {
  margin: 0;
  font-size: var(--t-caption);
  color: var(--c-text-3);
}

.carril {
  overflow: hidden;
  border-radius: var(--r-bar);
  background-color: var(--c-track);
}
.relleno {
  height: 100%;
  border-radius: var(--r-bar);
  background-color: var(--tono);
  transition: width var(--dur-bar) var(--ease-emphasis);
}
.relleno.indeterminado {
  width: 40%;
  animation: vaiven 1.4s var(--ease-in-out) infinite;
}
@keyframes vaiven {
  0% {
    translate: -100% 0;
  }
  100% {
    translate: 250% 0;
  }
}

.tono-accent {
  --tono: var(--c-accent);
}
.tono-positive {
  --tono: var(--c-positive);
}
.tono-negative {
  --tono: var(--c-negative);
}
.tono-warning {
  --tono: var(--c-warning);
}
.tono-info {
  --tono: var(--c-info);
}
</style>
