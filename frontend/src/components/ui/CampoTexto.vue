<script setup lang="ts">
import { computed, ref, useId, type Component } from 'vue'
import { Check, CircleAlert, LoaderCircle } from 'lucide-vue-next'

const props = withDefaults(
  defineProps<{
    modelValue: string
    /** Obligatoria: el placeholder nunca sustituye a la etiqueta. */
    etiqueta: string
    tipo?: 'text' | 'email' | 'password' | 'search' | 'tel' | 'url'
    placeholder?: string
    ayuda?: string
    /** Si viene, sustituye a la ayuda y marca el campo como inválido. */
    error?: string
    correcto?: boolean
    cargando?: boolean
    deshabilitado?: boolean
    soloLectura?: boolean
    requerido?: boolean
    etiquetaOculta?: boolean
    /** Usa la pila monoespaciada: solo para NIF, IBAN o nº de factura. */
    monoespaciado?: boolean
    maxLongitud?: number
    contador?: boolean
    iconoInicio?: Component
    /** Unidad o texto fijo a la derecha, fuera del área de texto. */
    sufijo?: string
    autocompletar?: string
    /** Ancho en caracteres cuando el campo no debe ocupar toda la fila. */
    ancho?: string
  }>(),
  { tipo: 'text' },
)

const emit = defineEmits<{
  'update:modelValue': [valor: string]
  enter: []
}>()

const base = useId()
const idCampo = `${base}-campo`
const idAyuda = `${base}-ayuda`
const campo = ref<HTMLInputElement | null>(null)

const descrito = computed(() => (props.error || props.ayuda ? idAyuda : undefined))
const restantes = computed(() =>
  props.maxLongitud ? props.maxLongitud - props.modelValue.length : null,
)

defineExpose({
  enfocar: () => campo.value?.focus(),
})
</script>

<template>
  <div class="campo" :style="ancho ? { maxWidth: ancho } : undefined">
    <div class="fila-etiqueta">
      <label :for="idCampo" :class="{ 'oculto-visualmente': etiquetaOculta }">
        {{ etiqueta }}<span v-if="requerido" class="requerido" aria-hidden="true"> *</span>
      </label>
      <span v-if="contador && maxLongitud" class="contador num" :class="{ pasado: restantes! < 0 }">
        {{ modelValue.length }}/{{ maxLongitud }}
      </span>
    </div>

    <div
      class="caja"
      :class="{
        malo: !!error,
        inactivo: deshabilitado,
        lectura: soloLectura,
        mono: monoespaciado,
      }"
    >
      <component :is="iconoInicio" v-if="iconoInicio" :size="16" aria-hidden="true" class="afijo" />
      <input
        :id="idCampo"
        ref="campo"
        :value="modelValue"
        :type="tipo"
        :placeholder="placeholder"
        :disabled="deshabilitado"
        :readonly="soloLectura"
        :required="requerido"
        :maxlength="maxLongitud"
        :autocomplete="autocompletar"
        :aria-invalid="error ? 'true' : undefined"
        :aria-describedby="descrito"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
        @keydown.enter="emit('enter')"
      />
      <LoaderCircle v-if="cargando" :size="16" class="afijo girando" aria-hidden="true" />
      <CircleAlert v-else-if="error" :size="16" class="afijo malo-icono" aria-hidden="true" />
      <Check v-else-if="correcto" :size="16" class="afijo bien-icono" aria-hidden="true" />
      <span v-else-if="sufijo" class="afijo sufijo">{{ sufijo }}</span>
    </div>

    <p v-if="error" :id="idAyuda" class="mensaje malo-texto" aria-live="polite">{{ error }}</p>
    <p v-else-if="ayuda" :id="idAyuda" class="mensaje">{{ ayuda }}</p>
  </div>
</template>

<style scoped>
.campo {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.fila-etiqueta {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
}
label {
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.requerido {
  color: var(--c-negative);
}
.contador {
  font-size: var(--t-caption);
  color: var(--c-text-3);
}
.contador.pasado {
  color: var(--c-negative);
}

.caja {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  height: 40px;
  padding-inline: var(--sp-3);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background-color: var(--c-surface-2);
  color: var(--c-text-3);
  transition:
    border-color var(--dur-instant) var(--ease-in-out),
    box-shadow var(--dur-instant) var(--ease-in-out);
}
.caja:hover:not(.inactivo):not(.lectura) {
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
.caja.malo {
  border-color: var(--c-negative);
}
.caja.inactivo {
  background-color: var(--c-surface);
  border-color: var(--c-border-soft);
}
.caja.lectura {
  background-color: var(--c-surface);
  border-color: transparent;
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
.mono input {
  font-family: var(--font-mono);
}
input:focus {
  outline: none;
}
input:disabled {
  color: var(--c-text-disabled);
  cursor: not-allowed;
}

.afijo {
  flex: none;
  color: var(--c-text-3);
}
.sufijo {
  font-size: var(--t-sm);
}
.malo-icono {
  color: var(--c-negative);
}
.bien-icono {
  color: var(--c-positive);
}
.girando {
  animation: giro 900ms linear infinite;
}
@keyframes giro {
  to {
    rotate: 360deg;
  }
}

.mensaje {
  margin: 0;
  font-size: var(--t-caption);
  line-height: var(--t-caption-lh);
  color: var(--c-text-3);
}
.malo-texto {
  color: var(--c-negative);
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
