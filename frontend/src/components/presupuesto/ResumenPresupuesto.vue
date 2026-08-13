<script setup lang="ts">
/**
 * Las cifras del mes en tarjetas, con los avisos que el backend ya trae
 * redactados.
 *
 * Los avisos no se reinterpretan aquí: vienen escritos en español desde
 * `services/presupuesto.py` y se muestran tal cual. Lo que sí se deriva de los
 * datos es su severidad, porque el texto no la lleva: un sobrepaso es rojo, y
 * sobreasignar es ámbar —repartir más de lo que entra es un plan arriesgado, no
 * un error consumado.
 */
import { computed } from 'vue'
import {
  ArrowDownRight,
  ArrowUpRight,
  CircleAlert,
  Info,
  TriangleAlert,
  Wallet,
} from 'lucide-vue-next'

import { aNumero, etiquetaPeriodo, euros, porcentaje } from '@/lib/formato'
import type { BarraPresupuesto as DatosBarra, ClaveCifra } from './types'

const props = withDefaults(
  defineProps<{
    barra: DatosBarra | null
    cargando?: boolean
    /** Cifra que se pinta en grande. Solo una por vista, y puede que ya la tenga la barra. */
    destacada?: ClaveCifra | null
    mostrarAvisos?: boolean
  }>(),
  { cargando: false, destacada: null, mostrarAvisos: true },
)

type Tono = 'neutro' | 'positivo' | 'negativo' | 'aviso'

interface Cifra {
  clave: ClaveCifra | 'arrastrado'
  etiqueta: string
  valor: string
  nota: string
  tono: Tono
  icono: 'entrada' | 'salida' | 'cartera' | 'aviso' | null
}

const cifras = computed<Cifra[]>(() => {
  const b = props.barra
  const ingresos = aNumero(b?.ingresos)
  const asignado = aNumero(b?.total_asignado)
  const gastado = aNumero(b?.total_gastado)
  const arrastrado = aNumero(b?.total_arrastrado)
  const sinAsignar = aNumero(b?.sin_asignar)
  const disponible = aNumero(b?.disponible)
  const pctAsignado = aNumero(b?.porcentaje_asignado)
  const pctGastado = aNumero(b?.porcentaje_gastado)

  const lista: Cifra[] = [
    {
      clave: 'ingresos',
      etiqueta: 'Ingresos',
      valor: euros(ingresos),
      nota: ingresos > 0 ? 'Lo que ha entrado este mes' : 'Todavía sin ingresos registrados',
      tono: 'neutro',
      icono: 'entrada',
    },
    {
      clave: 'asignado',
      etiqueta: 'Asignado',
      valor: euros(asignado),
      nota:
        ingresos > 0
          ? `${porcentaje(pctAsignado / 100)} de los ingresos`
          : 'Sin ingresos con los que compararlo',
      tono: sinAsignar < 0 ? 'aviso' : 'neutro',
      icono: sinAsignar < 0 ? 'aviso' : null,
    },
    {
      clave: 'gastado',
      etiqueta: 'Gastado',
      valor: euros(gastado),
      nota: `${porcentaje(pctGastado / 100)} de la barra`,
      tono: 'neutro',
      icono: 'salida',
    },
    {
      clave: 'disponible',
      etiqueta: 'Disponible',
      valor: euros(disponible),
      nota:
        disponible < 0
          ? 'Has gastado más de lo que tenías'
          : 'Ingresos más arrastres menos gastos',
      tono: disponible < 0 ? 'negativo' : disponible > 0 ? 'positivo' : 'neutro',
      icono: 'cartera',
    },
    {
      clave: 'sinAsignar',
      etiqueta: 'Sin asignar',
      valor: euros(sinAsignar),
      nota:
        sinAsignar < 0
          ? 'Sobreasignado: repartido más de lo que entra'
          : sinAsignar === 0
            ? 'Todo repartido'
            : 'Pendiente de repartir entre temáticas',
      tono: sinAsignar < 0 ? 'aviso' : 'neutro',
      icono: sinAsignar < 0 ? 'aviso' : null,
    },
  ]

  // El arrastre solo ocupa sitio cuando existe: una tarjeta a cero es ruido.
  if (arrastrado !== 0) {
    lista.push({
      clave: 'arrastrado',
      etiqueta: 'Arrastrado',
      valor: euros(arrastrado),
      nota: 'Viene del mes anterior',
      tono: 'neutro',
      icono: null,
    })
  }

  return lista
})

/**
 * Severidad de cada aviso, deducida de los datos y no del texto: rojo si hay
 * sobrepaso, ámbar si hay sobreasignación, informativo en el resto.
 */
