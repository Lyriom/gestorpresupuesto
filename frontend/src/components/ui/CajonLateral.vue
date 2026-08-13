<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { ChevronDown, ChevronUp, X } from 'lucide-vue-next'
import { useMedia } from '@/composables/useMedia'
import { bloquearFondo, liberarFondo } from '@/lib/capaModal'
import EsqueletoCarga from './EsqueletoCarga.vue'

const props = withDefaults(
  defineProps<{
    abierto: boolean
    titulo: string
    subtitulo?: string
    tamanyo?: 'md' | 'lg'
    /**
     * Bloquea el fondo y atrapa el foco. Por defecto: no en escritorio (el
     * panel conserva el contexto de la lista) y sí en móvil (hoja inferior).
     */
    bloqueante?: boolean
    cargando?: boolean
    /** Muestra los chevrons de anterior/siguiente en la cabecera. */
    conNavegacion?: boolean
    hayAnterior?: boolean
    haySiguiente?: boolean
  }>(),
  { tamanyo: 'md' },
)

const emit = defineEmits<{
  'update:abierto': [valor: boolean]
  cerrar: []
  anterior: []
  siguiente: []
}>()

const { esMovil } = useMedia()
const base = useId()
const idTitulo = `${base}-titulo`
const panel = ref<HTMLElement | null>(null)
const arrastre = ref(0)
let devolverFocoA: HTMLElement | null = null
let inicioY: number | null = null

const bloquea = computed(() => props.bloqueante ?? esMovil.value)

function cerrar(): void {
  emit('update:abierto', false)
  emit('cerrar')
}

const SELECTOR_FOCO =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Cuando el cajón bloquea (hoja inferior en móvil) el foco no puede escaparse
 * al fondo, que además está `inert`: §5.8 le da la misma semántica que al modal.
 */
function atraparFoco(evento: KeyboardEvent): void {
  if (!bloquea.value || evento.key !== 'Tab' || !panel.value) return
  const focoables = [...panel.value.querySelectorAll<HTMLElement>(SELECTOR_FOCO)].filter(
    (el) => el.offsetParent !== null,
  )
  if (focoables.length === 0) {
    evento.preventDefault()
    panel.value.focus()
    return
  }
  const primero = focoables[0]
  const ultimo = focoables[focoables.length - 1]
  const activo = document.activeElement
  if (evento.shiftKey && (activo === primero || activo === panel.value)) {
    evento.preventDefault()
    ultimo.focus()
  } else if (!evento.shiftKey && activo === ultimo) {
    evento.preventDefault()
    primero.focus()
  }
}

function alTeclear(evento: KeyboardEvent): void {
  if (evento.key === 'Escape') {
    evento.stopPropagation()
    cerrar()
    return
  }
  atraparFoco(evento)
  if (!props.conNavegacion) return
  // Las flechas solo navegan si el foco no está dentro de un campo de texto.
  const destino = evento.target as HTMLElement
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(destino.tagName)) return
  if (evento.key === 'ArrowUp' && props.hayAnterior) {
    evento.preventDefault()
    emit('anterior')
  } else if (evento.key === 'ArrowDown' && props.haySiguiente) {
    evento.preventDefault()
    emit('siguiente')
  }
}

/* Cierre por gesto hacia abajo en la hoja inferior. */
function inicioGesto(evento: TouchEvent): void {
  inicioY = evento.touches[0]?.clientY ?? null
}
function moverGesto(evento: TouchEvent): void {
  if (inicioY === null) return
  arrastre.value = Math.max(0, (evento.touches[0]?.clientY ?? inicioY) - inicioY)
}
function finGesto(): void {
  if (arrastre.value > 96) cerrar()
  arrastre.value = 0
  inicioY = null
}

/** Esta instancia tiene el fondo bloqueado; sin esto, cerrar un cajón no
 *  bloqueante quitaba el `inert` que había puesto un modal exterior. */
let bloqueado = false

function liberar(): void {
  if (!bloqueado) return
  bloqueado = false
  liberarFondo()
}

watch(
  () => props.abierto,
  async (abierto) => {
    if (abierto) {
      devolverFocoA = document.activeElement as HTMLElement | null
      if (bloquea.value && !bloqueado) {
        bloqueado = true
        bloquearFondo()
      }
      await nextTick()
      // Al primer campo si hay; si no, al contenedor (§5.7).
      const campo = panel.value?.querySelector<HTMLElement>(
        'input:not([type="hidden"]):not([disabled]):not([readonly]),' +
          'textarea:not([disabled]):not([readonly]),' +
          'select:not([disabled]),' +
          '[role="combobox"]:not([disabled])',
      )
      ;(campo ?? panel.value)?.focus()
    } else {
      liberar()
      devolverFocoA?.focus()
      devolverFocoA = null
      arrastre.value = 0
    }
  },
)

