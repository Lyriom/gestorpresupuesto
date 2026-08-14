<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from 'vue'
import { onClickOutside } from '@vueuse/core'
import { Calendar, ChevronLeft, ChevronRight, CircleAlert } from 'lucide-vue-next'
import { fechaLarga, localeActual, mesAnyo } from '@/lib/formato'

const props = withDefaults(
  defineProps<{
    /** Fecha en ISO `AAAA-MM-DD`, o `null`. */
    modelValue: string | null
    etiqueta?: string
    ayuda?: string
    error?: string
    deshabilitado?: boolean
    requerido?: boolean
    minima?: string
    maxima?: string
    /** ISO → nº de transacciones. Pinta el punto de 3 px bajo el día. */
    diasConDatos?: Record<string, number>
  }>(),
  { etiqueta: 'Fecha' },
)

const emit = defineEmits<{ 'update:modelValue': [iso: string | null] }>()

const base = useId()
const idCampo = `${base}-campo`
const idAyuda = `${base}-ayuda`
const idPanel = `${base}-panel`

const abierto = ref(false)
const texto = ref('')
const errorInterno = ref<string | null>(null)
const raiz = ref<HTMLElement | null>(null)
const rejilla = ref<HTMLElement | null>(null)

const CABECERAS = ['L', 'M', 'X', 'J', 'V', 'S', 'D']
const HOY_ISO = aIso(new Date())

function aIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function deIso(iso: string | null): Date | null {
  if (!iso) return null
  const [a, m, d] = iso.split('-').map(Number)
  if (!a || !m || !d) return null
  const fecha = new Date(a, m - 1, d)
  return Number.isNaN(fecha.getTime()) ? null : fecha
}

