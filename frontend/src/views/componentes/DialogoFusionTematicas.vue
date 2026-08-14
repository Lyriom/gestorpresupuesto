<script setup lang="ts">
/**
 * «Fusionar con…» (§2.6 y flujo §3.2).
 *
 * El objetivo del diálogo es que nadie fusione sin entender qué pasa con su
 * histórico, así que los números no son de adorno: vienen de
 * `POST /categories/merge/preview`, que simula la operación completa. Sin
 * destino elegido y sin la casilla marcada, «Fusionar» no se puede pulsar.
 */
import { computed, ref, watch } from 'vue'

import type { CategoriaFusionPrevia, CategoriaNodo } from '@/api/categorias'
import BotonBase from '@/components/ui/BotonBase.vue'
import EtiquetaCategoria from '@/components/ui/EtiquetaCategoria.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import { useAvisos } from '@/composables/useAvisos'
import { dinero } from '@/lib/formato'
import { ranuraDeCategoria, useCategorias } from '@/stores/categorias'

const props = defineProps<{
  abierto: boolean
  origen: CategoriaNodo | null
}>()

const emit = defineEmits<{ 'update:abierto': [valor: boolean]; fusionado: [] }>()

const categorias = useCategorias()
const avisos = useAvisos()

const destinoId = ref<string | number | null>(null)
const entendido = ref(false)
const previa = ref<CategoriaFusionPrevia | null>(null)
const cargandoPrevia = ref(false)
const errorDestino = ref<string | null>(null)

/** No se puede fusionar consigo misma ni con un descendiente (RN-18). */
const opcionesDestino = computed(() => {
  const origen = props.origen
  if (!origen) return []
  const prohibidos = categorias.descendientesDe(origen.id)
  return categorias
    .opciones(origen.kind)
    .filter((o) => o.valor !== origen.id && !prohibidos.has(String(o.valor)))
})

const puedeFusionar = computed(() => !!destinoId.value && entendido.value && !!previa.value)

const nombreDestino = computed(
  () => opcionesDestino.value.find((o) => o.valor === destinoId.value)?.etiqueta ?? '',
)

const sinHistorico = computed(() => (previa.value?.transactions ?? 0) === 0)

async function cargarPrevia(): Promise<void> {
  const origen = props.origen
  if (!origen || !destinoId.value) {
    previa.value = null
    return
  }
  cargandoPrevia.value = true
  errorDestino.value = null
  previa.value = await categorias.previsualizarFusion({
    source_ids: [origen.id],
    target_id: String(destinoId.value),
  })
  cargandoPrevia.value = false
}

async function fusionar(): Promise<void> {
  const origen = props.origen
  if (!origen) return
  if (!destinoId.value) {
    errorDestino.value = 'Elige la temática de destino.'
    return
  }
  const ok = await categorias.fusionar({
    source_ids: [origen.id],
    target_id: String(destinoId.value),
  })
  if (!ok) return
  // Sin «Deshacer» a propósito: el diálogo acaba de avisar de que es irreversible.
  avisos.exito('Fusionado correctamente.')
  emit('fusionado')
  emit('update:abierto', false)
}

watch(destinoId, () => void cargarPrevia())

watch(
  () => props.abierto,
  (abierto) => {
    if (!abierto) return
    destinoId.value = null
    entendido.value = false
    previa.value = null
    errorDestino.value = null
  },
)
</script>

