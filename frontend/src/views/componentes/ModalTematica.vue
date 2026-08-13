<script setup lang="ts">
/**
 * Crear o editar una temática (§2.6).
 *
 * Renombrar no rompe el histórico (F-05): el identificador no cambia. El padre
 * no se toca aquí porque moverse en el árbol tiene su propio endpoint, que es el
 * único que comprueba ciclos y profundidad (RN-11).
 */
import { computed, ref, watch } from 'vue'

import type { CategoriaNodo } from '@/api/categorias'
import { PROFUNDIDAD_MAXIMA } from '@/api/categorias'
import { centimosDeImporte, importeDeCentimos } from '@/api/comun'
import BotonBase from '@/components/ui/BotonBase.vue'
import CampoImporte from '@/components/ui/CampoImporte.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import { PALETA_CATEGORICA } from '@/components/presupuesto/colores'
import { useAvisos } from '@/composables/useAvisos'
import { ranuraDeCategoria, useCategorias } from '@/stores/categorias'

const props = defineProps<{
  abierto: boolean
  /** `null` crea una nueva; con valor, edita esa. */
  tematica: CategoriaNodo | null
  /** Padre sugerido al crear una subcategoría. */
  padreId?: string | null
}>()

const emit = defineEmits<{ 'update:abierto': [valor: boolean]; guardado: [] }>()

const categorias = useCategorias()
const avisos = useAvisos()

const nombre = ref('')
const ranura = ref(1)
const padre = ref<string | number | null>(null)
const arrastre = ref(false)
const bloqueada = ref(false)
const objetivoCentimos = ref<number | null>(null)
const errorNombre = ref<string | null>(null)

const editando = computed(() => props.tematica !== null)
const titulo = computed(() => (editando.value ? 'Editar temática' : 'Nueva temática'))

/** Solo se puede colgar de una temática que no agote los seis niveles. */
const opcionesPadre = computed(() => [
  { valor: '', etiqueta: 'Ninguna (temática principal)' },
  ...categorias
    .opciones()
    .filter(
      (o) =>
        o.valor !== props.tematica?.id &&
        (categorias.porId.get(String(o.valor))?.depth ?? 0) < PROFUNDIDAD_MAXIMA - 1 &&
        !categorias.descendientesDe(props.tematica?.id ?? '').has(String(o.valor)),
    ),
])

async function guardar(): Promise<void> {
  errorNombre.value = null
  if (!nombre.value.trim()) {
    errorNombre.value = 'Este campo es obligatorio.'
    return
  }
  const comun = {
    name: nombre.value.trim(),
    color: String(ranura.value),
    rollover_enabled: arrastre.value,
    is_locked: bloqueada.value,
    monthly_target: importeDeCentimos(objetivoCentimos.value),
  }
  const ok = props.tematica
    ? await categorias.actualizar(props.tematica.id, comun)
    : await categorias.crear({ ...comun, parent_id: padre.value ? String(padre.value) : null })
  if (!ok) return
  avisos.exito(editando.value ? 'Temática guardada.' : 'Temática creada.')
  emit('guardado')
  emit('update:abierto', false)
}

watch(
  () => props.abierto,
  (abierto) => {
    if (!abierto) return
    const t = props.tematica
    nombre.value = t?.name ?? ''
    ranura.value = t ? ranuraDeCategoria(t.color, t.id) : 1
    padre.value = t?.parent_id ?? props.padreId ?? null
    arrastre.value = t?.rollover_enabled ?? false
    bloqueada.value = t?.is_locked ?? false
    objetivoCentimos.value = centimosDeImporte(t?.monthly_target ?? null)
    errorNombre.value = null
  },
)
</script>

<template>
  <ModalBase
    :abierto="abierto"
    :titulo="titulo"
    tamanyo="md"
    :guardando="categorias.guardando"
    :error="categorias.error ?? undefined"
    @update:abierto="emit('update:abierto', $event)"
    @cerrar="emit('update:abierto', false)"
  >
    <div class="cuerpo">
      <CampoTexto
        v-model="nombre"
        etiqueta="Nombre"
        placeholder="Alimentación"
        :error="errorNombre ?? undefined"
        requerido
      />

      <SelectorBase
        v-if="!editando"
        v-model="padre"
        etiqueta="Dentro de"
        ayuda="Una temática puede anidarse hasta seis niveles."
        :opciones="opcionesPadre"
      />

      <fieldset class="colores">
        <legend>Color</legend>
        <label v-for="(token, i) in PALETA_CATEGORICA" :key="i" class="muestra">
          <input v-model="ranura" type="radio" name="ranura" :value="i + 1" />
          <span class="tono" :style="{ background: token }" aria-hidden="true" />
          <span class="oculto">Color {{ i + 1 }} de 12</span>
        </label>
      </fieldset>

      <CampoImporte
        v-model="objetivoCentimos"
        etiqueta="Objetivo mensual"
        ayuda="Opcional: el importe que sueles querer asignar cada mes."
      />

      <InterruptorBase
        v-model="arrastre"
        etiqueta="Arrastrar lo que sobre al mes siguiente"
        descripcion="Lo que no gastes se suma al presupuesto del mes que viene."
      />
      <InterruptorBase
        v-model="bloqueada"
        etiqueta="No reasignar arrastrando"
        descripcion="Para importes fijos como la hipoteca o un seguro."
      />
    </div>

    <template #pie>
      <BotonBase variante="contorno" @click="emit('update:abierto', false)">Cancelar</BotonBase>
      <BotonBase variante="primaria" :cargando="categorias.guardando" @click="guardar">
        Guardar
      </BotonBase>
    </template>
  </ModalBase>
</template>

<style scoped>
.cuerpo {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.colores {
  margin: 0;
  padding: 0;
  border: 0;
}
.colores legend {
  padding: 0 0 var(--sp-2);
  font-size: var(--t-sm);
  font-weight: 600;
}
.colores {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}
.muestra {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--r-md);
  cursor: pointer;
}
.muestra:has(input:checked) {
  outline: 2px solid var(--c-accent);
  outline-offset: -2px;
}
.muestra:has(input:focus-visible) {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}
.tono {
  display: block;
  width: 24px;
  height: 24px;
  border-radius: var(--r-full);
}
.muestra input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}
.oculto {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>
