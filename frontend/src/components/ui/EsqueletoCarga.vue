<script setup lang="ts">
import { computed } from 'vue'

/** Geometrías reales del contenido que sustituye (§5.13). */
const GEOMETRIA = {
  texto: { height: '14px', width: '100%', radius: 'var(--r-sm)' },
  importe: { height: '15px', width: '88px', radius: 'var(--r-sm)' },
  avatar: { height: '32px', width: '32px', radius: 'var(--r-full)' },
  barra: { height: '40px', width: '100%', radius: 'var(--r-bar)' },
  bloque: { height: '44px', width: '100%', radius: 'var(--r-lg)' },
} as const

const props = withDefaults(
  defineProps<{
    variante?: keyof typeof GEOMETRIA
    /** Nunca más de 8: por encima, el esqueleto miente sobre el contenido. */
    lineas?: number
    ancho?: string
    alto?: string
    /** Texto oculto que anuncia qué se está cargando. */
    anuncio?: string
  }>(),
  { variante: 'texto', lineas: 1, anuncio: 'Cargando' },
)

const geo = computed(() => GEOMETRIA[props.variante])
const cuantas = computed(() => Math.min(8, Math.max(1, props.lineas)))
</script>

<template>
  <div class="pila" aria-busy="true" role="presentation">
    <span class="oculto-visualmente">{{ anuncio }}</span>
    <span
      v-for="n in cuantas"
      :key="n"
      class="esqueleto"
      :style="{
        height: alto ?? geo.height,
        width: n === cuantas && cuantas > 1 && !ancho ? '62%' : (ancho ?? geo.width),
        borderRadius: geo.radius,
      }"
    />
  </div>
</template>

<style scoped>
.pila {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.esqueleto {
  display: block;
}
.oculto-visualmente {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}
</style>
