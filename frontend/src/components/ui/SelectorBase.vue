<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from 'vue'
import { onClickOutside } from '@vueuse/core'
import { Check, ChevronDown, CircleAlert } from 'lucide-vue-next'
import EsqueletoCarga from './EsqueletoCarga.vue'

export interface OpcionSelector {
  valor: string | number
  etiqueta: string
  /** Cabecera de grupo bajo la que se agrupa la opción. */
  grupo?: string
  deshabilitada?: boolean
  /** Ranura de categoría 1..12: pinta un punto del hue a la izquierda. */
  ranura?: number
}

const props = withDefaults(
  defineProps<{
    modelValue: string | number | null
    opciones: OpcionSelector[]
    etiqueta: string
    placeholder?: string
    ayuda?: string
    error?: string
    deshabilitado?: boolean
    cargando?: boolean
    requerido?: boolean
    etiquetaOculta?: boolean
    /** Buscador interno. Por defecto se activa a partir de 8 opciones. */
    buscable?: boolean
  }>(),
  { placeholder: 'Selecciona una opción' },
)

const emit = defineEmits<{ 'update:modelValue': [valor: string | number | null] }>()

const base = useId()
const idDisparador = `${base}-disparador`
const idLista = `${base}-lista`
const idAyuda = `${base}-ayuda`

const abierto = ref(false)
const filtro = ref('')
const indiceActivo = ref(-1)
const raiz = ref<HTMLElement | null>(null)
const disparador = ref<HTMLButtonElement | null>(null)
const buscador = ref<HTMLInputElement | null>(null)
const lista = ref<HTMLElement | null>(null)
let teclado = ''
let relojTeclado: ReturnType<typeof setTimeout> | null = null

const conBuscador = computed(() => props.buscable ?? props.opciones.length >= 8)

const visibles = computed(() => {
  const t = filtro.value.trim().toLowerCase()
  if (!t) return props.opciones
  return props.opciones.filter((o) => o.etiqueta.toLowerCase().includes(t))
})

/** Opciones agrupadas conservando el orden de llegada. */
const grupos = computed(() => {
  const salida: Array<{ nombre: string | undefined; opciones: OpcionSelector[] }> = []
  for (const o of visibles.value) {
    const ultimo = salida.at(-1)
    if (ultimo && ultimo.nombre === o.grupo) ultimo.opciones.push(o)
    else salida.push({ nombre: o.grupo, opciones: [o] })
  }
  return salida
})

const seleccionada = computed(() => props.opciones.find((o) => o.valor === props.modelValue) ?? null)
const idOpcion = (i: number) => `${base}-op-${i}`

function abrir(): void {
  if (props.deshabilitado) return
  abierto.value = true
  indiceActivo.value = Math.max(
    0,
    visibles.value.findIndex((o) => o.valor === props.modelValue),
  )
  void nextTick(() => {
    if (conBuscador.value) buscador.value?.focus()
    desplazarAlActivo()
  })
}

function cerrar(devolverFoco = true): void {
  if (!abierto.value) return
  abierto.value = false
  filtro.value = ''
  if (devolverFoco) disparador.value?.focus()
}

function elegir(opcion: OpcionSelector): void {
  if (opcion.deshabilitada) return
  emit('update:modelValue', opcion.valor)
  cerrar()
}

function desplazarAlActivo(): void {
  lista.value?.querySelector<HTMLElement>('[data-activa="true"]')?.scrollIntoView({ block: 'nearest' })
}

function mover(delta: number): void {
  const total = visibles.value.length
  if (total === 0) return
  let i = indiceActivo.value
  for (let intento = 0; intento < total; intento++) {
    i = (i + delta + total) % total
    if (!visibles.value[i].deshabilitada) break
  }
  indiceActivo.value = i
  void nextTick(desplazarAlActivo)
}

function irA(indice: number): void {
  indiceActivo.value = indice
  void nextTick(desplazarAlActivo)
}

