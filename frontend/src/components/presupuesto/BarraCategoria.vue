<script setup lang="ts">
/**
 * Versión compacta de la BudgetBar para una sola temática.
 *
 * Se usa en la lista de temáticas, en la ficha de temática y como sustituto de
 * la barra grande en móvil. El carril mide 8 px y **no** es interactivo: un
 * objetivo de toque de 8 px de alto no existe. Lo interactivo es la fila
 * completa, con sus 48 px.
 *
 * El sobrepaso se sale del 100 % con rayas a 45° hasta un tope visual del 130 %;
 * a partir de ahí solo crece el número, porque una barra de 400 % no informa de
 * nada y rompe la maqueta.
 */
import { computed } from 'vue'
import { CirclePlus, TriangleAlert } from 'lucide-vue-next'

import { aNumero, euros, porcentaje } from '@/lib/formato'
import { colorDeCategoria } from './colores'
import { ETIQUETA_ESTADO, type AsignacionTematica } from './types'

const props = withDefaults(
  defineProps<{
    asignacion: AsignacionTematica
    /** Si se pasa, la fila es un enlace; si no, un botón que emite `activar`. */
    href?: string
    diaActual?: number
    diasDelMes?: number
    /** Oculta el nombre cuando la fila ya está dentro de la ficha de la temática. */
    mostrarNombre?: boolean
  }>(),
  { mostrarNombre: true },
)

const emit = defineEmits<{
  activar: [asignacion: AsignacionTematica]
  asignar: [asignacion: AsignacionTematica]
}>()

const TOPE_VISUAL = 130

const nombre = computed(() => props.asignacion.category.name)
const color = computed(() =>
  colorDeCategoria(props.asignacion.category.color, props.asignacion.category_id),
)
const asignado = computed(() => aNumero(props.asignacion.allocated))
const arrastrado = computed(() => aNumero(props.asignacion.rollover_in))
/** Lo que de verdad hay para gastar este mes: lo asignado más lo que viene del anterior. */
const efectivo = computed(() => asignado.value + arrastrado.value)
const gastado = computed(() => aNumero(props.asignacion.spent))
const sobrepaso = computed(() => aNumero(props.asignacion.overspent))
/** `spent_pct` es una proporción: aquí se pinta en 0-100. */
const consumido = computed(() => (props.asignacion.spent_pct ?? 0) * 100)
const sinAsignacion = computed(() => efectivo.value <= 0)
const sobrepasado = computed(() => props.asignacion.state === 'sobrepasado')

/** Con sobrepaso el carril nominal se encoge para que el rojo quepa en la fila. */
const tope = computed(() =>
  consumido.value > 100 ? Math.min(consumido.value, TOPE_VISUAL) : 100,
)
const anchoCarril = computed(() => `${(100 * 100) / tope.value}%`)
const anchoRelleno = computed(() => `${Math.min(consumido.value, 100)}%`)
const anchoExceso = computed(() => `${Math.max(0, Math.min(consumido.value, TOPE_VISUAL) - 100)}%`)

const marcaRitmo = computed(() => {
  const dia = props.diaActual
  const dias = props.diasDelMes
  if (!dia || !dias || dias <= 0) return null
  return `${Math.min(Math.max(dia / dias, 0), 1) * 100}%`
})

const etiquetaInteractiva = computed(() => (props.href ? 'a' : 'button'))

const textoImportes = computed(() =>
  sinAsignacion.value
    ? `${euros(gastado.value)} · sin asignación`
    : `${euros(gastado.value)} / ${euros(efectivo.value)}`,
)

const descripcion = computed(() => {
  if (sinAsignacion.value) {
    return `${nombre.value}: ${euros(gastado.value)} gastados sin presupuesto asignado.`
  }
  const base = `${nombre.value}: ${euros(gastado.value)} gastados de ${euros(efectivo.value)}, ${porcentaje(consumido.value / 100)}`
  return sobrepasado.value
    ? `${base}. Sobrepasada en ${euros(sobrepaso.value)}.`
    : `${base}.`
})
</script>

