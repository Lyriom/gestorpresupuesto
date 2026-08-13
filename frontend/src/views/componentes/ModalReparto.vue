<script setup lang="ts">
/**
 * «Cambiar asignación»: un campo de importe por temática y el contador de lo que
 * queda sin asignar.
 *
 * Es la alternativa siempre disponible al arrastre en la barra (§3.4 de los
 * flujos): el mismo camino que usa alguien con lector de pantalla, con teclado
 * sin ratón, o simplemente sin ganas de arrastrar nada.
 */
import { computed, ref, watch } from 'vue'
import { Lock } from 'lucide-vue-next'

import { centimosDeImporte, importeDeCentimos } from '@/api/comun'
import type { AsignacionCrear } from '@/api/presupuestos'
import BotonBase from '@/components/ui/BotonBase.vue'
import CampoImporte from '@/components/ui/CampoImporte.vue'
import EtiquetaCategoria from '@/components/ui/EtiquetaCategoria.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import PistaAyuda from '@/components/ui/PistaAyuda.vue'
import { aNumero, etiquetaPeriodo, euros } from '@/lib/formato'
import { ranuraDeCategoria } from '@/stores/categorias'
import { usePresupuesto } from '@/stores/presupuesto'

const props = defineProps<{
  abierto: boolean
  /** Temática que recibe el foco al abrir, si se llega desde un aviso. */
  destacada?: string | null
}>()

const emit = defineEmits<{ 'update:abierto': [valor: boolean]; guardado: [] }>()

const presupuesto = usePresupuesto()

/** Céntimos por temática, editables. */
const valores = ref<Record<string, number | null>>({})

const ingresos = computed(() => centimosDeImporte(presupuesto.mes?.income) ?? 0)
const asignado = computed(() =>
  Object.values(valores.value).reduce<number>((suma, v) => suma + (v ?? 0), 0),
)
const sinAsignar = computed(() => ingresos.value - asignado.value)
const sobreasignado = computed(() => sinAsignar.value < 0)

/** No se puede bajar de lo ya gastado: ese dinero ya salió. */
function minimoDe(categoryId: string): number {
  const a = presupuesto.asignaciones.find((x) => x.category_id === categoryId)
  return a ? Math.round(aNumero(a.spent) * 100) : 0
}

function errorDe(categoryId: string): string | undefined {
  const minimo = minimoDe(categoryId)
  const valor = valores.value[categoryId] ?? 0
  if (minimo > 0 && valor < minimo) {
    return `No puedes bajar de ${euros(minimo / 100)}: ya lo has gastado.`
  }
  return undefined
}

const hayErrores = computed(() =>
  presupuesto.asignaciones.some((a) => !!errorDe(a.category_id)),
)

async function guardar(): Promise<void> {
  const allocations: AsignacionCrear[] = presupuesto.asignaciones.map((a) => ({
    category_id: a.category_id,
    amount: importeDeCentimos(valores.value[a.category_id] ?? 0) ?? '0.00',
  }))
  const ok = await presupuesto.guardarReparto(allocations)
  if (ok) {
    emit('guardado')
    emit('update:abierto', false)
  }
}

watch(
  () => props.abierto,
  (abierto) => {
    if (!abierto) return
    const mapa: Record<string, number | null> = {}
    for (const a of presupuesto.asignaciones) {
      mapa[a.category_id] = centimosDeImporte(a.allocated)
    }
    valores.value = mapa
  },
  { immediate: true },
)
</script>

<template>
  <ModalBase
    :abierto="abierto"
    titulo="Cambiar asignación"
    :subtitulo="presupuesto.mes ? etiquetaPeriodo(presupuesto.mes.period) : undefined"
    tamanyo="lg"
    :guardando="presupuesto.guardando"
    :error="presupuesto.error ?? undefined"
    @update:abierto="emit('update:abierto', $event)"
    @cerrar="emit('update:abierto', false)"
  >
    <ul class="lista">
      <li
        v-for="a in presupuesto.asignaciones"
        :key="a.category_id"
        class="fila"
        :class="{ destacada: destacada === a.category_id }"
      >
        <span class="nombre">
          <EtiquetaCategoria
            :nombre="a.category.name"
            :ranura="ranuraDeCategoria(a.category.color, a.category_id)"
            tamanyo="sm"
          />
          <PistaAyuda
            v-if="a.is_locked"
            texto="Temática bloqueada: no se reasigna arrastrando en la barra."
          >
            <Lock :size="14" aria-hidden="true" />
          </PistaAyuda>
        </span>
        <span class="gastado num">{{ euros(a.spent) }} gastados</span>
        <CampoImporte
          :model-value="valores[a.category_id] ?? null"
          :etiqueta="`Asignado a ${a.category.name}`"
          etiqueta-oculta
          :deshabilitado="a.is_locked"
          :error="errorDe(a.category_id)"
          @update:model-value="valores[a.category_id] = $event"
        />
      </li>
    </ul>

    <p v-if="presupuesto.asignaciones.length === 0" class="vacio">
      Este mes todavía no tiene ninguna temática con presupuesto.
    </p>

    <template #pie>
      <p class="contador num" :class="{ mal: sobreasignado }" role="status">
        Sin asignar <strong>{{ euros(sinAsignar / 100) }}</strong>
        <span v-if="sobreasignado"> · has repartido más de lo que ingresas</span>
      </p>
      <BotonBase variante="contorno" @click="emit('update:abierto', false)">Cancelar</BotonBase>
      <BotonBase
        variante="primaria"
        :cargando="presupuesto.guardando"
        :deshabilitado="hayErrores || presupuesto.asignaciones.length === 0"
        @click="guardar"
      >
        Guardar
      </BotonBase>
    </template>
  </ModalBase>
</template>

<style scoped>
.lista {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.fila {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 180px;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-2);
  border-radius: var(--r-md);
}
.fila.destacada {
  background-color: var(--c-surface-3);
}
.nombre {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
  color: var(--c-text-3);
}
.gastado {
  font-size: var(--t-caption);
  color: var(--c-text-3);
  white-space: nowrap;
}
.contador {
  flex: 1 1 auto;
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.contador strong {
  color: var(--c-text-1);
}
.contador.mal,
.contador.mal strong {
  color: var(--c-warning);
}
.vacio {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}

@media (max-width: 767px) {
  .fila {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
