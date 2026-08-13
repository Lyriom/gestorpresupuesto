<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { X } from 'lucide-vue-next'

const props = withDefaults(
  defineProps<{
    abierto: boolean
    titulo: string
    subtitulo?: string
    tamanyo?: 'sm' | 'md' | 'lg' | 'xl'
    /** Primaria en carga, resto deshabilitado y cierre bloqueado. */
    guardando?: boolean
    /** Banda de error bajo la cabecera. */
    error?: string
    /** Con cambios pendientes, Escape no cierra: pregunta. */
    cambiosSinGuardar?: boolean
    cerrarConEscape?: boolean
    ocultarCierre?: boolean
  }>(),
  { tamanyo: 'md', cerrarConEscape: true },
)

const emit = defineEmits<{
  'update:abierto': [valor: boolean]
  cerrar: []
  /** Se ha intentado cerrar con cambios sin guardar: el padre decide. */
  descartar: []
}>()

const base = useId()
const idTitulo = `${base}-titulo`
const panel = ref<HTMLElement | null>(null)
const cuerpo = ref<HTMLElement | null>(null)
const corteArriba = ref(false)
const corteAbajo = ref(false)
let devolverFocoA: HTMLElement | null = null

const SELECTOR_FOCO =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function solicitarCierre(): void {
  if (props.guardando) return
  if (props.cambiosSinGuardar) {
    emit('descartar')
    return
  }
  emit('update:abierto', false)
  emit('cerrar')
}

function atraparFoco(evento: KeyboardEvent): void {
  if (evento.key !== 'Tab' || !panel.value) return
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

function medirCortes(): void {
  const el = cuerpo.value
  if (!el) return
  corteArriba.value = el.scrollTop > 1
  corteAbajo.value = el.scrollTop + el.clientHeight < el.scrollHeight - 1
}

function bloquearFondo(): void {
  // Se compensa el ancho de la barra para que no haya salto de maquetación.
  const barra = window.innerWidth - document.documentElement.clientWidth
  document.body.style.overflow = 'hidden'
  if (barra > 0) document.body.style.paddingRight = `${barra}px`
  document.getElementById('app')?.setAttribute('inert', '')
}

function liberarFondo(): void {
  document.body.style.overflow = ''
  document.body.style.paddingRight = ''
  document.getElementById('app')?.removeAttribute('inert')
}

watch(
  () => props.abierto,
  async (abierto) => {
    if (abierto) {
      devolverFocoA = document.activeElement as HTMLElement | null
      bloquearFondo()
      await nextTick()
      // Al abrir, el foco va al primer campo; si no hay, al contenedor. Nunca
      // a una acción destructiva.
      const campo = panel.value?.querySelector<HTMLElement>(
        'input:not([type="hidden"]), textarea, select',
      )
      ;(campo ?? panel.value)?.focus()
      medirCortes()
    } else {
      liberarFondo()
      devolverFocoA?.focus()
      devolverFocoA = null
    }
  },
)

onBeforeUnmount(liberarFondo)
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="abierto" class="escena" @keydown.esc="cerrarConEscape && solicitarCierre()">
        <div class="scrim" @click="solicitarCierre()" />
        <div
          ref="panel"
          class="panel elev-3"
          :class="`t-${tamanyo}`"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="idTitulo"
          :aria-busy="guardando ? 'true' : undefined"
          tabindex="-1"
          @keydown="atraparFoco"
        >
          <header class="cabecera">
            <div class="titulos">
              <h2 :id="idTitulo">{{ titulo }}</h2>
              <p v-if="subtitulo">{{ subtitulo }}</p>
            </div>
            <button
              v-if="!ocultarCierre"
              type="button"
              class="cerrar"
              aria-label="Cerrar"
              :disabled="guardando"
              @click="solicitarCierre()"
            >
              <X :size="18" aria-hidden="true" />
            </button>
          </header>

          <p v-if="error" class="banda-error" role="alert">{{ error }}</p>

          <div
            ref="cuerpo"
            class="cuerpo"
            :class="{ 'corte-arriba': corteArriba, 'corte-abajo': corteAbajo }"
            @scroll="medirCortes"
          >
            <slot />
          </div>

          <footer v-if="$slots.pie" class="pie">
            <slot name="pie" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.escena {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: grid;
  place-items: center;
  padding: var(--sp-4);
}
.scrim {
  position: absolute;
  inset: 0;
  background-color: var(--c-overlay);
  backdrop-filter: blur(2px);
}

.panel {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-height: calc(100dvh - 2 * var(--sp-4));
  border: 1px solid var(--c-border);
  border-radius: var(--r-xl);
  background-color: var(--c-surface-2);
}
.t-sm {
  max-width: 420px;
}
.t-md {
  max-width: 560px;
}
.t-lg {
  max-width: 720px;
}
.t-xl {
  max-width: 960px;
}

.cabecera {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  padding: var(--sp-5) var(--sp-5) var(--sp-4);
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
  color: var(--c-text-1);
}
.titulos p {
  margin: var(--sp-1) 0 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.cerrar {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  margin: calc(-1 * var(--sp-2)) calc(-1 * var(--sp-2)) 0 0;
  border: 0;
  border-radius: var(--r-md);
  background: none;
  color: var(--c-text-2);
  cursor: pointer;
}
.cerrar:hover:not(:disabled) {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}
.cerrar:disabled {
  color: var(--c-text-disabled);
  cursor: not-allowed;
}

.banda-error {
  margin: 0;
  padding: var(--sp-3) var(--sp-5);
  background-color: var(--c-negative-wash);
  color: var(--c-negative);
  font-size: var(--t-sm);
}

.cuerpo {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 0 var(--sp-5) var(--sp-5);
  max-height: calc(100dvh - 160px);
}
/* Bordes de 1 px cuando el cuerpo está cortado por el scroll. */
.cuerpo.corte-arriba {
  border-top: 1px solid var(--c-border);
  padding-top: var(--sp-4);
}
.cuerpo.corte-abajo {
  border-bottom: 1px solid var(--c-border);
}

.pie {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-2);
  padding: var(--sp-4) var(--sp-5);
  border-top: 1px solid var(--c-border);
}

.modal-enter-active .panel,
.modal-leave-active .panel {
  transition:
    opacity var(--dur-slow) var(--ease-out),
    scale var(--dur-slow) var(--ease-out);
}
.modal-enter-active,
.modal-leave-active {
  transition: opacity var(--dur-slow) var(--ease-out);
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-from .panel,
.modal-leave-to .panel {
  scale: 0.98;
}

@media (max-width: 639px) {
  .escena {
    padding: 0;
    place-items: end stretch;
  }
  .panel {
    max-width: none;
    max-height: 100dvh;
    border-radius: 0;
  }
}
</style>
