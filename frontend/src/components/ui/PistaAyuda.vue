<script setup lang="ts">
import { onBeforeUnmount, ref, useId } from 'vue'

const props = withDefaults(
  defineProps<{
    /** Nunca contiene información que no esté en otro sitio (§5.12). */
    texto: string
    posicion?: 'arriba' | 'abajo' | 'izquierda' | 'derecha'
    /** 400 ms al abrir; 0 en la lateral colapsada, donde el tooltip es la etiqueta. */
    retardo?: number
  }>(),
  { posicion: 'arriba', retardo: 400 },
)

const visible = ref(false)
const volteado = ref(false)
const disparador = ref<HTMLElement | null>(null)
const idPista = `${useId()}-pista`
let temporizador: ReturnType<typeof setTimeout> | null = null

function cancelar(): void {
  if (temporizador !== null) clearTimeout(temporizador)
  temporizador = null
}

function abrir(inmediato = false): void {
  cancelar()
  const espera = inmediato ? 0 : props.retardo
  temporizador = setTimeout(() => {
    visible.value = true
    // Colisión con el borde de la ventana: primero se voltea el eje.
    requestAnimationFrame(() => {
      const caja = disparador.value?.getBoundingClientRect()
      if (!caja) return
      if (props.posicion === 'arriba') volteado.value = caja.top < 64
      else if (props.posicion === 'abajo') volteado.value = window.innerHeight - caja.bottom < 64
      else if (props.posicion === 'izquierda') volteado.value = caja.left < 300
      else volteado.value = window.innerWidth - caja.right < 300
    })
  }, espera)
}

function cerrar(): void {
  cancelar()
  temporizador = setTimeout(() => {
    visible.value = false
  }, 80)
}

const OPUESTA = {
  arriba: 'abajo',
  abajo: 'arriba',
  izquierda: 'derecha',
  derecha: 'izquierda',
} as const

onBeforeUnmount(cancelar)
</script>

<template>
  <span
    ref="disparador"
    class="envoltorio"
    @mouseenter="abrir()"
    @mouseleave="cerrar"
    @focusin="abrir(true)"
    @focusout="cerrar"
    @keydown.escape="visible = false"
  >
    <span :aria-describedby="visible ? idPista : undefined" class="disparador">
      <slot />
    </span>
    <Transition name="pista">
      <span
        v-if="visible"
        :id="idPista"
        role="tooltip"
        class="pista fade-only"
        :class="`p-${volteado ? OPUESTA[posicion] : posicion}`"
      >
        {{ texto }}
      </span>
    </Transition>
  </span>
</template>

<style scoped>
.envoltorio {
  position: relative;
  display: inline-flex;
}
.disparador {
  display: inline-flex;
}

.pista {
  position: absolute;
  z-index: 60;
  max-width: 280px;
  width: max-content;
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  background-color: var(--c-surface-2);
  box-shadow: var(--elev-3);
  color: var(--c-text-1);
  font-size: var(--t-caption);
  line-height: var(--t-caption-lh);
  text-align: left;
  pointer-events: none;
}

.p-arriba {
  bottom: calc(100% + 6px);
  left: 50%;
  translate: -50% 0;
}
.p-abajo {
  top: calc(100% + 6px);
  left: 50%;
  translate: -50% 0;
}
.p-izquierda {
  right: calc(100% + 6px);
  top: 50%;
  translate: 0 -50%;
}
.p-derecha {
  left: calc(100% + 6px);
  top: 50%;
  translate: 0 -50%;
}

.pista-enter-active,
.pista-leave-active {
  transition:
    opacity var(--dur-fast) var(--ease-out),
    translate var(--dur-fast) var(--ease-out);
}
.pista-enter-from,
.pista-leave-to {
  opacity: 0;
}
</style>
