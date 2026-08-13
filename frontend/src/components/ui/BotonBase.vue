<script setup lang="ts">
import { computed, type Component } from 'vue'
import { LoaderCircle } from 'lucide-vue-next'

export type VarianteBoton =
  | 'primaria'
  | 'secundaria'
  | 'fantasma'
  | 'contorno'
  | 'peligro'
  | 'peligro-fantasma'
  | 'enlace'

export type TamanyoBoton = 'sm' | 'md' | 'lg'

const props = withDefaults(
  defineProps<{
    variante?: VarianteBoton
    tamanyo?: TamanyoBoton
    /** Icono Lucide a la izquierda de la etiqueta. */
    icono?: Component
    /** Icono a la derecha; típicamente un chevron. */
    iconoFinal?: Component
    contador?: number | null
    cargando?: boolean
    deshabilitado?: boolean
    anchoCompleto?: boolean
    /** Sin etiqueta visible: obliga a `etiquetaAccesible`. */
    soloIcono?: boolean
    etiquetaAccesible?: string
    tipo?: 'button' | 'submit' | 'reset'
    /** Si se pasa, se pinta un `<a>` en lugar de un `<button>`. */
    href?: string
  }>(),
  {
    variante: 'secundaria',
    tamanyo: 'md',
    tipo: 'button',
    contador: null,
  },
)

const inactivo = computed(() => props.deshabilitado || props.cargando)
</script>

<template>
  <component
    :is="href ? 'a' : 'button'"
    class="boton"
    :class="[
      `v-${variante}`,
      `t-${tamanyo}`,
      { 'ancho-completo': anchoCompleto, 'solo-icono': soloIcono },
    ]"
    :type="href ? undefined : tipo"
    :href="href"
    :disabled="href ? undefined : inactivo"
    :aria-disabled="inactivo ? 'true' : undefined"
    :aria-busy="cargando ? 'true' : undefined"
    :aria-label="etiquetaAccesible"
  >
    <span v-if="cargando" class="girando" aria-hidden="true">
      <LoaderCircle :size="16" />
    </span>
    <!-- El contenido se mantiene en el DOM durante la carga para que el botón
         no cambie de ancho. -->
    <span class="contenido" :class="{ oculto: cargando }">
      <component :is="icono" v-if="icono" :size="16" aria-hidden="true" />
      <span v-if="!soloIcono" class="etiqueta"><slot /></span>
      <span v-if="contador !== null" class="contador num">{{ contador }}</span>
      <component :is="iconoFinal" v-if="iconoFinal" :size="16" aria-hidden="true" />
    </span>
  </component>
</template>

<style scoped>
.boton {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  border: 1px solid transparent;
  border-radius: var(--r-md);
  font-family: inherit;
  font-size: var(--t-body);
  font-weight: 600;
  line-height: 1;
  text-decoration: none;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background-color var(--dur-instant) var(--ease-in-out),
    border-color var(--dur-instant) var(--ease-in-out),
    color var(--dur-instant) var(--ease-in-out),
    translate var(--dur-instant) var(--ease-in-out);
}

/* Objetivo táctil de 44 px sin agrandar el pintado. */
.boton::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  width: max(100%, 44px);
  height: max(100%, 44px);
  translate: -50% -50%;
}

.contenido {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
}
.contenido.oculto {
  visibility: hidden;
}
.girando {
  position: absolute;
  display: inline-flex;
  animation: giro 900ms linear infinite;
}
@keyframes giro {
  to {
    rotate: 360deg;
  }
}

.t-sm {
  height: 32px;
  padding-inline: var(--sp-3);
  font-size: var(--t-sm);
}
.t-md {
  height: 40px;
  padding-inline: var(--sp-4);
}
.t-lg {
  height: 48px;
  padding-inline: var(--sp-5);
}
.solo-icono.t-sm {
  width: 32px;
  padding-inline: 0;
}
.solo-icono.t-md {
  width: 40px;
  padding-inline: 0;
}
.solo-icono.t-lg {
  width: 48px;
  padding-inline: 0;
}
.ancho-completo {
  width: 100%;
}

.contador {
  min-width: 18px;
  padding-inline: var(--sp-1);
  border-radius: var(--r-full);
  background-color: color-mix(in oklab, currentcolor 16%, transparent);
  font-size: var(--t-micro);
  text-align: center;
}

/* --- Variantes ---------------------------------------------------------- */
.v-primaria {
  background-color: var(--c-accent);
  color: var(--c-text-on-fill);
}
.v-primaria:hover:not([aria-disabled='true']) {
  background-color: var(--c-accent-hover);
}
.v-primaria:active:not([aria-disabled='true']) {
  background-color: var(--c-accent-press);
  translate: 0 0.5px;
}
/* Sobre relleno de acento el anillo pasa a --c-text-1 para no perder contraste. */
.v-primaria:focus-visible,
.v-peligro:focus-visible {
  outline-color: var(--c-text-1);
}

.v-secundaria {
  background-color: var(--c-surface-3);
  border-color: var(--c-border);
  color: var(--c-text-1);
}
.v-secundaria:hover:not([aria-disabled='true']) {
  border-color: var(--c-border-strong);
  background-color: color-mix(in oklab, var(--c-surface-3) 88%, var(--c-text-1));
}

.v-fantasma {
  background-color: transparent;
  color: var(--c-text-2);
}
.v-fantasma:hover:not([aria-disabled='true']) {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}

.v-contorno {
  background-color: transparent;
  border-color: var(--c-border-strong);
  color: var(--c-text-1);
}
.v-contorno:hover:not([aria-disabled='true']) {
  background-color: var(--c-surface-3);
}

.v-peligro {
  background-color: var(--c-negative);
  color: var(--c-text-on-fill);
}
.v-peligro:hover:not([aria-disabled='true']) {
  background-color: color-mix(in oklab, var(--c-negative) 88%, var(--c-text-1));
}

.v-peligro-fantasma {
  background-color: transparent;
  color: var(--c-negative);
}
.v-peligro-fantasma:hover:not([aria-disabled='true']) {
  background-color: var(--c-negative-wash);
}

.v-enlace {
  height: auto;
  padding: 0;
  background-color: transparent;
  color: var(--c-accent-text);
}
.v-enlace:hover:not([aria-disabled='true']) {
  text-decoration: underline;
}

/* --- Deshabilitado ------------------------------------------------------ */
.boton[aria-disabled='true'] {
  cursor: not-allowed;
  translate: none;
}
.boton[aria-disabled='true']:not(.v-fantasma):not(.v-enlace):not(.v-peligro-fantasma) {
  background-color: var(--c-surface-3);
  border-color: var(--c-border);
  color: var(--c-text-disabled);
}
.v-fantasma[aria-disabled='true'],
.v-enlace[aria-disabled='true'],
.v-peligro-fantasma[aria-disabled='true'] {
  color: var(--c-text-disabled);
}
</style>
