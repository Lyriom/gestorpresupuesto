<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { CircleAlert } from 'lucide-vue-next'
import { euros, parsearImporte } from '@/lib/formato'

/** 999.999,99 € expresados en céntimos, el tope del §5.5. */
const MAX_CENTIMOS = 99_999_999

/**
 * El € es un sufijo fijo FUERA del área de texto, así que `euros()` de
 * formato.ts no sirve para pintar el interior del campo: haría falta quitarle
 * el símbolo a posteriori. Este formateador da solo la cifra `1.234,56`.
 */
const fmtCampo = new Intl.NumberFormat('es-ES', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const props = withDefaults(
  defineProps<{
    /** Céntimos enteros. Nunca euros en coma flotante. */
    modelValue: number | null
    etiqueta?: string
    ayuda?: string
    error?: string
    deshabilitado?: boolean
    soloLectura?: boolean
    requerido?: boolean
    etiquetaOculta?: boolean
    /** `display` (28 px) en el modal rápido; `cuerpo` en formularios largos. */
    tamanyo?: 'cuerpo' | 'display'
    /** Fila de teclas `+10 +50 +100 C`. */
    teclasRapidas?: boolean
    /** Tope en céntimos; por defecto 999.999,99 €. */
    maximo?: number
  }>(),
  { etiqueta: 'Importe', tamanyo: 'cuerpo' },
)

const emit = defineEmits<{ 'update:modelValue': [centimos: number | null] }>()

const base = useId()
const idCampo = `${base}-campo`
const idAyuda = `${base}-ayuda`
const campo = ref<HTMLInputElement | null>(null)

const texto = ref('')
const enfocado = ref(false)
const errorInterno = ref<string | null>(null)
const expresion = ref<string | null>(null)
const signoIgnorado = ref(false)
const anuncio = ref('')
let relojExpresion: ReturnType<typeof setTimeout> | null = null
let relojSigno: ReturnType<typeof setTimeout> | null = null

const errorVisible = computed(() => props.error ?? errorInterno.value)
const tope = computed(() => props.maximo ?? MAX_CENTIMOS)

/* ---------- Máscara ----------------------------------------------------- */

function agrupar(entero: string): string {
  return entero.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
}

/**
 * Deja dígitos, una sola coma decimal por operando (máximo 2 decimales) y los
 * `+` de la aritmética simple. Los puntos se eliminan siempre: son separadores
 * de millar puestos por la máscara, porque el punto tecleado se convierte en
 * coma antes de llegar aquí.
 */
function limpiar(bruto: string): string {
  return bruto
    .replace(/[^\d,+]/g, '')
    .split('+')
    .map((op) => {
      const i = op.indexOf(',')
      if (i === -1) return op
      return `${op.slice(0, i)},${op.slice(i + 1).replace(/,/g, '').slice(0, 2)}`
    })
    .join('+')
}

function enmascarar(limpio: string): string {
  return limpio
    .split('+')
    .map((op) => {
      const [entero = '', decimal] = op.split(',')
      const e = agrupar(entero)
      return decimal === undefined ? e : `${e},${decimal}`
    })
    .join('+')
}

/** El cursor se mantiene por posición lógica (dígitos), no de caracteres. */
function significativosHasta(s: string, limite: number): number {
  let n = 0
  for (let i = 0; i < limite && i < s.length; i++) if (s[i] !== '.') n++
  return n
}

function posicionTras(s: string, cuantos: number): number {
  let n = 0
  for (let i = 0; i < s.length; i++) {
    if (n === cuantos) return i
    if (s[i] !== '.') n++
  }
  return s.length
}

/* ---------- Valor ------------------------------------------------------- */

function fijarCentimos(centimos: number): void {
  if (centimos > tope.value) {
    errorInterno.value = `El importe no puede pasar de ${euros(tope.value / 100)}.`
    emit('update:modelValue', null)
    return
  }
  errorInterno.value = null
  texto.value = fmtCampo.format(centimos / 100)
  anuncio.value = `${texto.value} euros`
  emit('update:modelValue', centimos)
}

function alEscribir(evento: Event): void {
  const el = evento.target as HTMLInputElement
  const caret = el.selectionStart ?? el.value.length
  const antes = significativosHasta(el.value, caret)
  const enmascarado = enmascarar(limpiar(el.value))
  texto.value = enmascarado
  el.value = enmascarado
  const pos = posicionTras(enmascarado, antes)
  el.setSelectionRange(pos, pos)
  errorInterno.value = null

  // Mientras se teclea una expresión no hay valor: se resuelve al salir.
  if (enmascarado.includes('+')) return
  const n = parsearImporte(enmascarado)
  emit('update:modelValue', n === null ? null : Math.round(n * 100))
}

function alPulsar(evento: KeyboardEvent): void {
  // Punto y coma del teclado numérico son lo mismo: separador decimal.
  if (evento.key !== '.') return
  evento.preventDefault()
  const el = evento.target as HTMLInputElement
  const i = el.selectionStart ?? el.value.length
  const f = el.selectionEnd ?? i
  el.value = `${el.value.slice(0, i)},${el.value.slice(f)}`
  el.setSelectionRange(i + 1, i + 1)
  el.dispatchEvent(new Event('input'))
}

function alPegar(evento: ClipboardEvent): void {
  const pegado = evento.clipboardData?.getData('text') ?? ''
  if (!pegado) return
  evento.preventDefault()
  if (pegado.includes('-')) {
    signoIgnorado.value = true
    if (relojSigno !== null) clearTimeout(relojSigno)
    relojSigno = setTimeout(() => (signoIgnorado.value = false), 4000)
  }
  const n = parsearImporte(pegado)
  if (n === null) return
  fijarCentimos(Math.round(Math.abs(n) * 100))
}

function alSalir(): void {
  enfocado.value = false
  const bruto = texto.value.trim()
  if (!bruto) {
    // Vacío se queda vacío: no se inventa un 0,00.
    errorInterno.value = null
    emit('update:modelValue', null)
    return
  }
  const partes = bruto.split('+').map((p) => p.trim()).filter(Boolean)
  const valores = partes.map(parsearImporte)
  if (valores.some((v) => v === null)) {
    errorInterno.value = 'Introduce un importe con el formato 1.234,56.'
    return
  }
  if (partes.length > 1) {
    expresion.value = partes.join(' + ')
    if (relojExpresion !== null) clearTimeout(relojExpresion)
    relojExpresion = setTimeout(() => (expresion.value = null), 2000)
  }
  const total = valores.reduce<number>((suma, v) => suma + (v ?? 0), 0)
  fijarCentimos(Math.round(total * 100))
}

function sumar(cantidadEuros: number): void {
  fijarCentimos((props.modelValue ?? 0) + cantidadEuros * 100)
  campo.value?.focus()
}

function vaciar(): void {
  texto.value = ''
  errorInterno.value = null
  emit('update:modelValue', null)
  campo.value?.focus()
}

watch(
  () => props.modelValue,
  (valor) => {
    if (enfocado.value) return
    texto.value = valor === null || valor === undefined ? '' : fmtCampo.format(valor / 100)
  },
  { immediate: true },
)

defineExpose({ enfocar: () => campo.value?.focus() })
</script>

<template>
  <div class="campo">
    <label :for="idCampo" :class="{ 'oculto-visualmente': etiquetaOculta }">
      {{ etiqueta }}<span class="oculto-visualmente"> en euros</span>
      <span v-if="requerido" class="requerido" aria-hidden="true"> *</span>
    </label>

    <p v-if="soloLectura" class="lectura num" :class="{ grande: tamanyo === 'display' }">
      {{ modelValue === null ? '—' : euros(modelValue / 100) }}
    </p>

    <div
      v-else
      class="caja"
      :class="{ malo: !!errorVisible, inactivo: deshabilitado, grande: tamanyo === 'display' }"
    >
      <input
        :id="idCampo"
        ref="campo"
        class="num"
        :class="{ 'num-grande': tamanyo === 'display' }"
        :value="texto"
        type="text"
        inputmode="decimal"
        autocomplete="off"
        enterkeyhint="done"
        placeholder="0,00"
        :disabled="deshabilitado"
        :required="requerido"
        :aria-invalid="errorVisible ? 'true' : undefined"
        :aria-describedby="idAyuda"
        @input="alEscribir"
        @keydown="alPulsar"
        @paste="alPegar"
        @focus="enfocado = true"
        @blur="alSalir"
      />
      <span class="moneda" aria-hidden="true">€</span>
    </div>

    <div v-if="teclasRapidas && !soloLectura" class="rapidas">
      <button v-for="n in [10, 50, 100]" :key="n" type="button" @click="sumar(n)">+{{ n }}</button>
      <button type="button" aria-label="Borrar el importe" @click="vaciar">C</button>
    </div>

    <p v-if="errorVisible" :id="idAyuda" class="mensaje malo-texto" aria-live="polite">
      <CircleAlert :size="14" aria-hidden="true" />{{ errorVisible }}
    </p>
    <p v-else :id="idAyuda" class="mensaje">
      <span v-if="expresion" class="expresion">{{ expresion }}</span>
      <span v-else-if="signoIgnorado" class="aviso-signo">
        Se ha ignorado el signo: el tipo de movimiento decide si suma o resta.
      </span>
      <span v-else>{{ ayuda ?? 'Coma o punto para los decimales. Puedes sumar: 12,50+3,20' }}</span>
    </p>

    <span class="oculto-visualmente" aria-live="polite">{{ anuncio }}</span>
  </div>
</template>

<style scoped>
.campo {
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

.caja {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  height: 40px;
  padding-inline: var(--sp-3);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background-color: var(--c-surface-2);
  transition:
    border-color var(--dur-instant) var(--ease-in-out),
    box-shadow var(--dur-instant) var(--ease-in-out);
}
.caja.grande {
  height: 56px;
}
.caja:hover:not(.inactivo) {
  border-color: var(--c-border-strong);
}
.caja:focus-within {
  border-color: var(--c-accent);
  box-shadow: var(--glow-accent);
}
/* Anillo de foco real (§5, §10): 2 px de acento con 2 px de separación. El
   input hace `outline: none` y el brillo de --glow-accent es de 1 px, por
   debajo del 3:1 exigido al indicador. Se ancla al input para que enfocar un
   botón de dentro de la caja no ilumine el campo entero. */
.caja:has(input:focus-visible) {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}
.caja.malo {
  border-color: var(--c-negative);
}
.caja.inactivo {
  background-color: var(--c-surface);
  border-color: var(--c-border-soft);
}

input {
  flex: 1 1 auto;
  min-width: 0;
  height: 100%;
  border: 0;
  padding: 0;
  background: none;
  color: var(--c-text-1);
  font-family: inherit;
  font-size: var(--t-body);
  font-weight: 600;
}
.grande input {
  font-size: var(--t-display);
  line-height: var(--t-display-lh);
}
input:focus {
  outline: none;
}
input:disabled {
  color: var(--c-text-disabled);
  cursor: not-allowed;
}

.moneda {
  flex: none;
  color: var(--c-text-3);
  font-size: var(--t-body);
}
.grande .moneda {
  font-size: var(--t-h3);
}

.lectura {
  margin: 0;
  font-size: var(--t-body);
  font-weight: 600;
  color: var(--c-text-1);
  text-align: left;
}
.lectura.grande {
  font-size: var(--t-display);
  letter-spacing: -0.012em;
}

.rapidas {
  display: flex;
  gap: var(--sp-2);
}
.rapidas button {
  min-width: 44px;
  height: 32px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  background-color: var(--c-surface-3);
  color: var(--c-text-2);
  font-family: inherit;
  font-size: var(--t-caption);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}
.rapidas button:hover {
  color: var(--c-text-1);
  border-color: var(--c-border-strong);
}

.mensaje {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  margin: 0;
  min-height: 1.2em;
  font-size: var(--t-caption);
  color: var(--c-text-3);
}
.malo-texto {
  color: var(--c-negative);
}
.expresion {
  font-variant-numeric: tabular-nums;
  color: var(--c-text-2);
}
.aviso-signo {
  color: var(--c-warning);
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
