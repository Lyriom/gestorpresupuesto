<script setup lang="ts">
import { computed, nextTick, ref, useId, type Component } from 'vue'
import { onClickOutside } from '@vueuse/core'

export interface ItemMenu {
  clave: string
  etiqueta: string
  icono?: Component
  /** Atajo que se muestra a la derecha; el registro real vive en useAtajos. */
  atajo?: string
  peligrosa?: boolean
  deshabilitada?: boolean
  separadorAntes?: boolean
}

const props = withDefaults(
  defineProps<{
    items: ItemMenu[]
    /** aria-label del menú. */
    etiqueta: string
    alineacion?: 'izquierda' | 'derecha'
    /** Hacia arriba, cuando el disparador está al fondo de la pantalla. */
    haciaArriba?: boolean
    ancho?: string
  }>(),
  { alineacion: 'izquierda', ancho: '240px' },
)

const emit = defineEmits<{
  seleccionar: [clave: string]
  'update:abierto': [valor: boolean]
}>()

const base = useId()
const idMenu = `${base}-menu`
const abierto = ref(false)
const indiceActivo = ref(-1)
const raiz = ref<HTMLElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const disparador = ref<HTMLElement | null>(null)

/** Atributos ARIA que tiene que llevar el disparador que ponga quien lo use. */
const atributos = computed(() => ({
  'aria-haspopup': 'menu' as const,
  'aria-expanded': abierto.value,
  'aria-controls': idMenu,
}))

function abrir(): void {
  abierto.value = true
  emit('update:abierto', true)
  void enfocarIndice(0)
}

function cerrar(devolverFoco = true): void {
  if (!abierto.value) return
  abierto.value = false
  emit('update:abierto', false)
  indiceActivo.value = -1
  if (devolverFoco) disparador.value?.querySelector<HTMLElement>('button, a')?.focus()
}

function alternar(): void {
  abierto.value ? cerrar() : abrir()
}

/**
 * Lo que el teclado puede recorrer dentro del menú.
 *
 * Se lee del DOM y no de `items` por dos razones: los elementos deshabilitados
 * quedan fuera (antes se indexaba la lista filtrada contra el DOM sin filtrar, y
 * las flechas caían en el sitio equivocado), y los slots de cabecera y pie
 * entran en el recorrido —ahí es donde §5.16 coloca el conmutador de tema y el
 * botón de renovar sesión, que sin esto no se alcanzaban con el teclado—.
 */
function focusables(): HTMLElement[] {
  if (!menu.value) return []
  return Array.from(
    menu.value.querySelectorAll<HTMLElement>(
      '[role="menuitem"]:not([aria-disabled="true"]),' +
        'a[href],' +
        'input:not([disabled]),' +
        'select:not([disabled]),' +
        'button:not([disabled]):not([role="menuitem"])',
    ),
  )
}

async function enfocarIndice(indice: number): Promise<void> {
  await nextTick()
  const lista = focusables()
  if (lista.length === 0) return
  const i = ((indice % lista.length) + lista.length) % lista.length
  indiceActivo.value = i
  lista[i]?.focus()
}

function mover(delta: number): void {
  const lista = focusables()
  if (lista.length === 0) return
  const actual = lista.indexOf(document.activeElement as HTMLElement)
  void enfocarIndice((actual === -1 ? 0 : actual) + delta)
}

function elegir(item: ItemMenu): void {
  if (item.deshabilitada) return
  emit('seleccionar', item.clave)
  cerrar()
}

function alTeclear(evento: KeyboardEvent): void {
  switch (evento.key) {
    case 'ArrowDown':
      evento.preventDefault()
      abierto.value ? mover(1) : abrir()
      break
    case 'ArrowUp':
      evento.preventDefault()
      abierto.value ? mover(-1) : abrir()
      break
    case 'Home':
      evento.preventDefault()
      void enfocarIndice(0)
      break
    case 'End':
      evento.preventDefault()
      void enfocarIndice(focusables().length - 1)
      break
    case 'Escape':
      evento.preventDefault()
      cerrar()
      break
    case 'Tab':
      cerrar(false)
      break
  }
}

onClickOutside(raiz, () => cerrar(false))
defineExpose({ abrir, cerrar, alternar })
</script>

<template>
  <div ref="raiz" class="envoltorio" @keydown="alTeclear">
    <div ref="disparador" class="disparador">
      <!-- El disparador lo pone quien usa el menú; aquí solo se le pasan los
           atributos ARIA que tiene que llevar. -->
      <slot name="disparador" :abierto="abierto" :alternar="alternar" :atributos="atributos" />
    </div>

    <Transition name="menu">
      <div
        v-if="abierto"
        :id="idMenu"
        ref="menu"
        role="menu"
        :aria-label="etiqueta"
        class="menu elev-3 fade-only"
        :class="[`a-${alineacion}`, { arriba: haciaArriba }]"
        :style="{ width: ancho }"
      >
        <slot name="cabecera" />
        <template v-for="item in items" :key="item.clave">
          <hr v-if="item.separadorAntes" class="separador" />
          <button
            type="button"
            role="menuitem"
            class="item"
            :class="{ peligrosa: item.peligrosa, inactiva: item.deshabilitada }"
            :aria-disabled="item.deshabilitada ? 'true' : undefined"
            :tabindex="-1"
            @click="elegir(item)"
          >
            <component :is="item.icono" v-if="item.icono" :size="16" aria-hidden="true" />
            <span class="etiqueta">{{ item.etiqueta }}</span>
            <kbd v-if="item.atajo">{{ item.atajo }}</kbd>
          </button>
        </template>
        <slot name="pie" />
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.envoltorio {
  position: relative;
  display: inline-flex;
}
.disparador {
  display: inline-flex;
}

.menu {
  position: absolute;
  top: calc(100% + 4px);
  z-index: 70;
  padding: var(--sp-1);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  background-color: var(--c-surface-2);
}
.menu.arriba {
  top: auto;
  bottom: calc(100% + 4px);
}
.a-izquierda {
  left: 0;
}
.a-derecha {
  right: 0;
}

.item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  /* Objetivo táctil de 44 px (§10); antes eran 36. */
  min-height: 44px;
  padding-inline: var(--sp-2);
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--c-text-1);
  font-family: inherit;
  font-size: var(--t-body);
  text-align: left;
  cursor: pointer;
}
.item:hover:not(.inactiva) {
  background-color: var(--c-surface-3);
}
.item .etiqueta {
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.item.peligrosa {
  color: var(--c-negative);
}
.item.peligrosa:hover {
  background-color: var(--c-negative-wash);
}
.item.inactiva {
  color: var(--c-text-disabled);
  cursor: not-allowed;
}
kbd {
  flex: none;
  font-family: var(--font-mono);
  font-size: var(--t-micro);
  color: var(--c-text-3);
}

.separador {
  margin: var(--sp-1) 0;
  border: 0;
  border-top: 1px solid var(--c-border);
}

.menu-enter-active,
.menu-leave-active {
  transition: opacity var(--dur-fast) var(--ease-out);
}
.menu-enter-from,
.menu-leave-to {
  opacity: 0;
}
</style>