function saltarPorLetra(letra: string): void {
  teclado += letra.toLowerCase()
  if (relojTeclado !== null) clearTimeout(relojTeclado)
  relojTeclado = setTimeout(() => (teclado = ''), 600)
  const i = visibles.value.findIndex((o) => o.etiqueta.toLowerCase().startsWith(teclado))
  if (i >= 0) irA(i)
}

function alTeclear(evento: KeyboardEvent): void {
  if (!abierto.value) {
    if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(evento.key)) {
      evento.preventDefault()
      abrir()
    }
    return
  }
  switch (evento.key) {
    case 'ArrowDown':
      evento.preventDefault()
      mover(1)
      break
    case 'ArrowUp':
      evento.preventDefault()
      mover(-1)
      break
    case 'Home':
      evento.preventDefault()
      irA(0)
      break
    case 'End':
      evento.preventDefault()
      irA(visibles.value.length - 1)
      break
    case 'Enter':
      evento.preventDefault()
      if (visibles.value[indiceActivo.value]) elegir(visibles.value[indiceActivo.value])
      break
    case 'Escape':
      evento.preventDefault()
      cerrar()
      break
    case 'Tab':
      // Tab cierra confirmando lo que estuviera activo.
      if (visibles.value[indiceActivo.value]) elegir(visibles.value[indiceActivo.value])
      else cerrar(false)
      break
    default:
      if (!conBuscador.value && evento.key.length === 1 && /\S/.test(evento.key)) {
        saltarPorLetra(evento.key)
      }
  }
}

const errorVisible = computed(() => props.error)

watch(filtro, () => {
  indiceActivo.value = visibles.value.length > 0 ? 0 : -1
})

onClickOutside(raiz, () => cerrar(false))
</script>

