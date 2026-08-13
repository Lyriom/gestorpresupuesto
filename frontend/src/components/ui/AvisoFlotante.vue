<script setup lang="ts">
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from 'lucide-vue-next'
import { useAvisos, type TipoAviso } from '@/composables/useAvisos'

/**
 * Región única de avisos: se monta una sola vez en el layout. La cola vive en
 * useAvisos, así que cualquier capa puede lanzar un aviso sin conocer el DOM.
 */
const { avisos, pausado, cerrar, pausar, reanudar } = useAvisos()

const ICONOS = {
  exito: CircleCheck,
  info: Info,
  aviso: TriangleAlert,
  error: CircleAlert,
} as const satisfies Record<TipoAviso, unknown>
</script>

<template>
  <div
    class="region"
    @pointerenter="pausar"
    @pointerleave="reanudar"
    @focusin="pausar"
    @focusout="reanudar"
  >
    <TransitionGroup name="aviso">
      <div
        v-for="a in avisos"
        :key="a.id"
        class="aviso elev-3"
        :class="`tipo-${a.tipo}`"
        :role="a.tipo === 'error' ? 'alert' : 'status'"
        :aria-live="a.tipo === 'error' ? 'assertive' : 'polite'"
      >
        <component :is="ICONOS[a.tipo]" :size="16" class="icono" aria-hidden="true" />
        <div class="texto">
          <p v-if="a.titulo" class="titulo">{{ a.titulo }}</p>
          <p class="mensaje">{{ a.mensaje }}</p>
          <button v-if="a.accion" type="button" class="accion" @click="a.accion.alPulsar()">
            {{ a.accion.etiqueta }}
          </button>
        </div>
        <button type="button" class="cerrar toque-44" aria-label="Cerrar el aviso" @click="cerrar(a.id)">
          <X :size="14" aria-hidden="true" />
        </button>
        <span
          v-if="a.duracion > 0"
          class="temporizador"
          aria-hidden="true"
          :style="{
            animationDuration: `${a.duracion}ms`,
            animationPlayState: pausado ? 'paused' : 'running',
          }"
        />
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.region {
  position: fixed;
  z-index: 120;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  /* Escritorio: abajo a la derecha. */
  right: var(--sp-4);
  bottom: var(--sp-4);
  width: min(360px, calc(100vw - 2 * var(--sp-4)));
}
/* Móvil: arriba, para no tapar el botón flotante de añadir gasto. */
@media (max-width: 767px) {
  .region {
    top: max(var(--sp-4), env(safe-area-inset-top));
    bottom: auto;
    left: var(--sp-4);
    right: var(--sp-4);
    width: auto;
  }
}

.aviso {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  overflow: hidden;
  padding: var(--sp-3);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  background-color: var(--c-surface-2);
}
.icono {
  flex: none;
  margin-top: 1px;
  color: var(--tono);
}
.texto {
  flex: 1 1 auto;
  min-width: 0;
}
.titulo {
  margin: 0 0 2px;
  font-size: var(--t-sm);
  font-weight: 600;
  color: var(--c-text-1);
}
.mensaje {
  margin: 0;
  font-size: var(--t-sm);
  line-height: var(--t-sm-lh);
  color: var(--c-text-2);
}
.accion {
  margin-top: var(--sp-1);
  padding: 0;
  border: 0;
  background: none;
  color: var(--c-accent-text);
  font-family: inherit;
  font-size: var(--t-sm);
  font-weight: 600;
  cursor: pointer;
}
.accion:hover {
  text-decoration: underline;
}
.cerrar {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--c-text-3);
  cursor: pointer;
}
.cerrar:hover {
  color: var(--c-text-1);
}

.temporizador {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2px;
  width: 100%;
  transform-origin: left;
  background-color: var(--tono);
  animation-name: menguar;
  animation-timing-function: linear;
  animation-fill-mode: forwards;
}
@keyframes menguar {
  from {
    scale: 1 1;
  }
  to {
    scale: 0 1;
  }
}

.tipo-exito {
  --tono: var(--c-positive);
}
.tipo-info {
  --tono: var(--c-info);
}
.tipo-aviso {
  --tono: var(--c-warning);
}
.tipo-error {
  --tono: var(--c-negative);
}

.aviso-enter-active,
.aviso-leave-active {
  transition:
    opacity var(--dur-base) var(--ease-out),
    translate var(--dur-base) var(--ease-out);
}
.aviso-enter-from,
.aviso-leave-to {
  opacity: 0;
  translate: 0 8px;
}
.aviso-leave-active {
  position: absolute;
}
</style>