function aMascara(iso: string | null): string {
  const d = deIso(iso)
  if (!d) return ''
  return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`
}

function deMascara(valor: string): string | null {
  const m = valor.match(/^(\d{2})\/(\d{2})\/(\d{4})$/)
  if (!m) return null
  const [, dd, mm, aaaa] = m
  const fecha = new Date(Number(aaaa), Number(mm) - 1, Number(dd))
  if (fecha.getDate() !== Number(dd) || fecha.getMonth() !== Number(mm) - 1) return null
  return aIso(fecha)
}

/* ---------- Estado del panel -------------------------------------------- */

const enfocada = ref<string>(props.modelValue ?? HOY_ISO)
const mesVisible = ref<Date>(deIso(props.modelValue) ?? new Date())

const etiquetaMes = computed(() => mesAnyo(mesVisible.value))

/** Semanas del mes visible; los días de otros meses se ocultan, no se atenúan. */
const semanas = computed<Array<Array<string | null>>>(() => {
  const primero = new Date(mesVisible.value.getFullYear(), mesVisible.value.getMonth(), 1)
  const ultimo = new Date(mesVisible.value.getFullYear(), mesVisible.value.getMonth() + 1, 0)
  const hueco = (primero.getDay() + 6) % 7 // lunes = 0
  const celdas: Array<string | null> = Array.from({ length: hueco }, () => null)
  for (let dia = 1; dia <= ultimo.getDate(); dia++) {
    celdas.push(aIso(new Date(primero.getFullYear(), primero.getMonth(), dia)))
  }
  while (celdas.length % 7 !== 0) celdas.push(null)
  return Array.from({ length: celdas.length / 7 }, (_, i) => celdas.slice(i * 7, i * 7 + 7))
})

function fueraDeRango(iso: string): boolean {
  if (props.minima && iso < props.minima) return true
  if (props.maxima && iso > props.maxima) return true
  return false
}

function esFinDeSemana(iso: string): boolean {
  const d = deIso(iso)
  return d ? d.getDay() === 0 || d.getDay() === 6 : false
}

function etiquetaDia(iso: string): string {
  const cuantas = props.diasConDatos?.[iso]
  const dia = fechaLarga(iso)
  const semana = deIso(iso)?.toLocaleDateString(localeActual(), { weekday: 'long' }) ?? ''
  const cabeza = `${semana}, ${dia}`
  if (!cuantas) return cabeza
  return `${cabeza}, ${cuantas} ${cuantas === 1 ? 'transacción' : 'transacciones'}`
}

/* ---------- Interacción ------------------------------------------------- */

function abrir(): void {
  if (props.deshabilitado) return
  abierto.value = true
  enfocada.value = props.modelValue ?? HOY_ISO
  mesVisible.value = deIso(enfocada.value) ?? new Date()
  void enfocarDia()
}

function cerrar(devolverFoco = true): void {
  if (!abierto.value) return
  abierto.value = false
  if (devolverFoco) (document.getElementById(idCampo) as HTMLInputElement | null)?.focus()
}

async function enfocarDia(): Promise<void> {
  await nextTick()
  rejilla.value?.querySelector<HTMLElement>('[data-enfocado="true"]')?.focus()
}

function elegir(iso: string): void {
  if (fueraDeRango(iso)) return
  errorInterno.value = null
  texto.value = aMascara(iso)
  emit('update:modelValue', iso)
  cerrar()
}

function desplazar(dias: number): void {
  const d = deIso(enfocada.value)
  if (!d) return
  d.setDate(d.getDate() + dias)
  enfocada.value = aIso(d)
  mesVisible.value = new Date(d.getFullYear(), d.getMonth(), 1)
  void enfocarDia()
}

function cambiarMes(meses: number): void {
  const d = deIso(enfocada.value) ?? new Date()
  d.setMonth(d.getMonth() + meses)
  enfocada.value = aIso(d)
  mesVisible.value = new Date(d.getFullYear(), d.getMonth(), 1)
  void enfocarDia()
}

function alTeclearRejilla(evento: KeyboardEvent): void {
  const acciones: Record<string, () => void> = {
    ArrowLeft: () => desplazar(-1),
    ArrowRight: () => desplazar(1),
    ArrowUp: () => desplazar(-7),
    ArrowDown: () => desplazar(7),
    Home: () => desplazar(-((deIso(enfocada.value)!.getDay() + 6) % 7)),
    End: () => desplazar(6 - ((deIso(enfocada.value)!.getDay() + 6) % 7)),
    PageUp: () => cambiarMes(evento.shiftKey ? -12 : -1),
    PageDown: () => cambiarMes(evento.shiftKey ? 12 : 1),
  }
  const accion = acciones[evento.key]
  if (!accion) return
  evento.preventDefault()
  accion()
}

/** Atajos de la columna izquierda. */
const ATAJOS: ReadonlyArray<{ etiqueta: string; calcular: () => Date }> = [
  { etiqueta: 'Hoy', calcular: () => new Date() },
  {
    etiqueta: 'Ayer',
    calcular: () => {
      const d = new Date()
      d.setDate(d.getDate() - 1)
      return d
    },
  },
  {
    etiqueta: 'Primer día del mes',
    calcular: () => {
      const d = new Date()
      return new Date(d.getFullYear(), d.getMonth(), 1)
    },
  },
  {
    etiqueta: 'Último día del mes',
    calcular: () => {
      const d = new Date()
      return new Date(d.getFullYear(), d.getMonth() + 1, 0)
    },
  },
  {
    etiqueta: 'Hace 30 días',
    calcular: () => {
      const d = new Date()
      d.setDate(d.getDate() - 30)
      return d
    },
  },
]

/* ---------- Entrada manual: siempre funciona ---------------------------- */

function alEscribir(evento: Event): void {
  const el = evento.target as HTMLInputElement
  const digitos = el.value.replace(/\D/g, '').slice(0, 8)
  let salida = digitos.slice(0, 2)
  if (digitos.length > 2) salida += `/${digitos.slice(2, 4)}`
  if (digitos.length > 4) salida += `/${digitos.slice(4, 8)}`
  texto.value = salida
  el.value = salida
  errorInterno.value = null
  if (salida === '') emit('update:modelValue', null)
}

function alSalir(): void {
  if (!texto.value) {
    errorInterno.value = null
    emit('update:modelValue', null)
    return
  }
  const iso = deMascara(texto.value)
  if (!iso) {
    errorInterno.value = 'Introduce una fecha con el formato 13/08/2026.'
    return
  }
  if (fueraDeRango(iso)) {
    errorInterno.value = 'Esa fecha está fuera del periodo permitido.'
    return
  }
  errorInterno.value = null
  emit('update:modelValue', iso)
}

const errorVisible = computed(() => props.error ?? errorInterno.value)

watch(
  () => props.modelValue,
  (valor) => {
    texto.value = aMascara(valor)
  },
  { immediate: true },
)

onClickOutside(raiz, () => cerrar(false))
</script>

<template>
  <div ref="raiz" class="campo">
    <label :for="idCampo">
      {{ etiqueta }}<span v-if="requerido" class="requerido" aria-hidden="true"> *</span>
    </label>

    <div class="caja" :class="{ malo: !!errorVisible, inactivo: deshabilitado }">
      <input
        :id="idCampo"
        :value="texto"
        type="text"
        inputmode="numeric"
        autocomplete="off"
        placeholder="dd/mm/aaaa"
        :disabled="deshabilitado"
        :aria-invalid="errorVisible ? 'true' : undefined"
        :aria-describedby="idAyuda"
        @input="alEscribir"
        @blur="alSalir"
        @keydown.down.prevent="abrir"
      />
      <button
        type="button"
        class="boton-calendario"
        aria-label="Elegir fecha en el calendario"
        :aria-expanded="abierto"
        :aria-controls="idPanel"
        :disabled="deshabilitado"
        @click="abierto ? cerrar() : abrir()"
      >
        <Calendar :size="16" aria-hidden="true" />
      </button>
    </div>

    <p v-if="errorVisible" :id="idAyuda" class="mensaje malo-texto" aria-live="polite">
      <CircleAlert :size="14" aria-hidden="true" />{{ errorVisible }}
    </p>
    <p v-else :id="idAyuda" class="mensaje">
      {{ ayuda ?? 'Puedes escribirla a mano: 13/08/2026' }}
    </p>

    <div
      v-if="abierto"
      :id="idPanel"
      class="panel elev-3"
      role="dialog"
      :aria-modal="false"
      aria-label="Elegir fecha"
      @keydown.escape.stop="cerrar()"
    >
      <ul class="atajos">
        <li v-for="a in ATAJOS" :key="a.etiqueta">
          <button type="button" @click="elegir(aIso(a.calcular()))">{{ a.etiqueta }}</button>
        </li>
      </ul>

      <div class="calendario">
        <div class="cabecera-mes">
          <button type="button" aria-label="Mes anterior" @click="cambiarMes(-1)">
            <ChevronLeft :size="16" aria-hidden="true" />
          </button>
          <span aria-live="polite">{{ etiquetaMes }}</span>
          <button type="button" aria-label="Mes siguiente" @click="cambiarMes(1)">
            <ChevronRight :size="16" aria-hidden="true" />
          </button>
        </div>

        <table ref="rejilla" class="rejilla" role="grid" @keydown="alTeclearRejilla">
          <thead>
            <tr>
              <th v-for="c in CABECERAS" :key="c" scope="col" class="micro">{{ c }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(semana, i) in semanas" :key="i">
              <td v-for="(iso, j) in semana" :key="j" role="gridcell">
                <button
                  v-if="iso"
                  type="button"
                  class="dia"
                  :class="{
                    hoy: iso === HOY_ISO,
                    elegido: iso === modelValue,
                    finde: esFinDeSemana(iso),
                  }"
                  :data-enfocado="iso === enfocada"
                  :tabindex="iso === enfocada ? 0 : -1"
                  :disabled="fueraDeRango(iso)"
                  :aria-selected="iso === modelValue"
                  :aria-label="etiquetaDia(iso)"
                  @click="elegir(iso)"
                  @focus="enfocada = iso"
                >
                  {{ Number(iso.slice(8)) }}
                  <span v-if="diasConDatos?.[iso]" class="punto" aria-hidden="true" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="pie">
          <button type="button" class="texto" @click="texto = ''; emit('update:modelValue', null); cerrar()">
            Borrar
          </button>
          <button type="button" class="principal" @click="elegir(enfocada)">Aplicar</button>
        </div>
      </div>
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

.caja {
  display: flex;
  align-items: center;
  height: 40px;
  padding-left: var(--sp-3);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background-color: var(--c-surface-2);
  transition: border-color var(--dur-instant) var(--ease-in-out);
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
  font-variant-numeric: tabular-nums;
}
input:focus {
  outline: none;
}

.boton-calendario {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 100%;
  border: 0;
  background: none;
  color: var(--c-text-3);
  cursor: pointer;
}
.boton-calendario:hover {
  color: var(--c-text-1);
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

/* --- Panel -------------------------------------------------------------- */
.panel {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 50;
  display: flex;
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  background-color: var(--c-surface-2);
}
.atajos {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: var(--sp-2);
  border-right: 1px solid var(--c-border);
  list-style: none;
  min-width: 148px;
}
.atajos button {
  width: 100%;
  min-height: 32px;
  padding-inline: var(--sp-2);
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--c-text-2);
  font-family: inherit;
  font-size: var(--t-caption);
  text-align: left;
  cursor: pointer;
}
.atajos button:hover {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}

.calendario {
  padding: var(--sp-2);
}
.cabecera-mes {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  padding: var(--sp-1) var(--sp-2) var(--sp-2);
  font-size: var(--t-h3);
  font-weight: 600;
}
.cabecera-mes button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--c-text-2);
  cursor: pointer;
}
.cabecera-mes button:hover {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}

.rejilla {
  border-collapse: collapse;
}
.micro {
  padding-bottom: var(--sp-1);
  font-size: var(--t-micro);
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--c-text-3);
  text-transform: uppercase;
}
td {
  padding: 1px;
}
.dia {
  position: relative;
  width: 34px;
  height: 34px;
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  background: none;
  color: var(--c-text-1);
  font-family: inherit;
  font-size: var(--t-caption);
  font-variant-numeric: tabular-nums;
  cursor: pointer;
}
.dia:hover:not(:disabled) {
  background-color: var(--c-surface-3);
}
.dia.finde {
  color: var(--c-text-3);
}
.dia.hoy {
  border-color: var(--c-accent);
}
.dia.elegido {
  background-color: var(--c-accent);
  color: var(--c-text-on-fill);
}
.dia.elegido:focus-visible {
  outline-color: var(--c-text-1);
}
.dia:disabled {
  color: var(--c-text-disabled);
  cursor: not-allowed;
}
.punto {
  position: absolute;
  bottom: 3px;
  left: 50%;
  width: 3px;
  height: 3px;
  translate: -50% 0;
  border-radius: var(--r-full);
  background-color: currentcolor;
}

.pie {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
  padding-top: var(--sp-2);
  border-top: 1px solid var(--c-border);
}
.pie button {
  min-height: 32px;
  padding-inline: var(--sp-3);
  border: 1px solid transparent;
  border-radius: var(--r-md);
  font-family: inherit;
  font-size: var(--t-caption);
  font-weight: 600;
  cursor: pointer;
}
.pie .texto {
  background: none;
  color: var(--c-text-2);
}
.pie .texto:hover {
  color: var(--c-text-1);
}
.pie .principal {
  background-color: var(--c-accent);
  color: var(--c-text-on-fill);
}

@media (max-width: 639px) {
  .atajos {
    display: none;
  }
}
</style>