const avisos = computed(() => {
  const b = props.barra
  if (!props.mostrarAvisos || !b) return []
  const haySobrepaso = b.segmentos.some((s) => s.estado === 'sobrepasado')
  const sobreasignado = aNumero(b.sin_asignar) < 0
  return b.avisos.map((texto, i) => ({
    clave: `aviso-${i}`,
    texto,
    tono: (haySobrepaso ? 'negativo' : sobreasignado ? 'aviso' : 'info') as
      | 'negativo'
      | 'aviso'
      | 'info',
  }))
})

const titulo = computed(() =>
  props.barra ? `Resumen de ${etiquetaPeriodo(props.barra.periodo).toLowerCase()}` : 'Resumen del mes',
)
</script>

<template>
  <section class="resumen" :aria-label="titulo">
    <template v-if="props.cargando">
      <ul class="rejilla">
        <li v-for="n in 5" :key="n" class="tarjeta">
          <span class="esqueleto esqueleto--etiqueta" />
          <span class="esqueleto esqueleto--valor" />
        </li>
      </ul>
      <p class="solo-lectores" role="status">Cargando el resumen del mes.</p>
    </template>

    <template v-else>
      <ul class="rejilla">
        <li
          v-for="c in cifras"
          :key="c.clave"
          class="tarjeta"
          :class="[`tarjeta--${c.tono}`, { 'tarjeta--destacada': props.destacada === c.clave }]"
        >
          <p class="etiqueta">
            <ArrowUpRight v-if="c.icono === 'entrada'" :size="14" aria-hidden="true" />
            <ArrowDownRight v-else-if="c.icono === 'salida'" :size="14" aria-hidden="true" />
            <Wallet v-else-if="c.icono === 'cartera'" :size="14" aria-hidden="true" />
            <CircleAlert v-else-if="c.icono === 'aviso'" :size="14" aria-hidden="true" />
            {{ c.etiqueta }}
          </p>
          <p class="valor">{{ c.valor }}</p>
          <p class="nota">{{ c.nota }}</p>
        </li>
      </ul>

      <ul v-if="avisos.length > 0" class="avisos" aria-live="polite" aria-label="Avisos del mes">
        <li v-for="a in avisos" :key="a.clave" class="aviso" :class="`aviso--${a.tono}`">
          <TriangleAlert v-if="a.tono === 'negativo'" :size="16" aria-hidden="true" />
          <CircleAlert v-else-if="a.tono === 'aviso'" :size="16" aria-hidden="true" />
          <Info v-else :size="16" aria-hidden="true" />
          <span>{{ a.texto }}</span>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.resumen {
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-family: var(--font-sans, system-ui, sans-serif);
  color: var(--c-text-1);
}

.rejilla {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

@media (min-width: 640px) {
  .rejilla {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (min-width: 1280px) {
  .rejilla {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.tarjeta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-xl, 16px);
}

.etiqueta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: var(--c-text-3);
  font-size: var(--t-sm, 0.875rem);
}

.valor {
  margin: 0;
  font-size: var(--t-display, 1.75rem);
  font-weight: 600;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}

.tarjeta--destacada .valor {
  font-size: var(--t-hero, 2.5rem);
  line-height: 1.05;
}

.nota {
  margin: 0;
  color: var(--c-text-2);
  font-size: var(--t-caption, 0.8125rem);
}

.tarjeta--positivo .valor {
  color: var(--c-positive);
}

.tarjeta--negativo .valor {
  color: var(--c-negative);
}

.tarjeta--negativo {
  border-color: var(--c-negative);
}

.tarjeta--aviso .valor {
  color: var(--c-warning);
}

.tarjeta--aviso .etiqueta {
  color: var(--c-warning);
}

.avisos {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.aviso {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--r-lg, 12px);
  font-size: var(--t-sm, 0.875rem);
  line-height: 1.4;
}

.aviso--negativo {
  background: var(--c-negative-wash);
  color: var(--c-negative);
}

.aviso--aviso {
  background: var(--c-warning-wash);
  color: var(--c-warning);
}

.aviso--info {
  background: var(--c-info-wash);
  color: var(--c-info);
}

.aviso svg {
  flex: 0 0 auto;
  margin-top: 2px;
}

.esqueleto {
  display: block;
  border-radius: var(--r-md, 8px);
  background: linear-gradient(
    90deg,
    var(--c-surface-3) 0%,
    var(--c-surface-2) 50%,
    var(--c-surface-3) 100%
  );
}

.esqueleto--etiqueta {
  width: 45%;
  height: 14px;
}

.esqueleto--valor {
  width: 70%;
  height: 28px;
}

.solo-lectores {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}
</style>