<template>
  <ModalBase
    :abierto="abierto"
    :titulo="`Fusionar «${origen?.name ?? ''}»`"
    tamanyo="md"
    :guardando="categorias.guardando"
    :error="categorias.error ?? undefined"
    @update:abierto="emit('update:abierto', $event)"
    @cerrar="emit('update:abierto', false)"
  >
    <div class="cuerpo">
      <p class="intro">
        Vas a fusionar
        <EtiquetaCategoria
          v-if="origen"
          :nombre="origen.name"
          :ranura="ranuraDeCategoria(origen.color, origen.id)"
          tamanyo="sm"
        />
        con el destino que elijas.
      </p>

      <SelectorBase
        v-model="destinoId"
        etiqueta="Temática de destino"
        placeholder="Elige una temática…"
        :opciones="opcionesDestino"
        :cargando="categorias.cargando"
        :error="errorDestino ?? undefined"
        requerido
      />

      <EsqueletoCarga
        v-if="cargandoPrevia"
        variante="texto"
        :lineas="5"
        anuncio="Calculando qué se va a mover"
      />

      <template v-else-if="previa">
        <p v-if="sinHistorico" class="resumen">
          «{{ origen?.name }}» no tiene movimientos. Se fusionará igualmente para conservar su
          presupuesto.
        </p>
        <p v-else class="resumen">
          «{{ origen?.name }}» tiene {{ previa.transactions }}
          {{ previa.transactions === 1 ? 'movimiento' : 'movimientos' }}
          <template v-if="previa.splits > 0">y {{ previa.splits }} líneas de reparto</template>.
        </p>

        <div class="que-pasa">
          <p class="rotulo">Qué va a pasar</p>
          <ul>
            <li v-if="!sinHistorico">
              Los {{ previa.transactions }} movimientos de «{{ origen?.name }}» pasarán a estar
              etiquetados como «{{ nombreDestino }}», conservando su fecha e importe originales.
            </li>
            <li v-if="!sinHistorico">
              Los informes de meses anteriores también cambiarán: ese gasto pasado se contará
              desde ahora bajo «{{ nombreDestino }}».
            </li>
            <li v-if="previa.budget_periods > 0">
              El presupuesto asignado se sumará al del destino:
              {{ dinero(previa.allocations_merged) }} en
              {{ previa.budget_periods }}
              {{ previa.budget_periods === 1 ? 'periodo' : 'periodos' }}.
            </li>
            <li v-if="previa.children_moved > 0">
              Sus {{ previa.children_moved }}
              {{ previa.children_moved === 1 ? 'subcategoría' : 'subcategorías' }} pasarán a colgar
              del destino.
            </li>
            <li v-if="previa.rules > 0 || previa.recurring > 0">
              Se actualizarán {{ previa.rules }} reglas y {{ previa.recurring }} recurrentes que
              apuntaban a «{{ origen?.name }}».
            </li>
            <li v-if="previa.invoice_lines > 0">
              {{ previa.invoice_lines }} líneas de factura pasarán al destino.
            </li>
            <li>El color de «{{ origen?.name }}» quedará libre para una temática nueva.</li>
            <li class="grave">Esta acción no se puede deshacer.</li>
          </ul>
        </div>

        <ul v-if="previa.conflicts.length > 0" class="conflictos" role="alert">
          <li v-for="(c, i) in previa.conflicts" :key="i">{{ c }}</li>
        </ul>

        <InterruptorBase
          v-model="entendido"
          etiqueta="Entiendo que esta acción no se puede deshacer"
        />
      </template>
    </div>

    <template #pie>
      <BotonBase variante="contorno" @click="emit('update:abierto', false)">Cancelar</BotonBase>
      <BotonBase
        variante="peligro"
        :cargando="categorias.guardando"
        :deshabilitado="!puedeFusionar"
        @click="fusionar"
      >
        Fusionar
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
.intro,
.resumen {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.que-pasa {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-3);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background-color: var(--c-surface-2);
}
.rotulo {
  margin: 0;
  font-size: var(--t-sm);
  font-weight: 600;
}
.que-pasa ul {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin: 0;
  padding-left: var(--sp-5);
  font-size: var(--t-sm);
  line-height: var(--t-sm-lh);
  color: var(--c-text-2);
}
.grave {
  color: var(--c-negative);
  font-weight: 600;
}
.conflictos {
  margin: 0;
  padding: var(--sp-3) var(--sp-3) var(--sp-3) var(--sp-6);
  border-radius: var(--r-md);
  background-color: var(--c-warning-wash);
  color: var(--c-warning);
  font-size: var(--t-sm);
}
</style>