<template>
  <div class="fila" :class="{ 'fila--sobrepasada': sobrepasado }">
    <div class="linea-superior">
      <component
        :is="etiquetaInteractiva"
        class="disparador"
        :href="props.href"
        :type="props.href ? undefined : 'button'"
        :aria-label="descripcion"
        @click="emit('activar', props.asignacion)"
      >
        <span class="punto" :style="{ background: color }" aria-hidden="true" />
        <span v-if="props.mostrarNombre" class="nombre">{{ nombre }}</span>
        <span v-if="sobrepasado" class="insignia">
          <TriangleAlert :size="12" aria-hidden="true" />
          {{ ETIQUETA_ESTADO.sobrepasado }}
        </span>
      </component>

      <span class="cifras">
        <span class="importes">{{ textoImportes }}</span>
        <span v-if="!sinAsignacion" class="pct">{{ porcentaje(consumido / 100) }}</span>
      </span>
    </div>

    <!-- El carril es decorativo: todas sus cifras están en el texto de arriba. -->
    <div v-if="!sinAsignacion" class="pista" aria-hidden="true">
      <div class="carril" :style="{ width: anchoCarril }">
        <div
          class="relleno"
          :class="{ 'relleno--completo': consumido >= 100 && !sobrepasado }"
          :style="{ width: anchoRelleno, background: color }"
        />
        <span v-if="marcaRitmo" class="ritmo" :style="{ left: marcaRitmo }" />
      </div>
      <div v-if="sobrepasado" class="exceso" :style="{ width: anchoExceso }" />
    </div>
    <div v-else class="pista pista--vacia" aria-hidden="true">
      <div class="hilo" />
    </div>

    <div class="pie">
      <p v-if="sobrepasado" class="aviso">
        <TriangleAlert :size="14" aria-hidden="true" />
        <span>{{ euros(sobrepaso, { signoSiempre: true }) }} de más</span>
      </p>
      <p v-else-if="arrastrado !== 0" class="nota">
        Incluye {{ euros(arrastrado) }} arrastrados del mes anterior
      </p>
      <button v-if="sinAsignacion" type="button" class="asignar" @click="emit('asignar', props.asignacion)">
        <CirclePlus :size="14" aria-hidden="true" />
        Asignar
      </button>
    </div>
  </div>
</template>

<style scoped>
.fila {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 48px;
  padding: 8px 4px;
  font-family: var(--font-sans, system-ui, sans-serif);
  color: var(--c-text-1);
}

.fila:hover {
  background: var(--c-surface-3);
}

.linea-superior {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

/* Enlace estirado: la fila entera es el objetivo de toque, pero «Asignar» sigue
   siendo un control aparte por encima. */
.disparador {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  font-weight: 500;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}

.disparador::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: var(--r-md, 8px);
}

.disparador:focus-visible {
  outline: none;
}

.disparador:focus-visible::after {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

.punto {
  flex: 0 0 auto;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.nombre {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.insignia {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border-radius: var(--r-full, 999px);
  background: var(--c-negative-wash);
  color: var(--c-negative);
  font-size: var(--t-micro, 0.75rem);
  font-weight: 600;
  white-space: nowrap;
}

.cifras {
  display: inline-flex;
  align-items: baseline;
  gap: 12px;
  flex: 0 0 auto;
  font-variant-numeric: tabular-nums;
}

.importes {
  color: var(--c-text-1);
}

.pct {
  min-width: 3.5em;
  text-align: right;
  color: var(--c-text-2);
}

.pista {
  display: flex;
  align-items: center;
  width: 100%;
}

.carril {
  position: relative;
  height: 8px;
  border-radius: var(--r-bar, 4px);
  background: var(--c-track);
  overflow: visible;
}

.relleno {
  height: 100%;
  border-radius: 4px 0 0 4px;
}

.relleno--completo {
  border-radius: var(--r-bar, 4px);
}

.ritmo {
  position: absolute;
  top: -2px;
  width: 1px;
  height: 12px;
  background: var(--c-text-3);
}

.exceso {
  height: 8px;
  border-radius: 0 4px 4px 0;
  background-color: var(--c-negative-wash);
  background-image: repeating-linear-gradient(
    45deg,
    var(--c-negative) 0 3px,
    transparent 3px 6px
  );
}

.pista--vacia {
  padding: 3px 0;
}

.hilo {
  width: 100%;
  height: 1px;
  background: var(--c-border);
}

.pie {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 0;
}

.pie:empty {
  display: none;
}

.aviso,
.nota {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: var(--t-micro, 0.75rem);
  font-variant-numeric: tabular-nums;
}

.aviso {
  color: var(--c-negative);
  font-weight: 600;
}

.nota {
  color: var(--c-text-3);
}

.asignar {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 44px;
  padding: 0 8px;
  margin-left: auto;
  border: 0;
  border-radius: var(--r-md, 8px);
  background: none;
  color: var(--c-accent-text);
  font: inherit;
  font-size: var(--t-caption, 0.8125rem);
  font-weight: 600;
  cursor: pointer;
}

.asignar:hover {
  text-decoration: underline;
}

.asignar:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

@media (prefers-contrast: more) {
  .carril {
    box-shadow: inset 0 0 0 1px var(--c-border-strong);
  }
}
</style>
