<script setup lang="ts">
/**
 * Tarjeta que envuelve a todos los gráficos.
 *
 * Existe por una regla del sistema de diseño: ninguna cifra vive solo dentro de
 * un gráfico. Aquí están el título, la altura por breakpoint y la tabla gemela
 * con su botón «Ver datos», así que ningún gráfico tiene que reinventarlos.
 */
import { computed, ref } from 'vue'
import { Table2 } from 'lucide-vue-next'

import type { FilaTabla } from './base'

const props = withDefaults(
  defineProps<{
    titulo?: string
    subtitulo?: string
    /** Resumen para lectores de pantalla del lienzo. */
    resumen: string
    columnas?: string[]
    filas?: FilaTabla[]
    /** Alto del área de trazado en píxeles; por defecto el del breakpoint. */
    alto?: number
    /** El donut muestra siempre su tabla al lado: comparar porciones a ojo no vale. */
    tablaFija?: boolean
    /** Índice de la primera columna numérica: se alinea a la derecha con `tabular-nums`. */
    desdeColumnaNumerica?: number
  }>(),
  { tablaFija: false, desdeColumnaNumerica: 1, columnas: () => [], filas: () => [] },
)

const idTabla = `tabla-${Math.random().toString(36).slice(2, 9)}`
const tablaAbierta = ref(false)
const hayTabla = computed(() => props.columnas.length > 0 && props.filas.length > 0)
const mostrarTabla = computed(() => hayTabla.value && (props.tablaFija || tablaAbierta.value))
const estiloLienzo = computed(() => (props.alto ? { '--alto-grafico': `${props.alto}px` } : {}))
</script>

<template>
  <figure class="marco" :class="{ 'marco--con-tabla': props.tablaFija && hayTabla }">
    <div class="cabecera">
      <div class="titulos">
        <figcaption v-if="props.titulo" class="titulo">{{ props.titulo }}</figcaption>
        <p v-if="props.subtitulo" class="subtitulo">{{ props.subtitulo }}</p>
      </div>
      <div class="acciones">
        <slot name="acciones" />
        <button
          v-if="hayTabla && !props.tablaFija"
          type="button"
          class="boton-datos"
          :aria-expanded="tablaAbierta"
          :aria-controls="idTabla"
          @click="tablaAbierta = !tablaAbierta"
        >
          <Table2 :size="16" aria-hidden="true" />
          {{ tablaAbierta ? 'Ocultar datos' : 'Ver datos' }}
        </button>
      </div>
    </div>

    <div class="cuerpo">
      <div class="lienzo" :style="estiloLienzo" role="img" :aria-label="props.resumen">
        <slot />
      </div>

      <div v-if="mostrarTabla" :id="idTabla" class="envoltorio-tabla" tabindex="0">
        <table class="tabla">
          <caption class="solo-lectores">
            {{ props.titulo || 'Datos del gráfico' }}
          </caption>
          <thead>
            <tr>
              <th
                v-for="(columna, i) in props.columnas"
                :key="columna"
                scope="col"
                :class="{ numerica: i >= props.desdeColumnaNumerica }"
              >
                {{ columna }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fila in props.filas" :key="fila.clave">
              <td
                v-for="(celda, i) in fila.celdas"
                :key="i"
                :class="{ numerica: i >= props.desdeColumnaNumerica }"
              >
                {{ celda }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </figure>
</template>

<style scoped>
.marco {
  --alto-grafico: 220px;
  margin: 0;
  padding: 16px;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-xl, 16px);
  color: var(--c-text-1);
  font-family: var(--font-sans, system-ui, sans-serif);
}

@media (min-width: 768px) {
  .marco {
    --alto-grafico: 260px;
  }
}

@media (min-width: 1024px) {
  .marco {
    --alto-grafico: 280px;
  }
}

.cabecera {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.titulo {
  margin: 0;
  font-size: var(--t-h2, 1.25rem);
  line-height: 1.3;
  font-weight: 600;
  color: var(--c-text-1);
}

.subtitulo {
  margin: 4px 0 0;
  font-size: var(--t-sm, 0.875rem);
  color: var(--c-text-2);
}

.acciones {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.boton-datos {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 44px;
  padding: 0 12px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md, 10px);
  background: transparent;
  color: var(--c-text-2);
  font: inherit;
  font-size: var(--t-sm, 0.875rem);
  cursor: pointer;
}

.boton-datos:hover {
  background: var(--c-surface-3);
  color: var(--c-text-1);
}

.boton-datos:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

.cuerpo {
  display: grid;
  gap: 16px;
}

.marco--con-tabla .cuerpo {
  grid-template-columns: 1fr;
}

@media (min-width: 768px) {
  .marco--con-tabla .cuerpo {
    grid-template-columns: minmax(0, 1fr) minmax(200px, 320px);
    align-items: center;
  }
}

.lienzo {
  position: relative;
  height: var(--alto-grafico);
  min-width: 0;
}

.envoltorio-tabla {
  overflow-x: auto;
  scroll-margin-top: 80px;
}

.envoltorio-tabla:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

.tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-sm, 0.875rem);
}

.tabla th,
.tabla td {
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--c-border-soft);
  white-space: nowrap;
}

.tabla th {
  color: var(--c-text-3);
  font-weight: 500;
}

.tabla td {
  color: var(--c-text-1);
}

.numerica {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.solo-lectores {
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
