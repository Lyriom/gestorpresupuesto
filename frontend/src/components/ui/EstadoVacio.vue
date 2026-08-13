<script setup lang="ts">
import { computed, type Component } from 'vue'
import { CircleAlert, FilterX, Inbox, SearchX } from 'lucide-vue-next'

export type TipoEstadoVacio = 'primer-uso' | 'sin-filtros' | 'sin-busqueda' | 'error'

const props = withDefaults(
  defineProps<{
    /** Los cuatro vacíos son distintos y dicen cosas distintas (§5.14). */
    tipo?: TipoEstadoVacio
    titulo: string
    descripcion?: string
    /** Sustituye al icono por defecto del tipo. */
    icono?: Component
    /** Nivel real del encabezado, para no romper la jerarquía de la vista. */
    nivel?: 2 | 3 | 4
    /** Término buscado o criterio aplicado, que se repite al usuario. */
    criterio?: string
  }>(),
  { tipo: 'primer-uso', nivel: 3 },
)

const ICONOS: Record<TipoEstadoVacio, Component> = {
  'primer-uso': Inbox,
  'sin-filtros': FilterX,
  'sin-busqueda': SearchX,
  error: CircleAlert,
}

const iconoFinal = computed(() => props.icono ?? ICONOS[props.tipo])
</script>

<template>
  <div class="vacio" :class="{ 'es-error': tipo === 'error' }" role="status">
    <component :is="iconoFinal" :size="32" :stroke-width="1.5" aria-hidden="true" class="icono" />
    <component :is="`h${nivel}`" class="titulo">{{ titulo }}</component>
    <p v-if="descripcion" class="descripcion">{{ descripcion }}</p>
    <p v-if="criterio" class="criterio">{{ criterio }}</p>
    <div v-if="$slots.accion" class="acciones"><slot name="accion" /></div>
    <div v-if="$slots.ayuda" class="ayuda"><slot name="ayuda" /></div>
  </div>
</template>

<style scoped>
.vacio {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-3);
  max-width: 42ch;
  margin-inline: auto;
  padding-block: var(--sp-12);
  text-align: center;
}
.icono {
  color: var(--c-text-3);
}
.es-error .icono {
  color: var(--c-negative);
}
.titulo {
  margin: 0;
  font-size: var(--t-h3);
  font-weight: 600;
  line-height: var(--t-h3-lh);
  color: var(--c-text-1);
}
.descripcion {
  margin: 0;
  font-size: var(--t-sm);
  line-height: var(--t-sm-lh);
  color: var(--c-text-2);
}
.criterio {
  margin: 0;
  font-size: var(--t-caption);
  color: var(--c-text-3);
}
.acciones {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--sp-2);
  margin-top: var(--sp-1);
}
</style>