onBeforeUnmount(() => {
  liberar()
  devolverFocoA?.focus()
  devolverFocoA = null
})
</script>

<template>
  <Teleport to="body">
    <Transition :name="esMovil ? 'hoja' : 'cajon'">
      <div v-if="abierto" class="escena" :class="{ movil: esMovil, bloquea }">
        <div v-if="bloquea" class="scrim" @click="cerrar" />
        <aside
          ref="panel"
          class="panel elev-3"
          :class="`t-${tamanyo}`"
          role="dialog"
          :aria-modal="bloquea"
          :aria-labelledby="idTitulo"
          tabindex="-1"
          :style="arrastre ? { translate: `0 ${arrastre}px` } : undefined"
          @keydown="alTeclear"
        >
          <div
            v-if="esMovil"
            class="asa"
            aria-hidden="true"
            @touchstart="inicioGesto"
            @touchmove="moverGesto"
            @touchend="finGesto"
          >
            <span />
          </div>

          <header class="cabecera">
            <div class="titulos">
              <h2 :id="idTitulo">{{ titulo }}</h2>
              <p v-if="subtitulo">{{ subtitulo }}</p>
            </div>
            <div class="acciones">
              <template v-if="conNavegacion">
                <button
                  type="button"
                  aria-label="Elemento anterior"
                  :disabled="!hayAnterior"
                  @click="emit('anterior')"
                >
                  <ChevronUp :size="18" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  aria-label="Elemento siguiente"
                  :disabled="!haySiguiente"
                  @click="emit('siguiente')"
                >
                  <ChevronDown :size="18" aria-hidden="true" />
                </button>
              </template>
              <button type="button" aria-label="Cerrar el panel" @click="cerrar">
                <X :size="18" aria-hidden="true" />
              </button>
            </div>
          </header>

          <div class="cuerpo">
            <EsqueletoCarga
              v-if="cargando"
              variante="texto"
              :lineas="6"
              anuncio="Cargando el detalle"
            />
            <slot v-else />
          </div>

          <footer v-if="$slots.pie" class="pie"><slot name="pie" /></footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.escena {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  justify-content: flex-end;
  pointer-events: none;
}
.escena.bloquea {
  pointer-events: auto;
}
.scrim {
  position: absolute;
  inset: 0;
  background-color: var(--c-overlay);
}

.panel {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  border-left: 1px solid var(--c-border);
  border-radius: var(--r-xl) 0 0 var(--r-xl);
  background-color: var(--c-surface-2);
  pointer-events: auto;
}
.t-md {
  max-width: 420px;
}
.t-lg {
  max-width: 560px;
}

.escena.movil {
  align-items: flex-end;
  justify-content: center;
}
.escena.movil .panel {
  max-width: none;
  height: 92dvh;
  border-left: 0;
  border-top: 1px solid var(--c-border);
  border-radius: var(--r-xl) var(--r-xl) 0 0;
  transition: translate var(--dur-fast) var(--ease-out);
}

.asa {
  display: flex;
  justify-content: center;
  padding: var(--sp-2) 0;
  touch-action: none;
}
.asa span {
  width: 40px;
  height: 4px;
  border-radius: var(--r-full);
  background-color: var(--c-border-strong);
}

.cabecera {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  border-bottom: 1px solid var(--c-border);
  background-color: var(--c-surface-2);
}
.titulos {
  flex: 1 1 auto;
  min-width: 0;
}
.titulos h2 {
  margin: 0;
  font-size: var(--t-h2);
  line-height: var(--t-h2-lh);
  font-weight: 600;
}
.titulos p {
  margin: var(--sp-1) 0 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.acciones {
  display: flex;
  gap: var(--sp-1);
}
.acciones button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--r-md);
  background: none;
  color: var(--c-text-2);
  cursor: pointer;
}
.acciones button:hover:not(:disabled) {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}
.acciones button:disabled {
  color: var(--c-text-disabled);
  cursor: not-allowed;
}

.cuerpo {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: var(--sp-5);
}
.pie {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-2);
  padding: var(--sp-4) var(--sp-5);
  border-top: 1px solid var(--c-border);
  padding-bottom: max(var(--sp-4), env(safe-area-inset-bottom));
}

.cajon-enter-active .panel,
.cajon-leave-active .panel {
  transition: translate var(--dur-slow) var(--ease-out);
}
.cajon-enter-from .panel,
.cajon-leave-to .panel {
  translate: 100% 0;
}
.cajon-enter-active,
.cajon-leave-active,
.hoja-enter-active,
.hoja-leave-active {
  transition: opacity var(--dur-slow) var(--ease-out);
}
.cajon-enter-from,
.cajon-leave-to,
.hoja-enter-from,
.hoja-leave-to {
  opacity: 0;
}
.hoja-enter-from .panel,
.hoja-leave-to .panel {
  translate: 0 100%;
}
</style>
