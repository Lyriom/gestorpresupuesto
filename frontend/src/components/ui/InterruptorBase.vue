<script setup lang="ts">
import { useId } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    etiqueta: string
    descripcion?: string
    deshabilitado?: boolean
    /** Oculta la etiqueta visualmente; sigue leyéndose con lector de pantalla. */
    etiquetaOculta?: boolean
    tamanyo?: 'sm' | 'md'
  }>(),
  { tamanyo: 'md' },
)

const emit = defineEmits<{ 'update:modelValue': [valor: boolean] }>()

const idDescripcion = `${useId()}-desc`

function alternar(): void {
  if (props.deshabilitado) return
  emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <div class="fila" :class="{ inactivo: deshabilitado }">
    <button
      type="button"
      role="switch"
      class="interruptor toque-44"
      :class="[`t-${tamanyo}`, { activo: modelValue }]"
      :aria-checked="modelValue"
      :aria-disabled="deshabilitado ? 'true' : undefined"
      :aria-describedby="descripcion ? idDescripcion : undefined"
      :aria-label="etiquetaOculta ? etiqueta : undefined"
      @click="alternar"
    >
      <span class="pomo" aria-hidden="true" />
    </button>
    <div v-if="!etiquetaOculta" class="textos">
      <span class="titulo" @click="alternar">{{ etiqueta }}</span>
      <span v-if="descripcion" :id="idDescripcion" class="ayuda">{{ descripcion }}</span>
    </div>
  </div>
</template>

<style scoped>
.fila {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
}
.textos {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.titulo {
  font-size: var(--t-body);
  color: var(--c-text-1);
  cursor: pointer;
}
.ayuda {
  font-size: var(--t-caption);
  color: var(--c-text-3);
}

.interruptor {
  flex: none;
  display: inline-flex;
  align-items: center;
  padding: 2px;
  border: 1px solid var(--c-border-strong);
  border-radius: var(--r-full);
  background-color: var(--c-track);
  cursor: pointer;
  transition: background-color var(--dur-instant) var(--ease-in-out);
}
.t-md {
  width: 44px;
  height: 24px;
}
.t-sm {
  width: 36px;
  height: 20px;
}

.pomo {
  display: block;
  aspect-ratio: 1;
  height: 100%;
  border-radius: var(--r-full);
  background-color: var(--c-text-2);
  transition:
    translate var(--dur-instant) var(--ease-in-out),
    background-color var(--dur-instant) var(--ease-in-out);
}

.activo {
  background-color: var(--c-accent);
  border-color: transparent;
}
.activo .pomo {
  background-color: var(--c-text-on-fill);
}
.t-md.activo .pomo {
  translate: 20px 0;
}
.t-sm.activo .pomo {
  translate: 16px 0;
}

.inactivo .titulo,
.inactivo .ayuda {
  color: var(--c-text-disabled);
}
.inactivo .titulo {
  cursor: not-allowed;
}
.interruptor[aria-disabled='true'] {
  cursor: not-allowed;
  background-color: var(--c-surface-3);
}
.interruptor[aria-disabled='true'] .pomo {
  background-color: var(--c-text-disabled);
}
</style>
