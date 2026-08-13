<script setup lang="ts">
/**
 * Historial de importaciones, con la reversión de cada lote (RN-69).
 *
 * Deshacer borra **exactamente** los movimientos que creó el lote y respeta los
 * que se hayan editado a mano después, así que la acción sigue disponible
 * mientras el lote esté confirmado y sin deshacer.
 */
import { RotateCcw, Trash2 } from 'lucide-vue-next'

import {
  ETIQUETA_ESTADO_IMPORTACION,
  ETIQUETA_FORMATO,
  type Importacion,
} from '@/api/importaciones'
import BotonBase from '@/components/ui/BotonBase.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import { fechaCorta } from '@/lib/formato'
import { useCuentas } from '@/stores/cuentas'
import BloqueError from './BloqueError.vue'

const props = defineProps<{
  items: Importacion[]
  cargando?: boolean
  error?: string | null
  /** Identificador del lote que se está deshaciendo ahora mismo. */
  revirtiendo?: string | null
}>()

const emit = defineEmits<{
  retomar: [lote: Importacion]
  revertir: [lote: Importacion]
  descartar: [lote: Importacion]
  reintentar: []
}>()

const cuentas = useCuentas()

/** Se puede deshacer mientras esté confirmado y no se haya deshecho ya. */
function sePuedeDeshacer(lote: Importacion): boolean {
  return lote.status === 'committed' && !lote.rolled_back_at
}

function sePuedeRetomar(lote: Importacion): boolean {
  return ['analyzing', 'needs_mapping', 'ready'].includes(lote.status)
}

/** El servidor exige deshacer antes de borrar un lote confirmado. */
function sePuedeDescartar(lote: Importacion): boolean {
  return lote.status !== 'committed' || !!lote.rolled_back_at
}

function etiquetaEstado(lote: Importacion): string {
  if (lote.rolled_back_at) return 'Deshecha'
  return ETIQUETA_ESTADO_IMPORTACION[lote.status]
}

function tono(lote: Importacion): string {
  if (lote.rolled_back_at) return 'deshecha'
  if (lote.status === 'failed') return 'fallo'
  if (lote.status === 'committed') return 'hecha'
  if (lote.status === 'needs_mapping') return 'aviso'
  return 'curso'
}

function rango(lote: Importacion): string {
  if (!lote.date_from || !lote.date_to) return '—'
  if (lote.date_from === lote.date_to) return fechaCorta(lote.date_from)
  return `${fechaCorta(lote.date_from)} – ${fechaCorta(lote.date_to)}`
}

const hayItems = () => props.items.length > 0
</script>

<template>
  <section class="bloque" aria-labelledby="titulo-historial">
    <h2 id="titulo-historial" class="titulo">Importaciones anteriores</h2>

    <div v-if="cargando && !hayItems()" class="tarjeta caja">
      <EsqueletoCarga variante="texto" :lineas="4" anuncio="Cargando el historial" />
    </div>

    <BloqueError
      v-else-if="error"
      titulo="No se ha podido cargar el historial"
      :descripcion="error"
      @reintentar="emit('reintentar')"
    />

    <div v-else-if="!hayItems()" class="tarjeta caja">
      <EstadoVacio
        titulo="Todavía no has importado ningún extracto"
        descripcion="Cuando importes un fichero aparecerá aquí, con la opción de deshacerlo."
        :nivel="3"
      />
    </div>

    <div
      v-else
      class="tarjeta envoltorio-tabla"
      tabindex="0"
      role="group"
      aria-label="Historial de importaciones, desplazable en horizontal"
    >
      <table class="tabla">
        <caption class="oculto">
          Importaciones anteriores con su estado, los movimientos creados y la opción de deshacer
        </caption>
        <thead>
          <tr>
            <th scope="col">Subida</th>
            <th scope="col">Fichero</th>
            <th scope="col">Cuenta</th>
            <th scope="col">Periodo</th>
            <th scope="col">Estado</th>
            <th scope="col" class="num-col">Filas</th>
            <th scope="col" class="num-col">Movimientos</th>
            <th scope="col" class="acciones-col"><span class="oculto">Acciones</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="lote in items" :key="lote.id">
            <td>{{ fechaCorta(lote.created_at) }}</td>
            <td>
              <span class="fichero">{{ lote.filename }}</span>
              <span class="formato">{{ ETIQUETA_FORMATO[lote.format] }}</span>
            </td>
            <td>{{ cuentas.nombreDe(lote.account_id) }}</td>
            <td>{{ rango(lote) }}</td>
            <td>
              <span class="estado" :class="`estado--${tono(lote)}`">{{ etiquetaEstado(lote) }}</span>
            </td>
            <td class="num-col num">
              {{ lote.rows_total }}
              <span v-if="lote.rows_error > 0" class="detalle">
                · {{ lote.rows_error }} con error
              </span>
            </td>
            <td class="num-col num">{{ lote.transactions_created }}</td>
            <td class="acciones-col">
              <div class="acciones">
                <BotonBase
                  v-if="sePuedeRetomar(lote)"
                  variante="secundaria"
                  tamanyo="sm"
                  @click="emit('retomar', lote)"
                >
                  {{ lote.status === 'needs_mapping' ? 'Indicar columnas' : 'Continuar' }}
                </BotonBase>
                <BotonBase
                  v-if="sePuedeDeshacer(lote)"
                  variante="peligro-fantasma"
                  tamanyo="sm"
                  :icono="RotateCcw"
                  :cargando="revirtiendo === lote.id"
                  @click="emit('revertir', lote)"
                >
                  Deshacer
                </BotonBase>
                <BotonBase
                  v-if="sePuedeDescartar(lote)"
                  variante="fantasma"
                  tamanyo="sm"
                  solo-icono
                  :icono="Trash2"
                  :etiqueta-accesible="`Descartar la importación de ${lote.filename}`"
                  @click="emit('descartar', lote)"
                />
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.bloque {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.titulo {
  margin: 0;
  font-size: var(--t-h2);
  font-weight: 600;
}
.caja {
  padding: var(--sp-5);
}
.envoltorio-tabla {
  overflow-x: auto;
  padding: var(--sp-2) var(--sp-4) var(--sp-4);
}
.tabla {
  width: 100%;
  min-width: 860px;
  border-collapse: collapse;
  font-size: var(--t-sm);
}
.tabla thead th {
  padding: var(--sp-2);
  text-align: left;
  border-bottom: 1px solid var(--c-border);
  color: var(--c-text-3);
  font-weight: 500;
  white-space: nowrap;
}
.tabla td {
  padding: var(--sp-2);
  border-bottom: 1px solid var(--c-border-soft);
  vertical-align: middle;
}
.num-col {
  text-align: right;
  white-space: nowrap;
}
.acciones-col {
  width: 260px;
}
.acciones {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--sp-1);
}
.fichero {
  display: inline-block;
  max-width: 24ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.formato {
  margin-left: var(--sp-2);
  padding: 1px var(--sp-2);
  border: 1px solid var(--c-border);
  border-radius: var(--r-full);
  color: var(--c-text-3);
  font-size: var(--t-micro);
}
.estado {
  white-space: nowrap;
}
.estado--hecha {
  color: var(--c-positive);
}
.estado--fallo {
  color: var(--c-negative);
}
.estado--aviso {
  color: var(--c-warning);
}
.estado--deshecha,
.estado--curso {
  color: var(--c-text-2);
}
.detalle {
  color: var(--c-warning);
  font-size: var(--t-caption);
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