<template>
  <div ref="raiz" class="campo">
    <label :for="idDisparador" :class="{ 'oculto-visualmente': etiquetaOculta }">
      {{ etiqueta }}<span v-if="requerido" class="requerido" aria-hidden="true"> *</span>
    </label>

    <button
      :id="idDisparador"
      ref="disparador"
      type="button"
      role="combobox"
      class="disparador"
      :class="{ malo: !!errorVisible, abierto, inactivo: deshabilitado }"
      :disabled="deshabilitado"
      :aria-expanded="abierto"
      :aria-controls="idLista"
      :aria-activedescendant="abierto && indiceActivo >= 0 ? idOpcion(indiceActivo) : undefined"
      :aria-invalid="errorVisible ? 'true' : undefined"
      :aria-describedby="ayuda || errorVisible ? idAyuda : undefined"
      @click="abierto ? cerrar() : abrir()"
      @keydown="alTeclear"
    >
      <span v-if="seleccionada" class="valor">
        <span
          v-if="seleccionada.ranura"
          class="punto"
          :style="{ '--hue': `var(--c-cat-${seleccionada.ranura})` }"
          aria-hidden="true"
        />
        {{ seleccionada.etiqueta }}
      </span>
      <span v-else class="hueco">{{ placeholder }}</span>
      <ChevronDown :size="16" class="chevron" aria-hidden="true" />
    </button>

    <p v-if="errorVisible" :id="idAyuda" class="mensaje malo-texto" aria-live="polite">
      <CircleAlert :size="14" aria-hidden="true" />{{ errorVisible }}
    </p>
    <p v-else-if="ayuda" :id="idAyuda" class="mensaje">{{ ayuda }}</p>

    <div v-if="abierto" class="flotante elev-3">
      <div v-if="conBuscador" class="buscador">
        <input
          ref="buscador"
          v-model="filtro"
          type="search"
          autocomplete="off"
          placeholder="Buscar…"
          aria-label="Buscar opción"
          :aria-controls="idLista"
          :aria-activedescendant="indiceActivo >= 0 ? idOpcion(indiceActivo) : undefined"
          @keydown="alTeclear"
        />
      </div>

      <div v-if="cargando" class="cargando">
        <EsqueletoCarga variante="texto" :lineas="3" anuncio="Cargando opciones" />
      </div>

      <ul v-else :id="idLista" ref="lista" role="listbox" :aria-label="etiqueta" class="lista">
        <li v-if="visibles.length === 0" class="sin-resultados">Sin resultados</li>
        <template v-for="(grupo, g) in grupos" :key="g">
          <li v-if="grupo.nombre" class="cabecera-grupo" role="presentation">{{ grupo.nombre }}</li>
          <li
            v-for="opcion in grupo.opciones"
            :id="idOpcion(visibles.indexOf(opcion))"
            :key="opcion.valor"
            role="option"
            class="opcion"
            :data-activa="visibles.indexOf(opcion) === indiceActivo"
            :class="{
              activa: visibles.indexOf(opcion) === indiceActivo,
              elegida: opcion.valor === modelValue,
              inactiva: opcion.deshabilitada,
            }"
            :aria-selected="opcion.valor === modelValue"
            :aria-disabled="opcion.deshabilitada ? 'true' : undefined"
            @click="elegir(opcion)"
            @mousemove="irA(visibles.indexOf(opcion))"
          >
            <Check v-if="opcion.valor === modelValue" :size="16" class="check" aria-hidden="true" />
            <span v-else class="check" />
            <span
              v-if="opcion.ranura"
              class="punto"
              :style="{ '--hue': `var(--c-cat-${opcion.ranura})` }"
              aria-hidden="true"
            />
            {{ opcion.etiqueta }}
          </li>
        </template>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.campo {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
label {
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.requerido {
  color: var(--c-negative);
}

.disparador {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  height: 40px;
  padding-inline: var(--sp-3);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background-color: var(--c-surface-2);
  color: var(--c-text-1);
  font-family: inherit;
  font-size: var(--t-body);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--dur-instant) var(--ease-in-out);
}
.disparador:hover:not(.inactivo) {
  border-color: var(--c-border-strong);
}
.disparador.abierto {
  border-color: var(--c-accent);
}
.disparador.malo {
  border-color: var(--c-negative);
}
.disparador.inactivo {
  background-color: var(--c-surface);
  color: var(--c-text-disabled);
  cursor: not-allowed;
}
.valor {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hueco {
  flex: 1 1 auto;
  color: var(--c-text-3);
}
.chevron {
  flex: none;
  color: var(--c-text-3);
}

.punto {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: var(--r-full);
  background-color: var(--hue);
}

.flotante {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  z-index: 50;
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  background-color: var(--c-surface-2);
  overflow: hidden;
}
.buscador {
  padding: var(--sp-2);
  border-bottom: 1px solid var(--c-border);
}
.buscador input {
  width: 100%;
  height: 32px;
  padding-inline: var(--sp-2);
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  background-color: var(--c-surface);
  color: var(--c-text-1);
  font-family: inherit;
  font-size: var(--t-sm);
}
.cargando {
  padding: var(--sp-3);
}

.lista {
  margin: 0;
  padding: var(--sp-1);
  max-height: 320px;
  overflow-y: auto;
  list-style: none;
}
.cabecera-grupo {
  padding: var(--sp-2) var(--sp-2) var(--sp-1);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--c-text-3);
}
.opcion {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-height: 36px;
  padding-inline: var(--sp-2);
  border-radius: var(--r-sm);
  font-size: var(--t-body);
  cursor: pointer;
}
.opcion .check {
  flex: none;
  width: 16px;
  color: var(--c-accent);
}
.opcion.activa {
  background-color: var(--c-surface-3);
}
.opcion.elegida {
  background-color: var(--c-accent-wash);
}
.opcion.inactiva {
  color: var(--c-text-disabled);
  cursor: not-allowed;
}
.sin-resultados {
  padding: var(--sp-3) var(--sp-2);
  font-size: var(--t-sm);
  color: var(--c-text-3);
}

.mensaje {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  margin: 0;
  font-size: var(--t-caption);
  color: var(--c-text-3);
}
.malo-texto {
  color: var(--c-negative);
}

.oculto-visualmente {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>
