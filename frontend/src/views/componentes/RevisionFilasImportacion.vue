<script setup lang="ts">
/**
 * Revisión de las filas del extracto antes de crear los movimientos (RN-67).
 *
 * Mismo criterio que la revisión de líneas de factura: la interfaz dice **qué
 * revisar** y nada se guarda sin pasar por aquí. Tres estados por fila, y cada
 * uno con icono y palabra además del color (§2.3):
 *
 * - Correcta: `✓`, sin realce; se importa.
 * - Con error: `⚠`, fondo de aviso y el motivo del servidor. Se corrige en la
 *   propia fila (fecha, concepto, importe) o se excluye.
 * - Duplicada: `⧉`; ya está registrada, se omite por defecto y el usuario puede
 *   decidir importarla igual con el interruptor de la fila (RN-68).
 *
 * Al corregir una fila el servidor recalcula su huella y le quita el error, así
 * que la respuesta del `PATCH` es la que manda: aquí no se adivina el estado.
 */
import { computed, ref, watch } from 'vue'
import { Check, Copy, RotateCcw, TriangleAlert, X } from 'lucide-vue-next'

import { ETIQUETA_ESTADO_FILA, type FilaImportacion } from '@/api/importaciones'
import BotonBase from '@/components/ui/BotonBase.vue'
import CampoFecha from '@/components/ui/CampoFecha.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import PestanyasBase from '@/components/ui/PestanyasBase.vue'
import { aNumero, dinero, fechaCorta, parsearImporte , simboloDe } from '@/lib/formato'

const props = defineProps<{
  filas: FilaImportacion[]
  cargando?: boolean
  /** Filas con una corrección en vuelo, para bloquear solo esas. */
  enCurso: (filaId: string) => boolean
  /** Se ha llegado al tope de filas del análisis. */
  truncadas?: boolean
}>()

const emit = defineEmits<{
  corregir: [
    filaId: string,
    cambios: { date?: string | null; amount?: string | null; description?: string | null },
  ]
  excluir: [fila: FilaImportacion, excluida: boolean]
  duplicada: [fila: FilaImportacion, duplicada: boolean]
}>()

type Vista = 'todas' | 'errores' | 'duplicadas' | 'excluidas'

interface Borrador {
  date: string | null
  importe: string
  description: string
}

const vista = ref<Vista>('todas')
const borradores = ref<Record<string, Borrador>>({})
/** Filas correctas que el usuario ha abierto para editar a mano. */
const abiertas = ref<string[]>([])
/**
 * Filas que han llegado marcadas como duplicadas alguna vez.
 *
 * Al desmarcar una, el servidor la devuelve ya como válida y sin rastro del
 * duplicado; sin esta lista el interruptor desaparecería y no habría forma de
 * volver a marcarla.
 */
const eranDuplicadas = ref<string[]>([])

watch(
  () => props.filas,
  (filas) => {
    const nuevas = filas.filter((f) => f.is_duplicate).map((f) => f.id)
    const pendientes = nuevas.filter((id) => !eranDuplicadas.value.includes(id))
    if (pendientes.length > 0) eranDuplicadas.value = [...eranDuplicadas.value, ...pendientes]
  },
  { immediate: true },
)

function cambiarVista(valor: string | number): void {
  vista.value = valor as Vista
}

const pestanyas = computed(() => [
  { valor: 'todas', etiqueta: 'Todas', contador: props.filas.length },
  {
    valor: 'errores',
    etiqueta: 'Con error',
    contador: props.filas.filter((f) => conProblema(f)).length,
  },
  {
    valor: 'duplicadas',
    etiqueta: 'Duplicadas',
    contador: props.filas.filter((f) => f.is_duplicate).length,
  },
  {
    valor: 'excluidas',
    etiqueta: 'Excluidas',
    contador: props.filas.filter((f) => f.is_skipped).length,
  },
])

const visibles = computed(() => {
  if (vista.value === 'errores') return props.filas.filter((f) => conProblema(f))
  if (vista.value === 'duplicadas') return props.filas.filter((f) => f.is_duplicate)
  if (vista.value === 'excluidas') return props.filas.filter((f) => f.is_skipped)
  return props.filas
})

/**
 * Sin fecha o sin importe no hay movimiento posible, aunque el servidor haya
 * dejado de marcarla como errónea —pasa al recuperar una fila excluida—. La
 * pantalla no puede decir «Correcta» de una fila que no se va a importar.
 */
function incompleta(fila: FilaImportacion): boolean {
  return !fila.date || aNumero(fila.amount) === 0
}

function conProblema(fila: FilaImportacion): boolean {
  return fila.status === 'error' || incompleta(fila)
}

/** Una fila con problema se edita siempre; las demás, solo si se abren. */
function editable(fila: FilaImportacion): boolean {
  return conProblema(fila) || abiertas.value.includes(fila.id)
}

/** Sin efectos: se llama desde la plantilla en cada repintado. */
function borradorDe(fila: FilaImportacion): Borrador {
  return (
    borradores.value[fila.id] ?? {
      date: fila.date ?? null,
      importe: fila.amount ?? '',
      description: fila.description ?? '',
    }
  )
}

function editar(fila: FilaImportacion, cambios: Partial<Borrador>): void {
  borradores.value = {
    ...borradores.value,
    [fila.id]: { ...borradorDe(fila), ...cambios },
  }
}

function abrir(fila: FilaImportacion): void {
  if (!abiertas.value.includes(fila.id)) abiertas.value = [...abiertas.value, fila.id]
}

/** Importe escrito a mano: se acepta `-30,15`, `1.234,56` y `1234.56`. */
function importeDelBorrador(fila: FilaImportacion): number | null {
  const texto = borradorDe(fila).importe.trim()
  if (!texto) return null
  return parsearImporte(texto)
}

function errorDeImporte(fila: FilaImportacion): string | undefined {
  const texto = borradorDe(fila).importe.trim()
  if (!texto) return 'Escribe el importe del movimiento.'
  const valor = parsearImporte(texto)
  if (valor === null) return 'No se entiende este importe.'
  if (valor === 0) return 'El importe no puede ser cero.'
  return undefined
}

function cambiada(fila: FilaImportacion): boolean {
  const borrador = borradores.value[fila.id]
  if (!borrador) return false
  const importe = importeDelBorrador(fila)
  return (
    borrador.date !== (fila.date ?? null) ||
    borrador.description !== (fila.description ?? '') ||
    (importe !== null && importe.toFixed(2) !== (fila.amount ?? ''))
  )
}

function puedeGuardar(fila: FilaImportacion): boolean {
  const borrador = borradorDe(fila)
  return (
    cambiada(fila) &&
    !!borrador.date &&
    borrador.description.trim() !== '' &&
    errorDeImporte(fila) === undefined
  )
}

function guardar(fila: FilaImportacion): void {
  const borrador = borradorDe(fila)
  const importe = importeDelBorrador(fila)
  emit('corregir', fila.id, {
    date: borrador.date,
    amount: importe === null ? null : importe.toFixed(2),
    description: borrador.description.trim(),
  })
  abiertas.value = abiertas.value.filter((id) => id !== fila.id)
  const resto = { ...borradores.value }
  delete resto[fila.id]
  borradores.value = resto
}

function descartar(fila: FilaImportacion): void {
  abiertas.value = abiertas.value.filter((id) => id !== fila.id)
  const resto = { ...borradores.value }
  delete resto[fila.id]
  borradores.value = resto
}

/** Estado con el que se pinta la fila: la exclusión pesa más que el resto. */
function tono(fila: FilaImportacion): 'excluida' | 'error' | 'duplicada' | 'valida' {
  if (fila.is_skipped) return 'excluida'
  if (conProblema(fila)) return 'error'
  if (fila.is_duplicate) return 'duplicada'
  return 'valida'
}

function etiquetaEstado(fila: FilaImportacion): string {
  if (fila.is_skipped) return 'Excluida'
  if (conProblema(fila)) return ETIQUETA_ESTADO_FILA.error
  return ETIQUETA_ESTADO_FILA[fila.status]
}
</script>

<template>
  <section class="tarjeta" aria-labelledby="titulo-filas">
    <div class="cabecera">
      <h2 id="titulo-filas" class="titulo">Revisa los movimientos</h2>
      <p class="ayuda">
        Corrige lo que haga falta o excluye las filas que no quieras importar. El signo menos
        marca un gasto.
      </p>
    </div>

    <PestanyasBase
      :model-value="vista"
      :pestanyas="pestanyas"
      etiqueta="Filtrar las filas del fichero"
      @update:model-value="cambiarVista"
    >
      <div v-if="cargando" class="caja">
        <EsqueletoCarga variante="texto" :lineas="8" anuncio="Cargando las filas del fichero" />
      </div>

      <div v-else-if="visibles.length === 0" class="caja">
        <EstadoVacio
          :tipo="vista === 'todas' ? 'primer-uso' : 'sin-filtros'"
          :titulo="
            vista === 'todas'
              ? 'Este fichero no tiene ningún movimiento'
              : 'Ninguna fila en este grupo'
          "
          :descripcion="
            vista === 'todas'
              ? 'No se ha podido interpretar ninguna fila del extracto.'
              : 'Cambia de pestaña para ver el resto de las filas.'
          "
          :nivel="3"
        />
      </div>

      <template v-else>
        <p v-if="truncadas" class="banda banda--aviso">
          <TriangleAlert :size="16" aria-hidden="true" />
          El fichero tiene más movimientos de los que admite una importación. Se muestran los
          primeros {{ filas.length }}.
        </p>

        <div
          class="envoltorio-tabla"
          tabindex="0"
          role="group"
          aria-label="Filas del extracto, desplazable en horizontal"
        >
          <table class="tabla">
            <caption class="oculto">
              Filas del extracto con su estado, el motivo de las que fallan y las duplicadas
              marcadas
            </caption>
            <thead>
              <tr>
                <th scope="col" class="col-num">Línea</th>
                <th scope="col" class="col-estado">Estado</th>
                <th scope="col">Fecha</th>
                <th scope="col">Concepto</th>
                <th scope="col" class="col-importe">Importe</th>
                <th scope="col" class="col-duplicada">Importar duplicada</th>
                <th scope="col" class="col-acciones"><span class="oculto">Acciones</span></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="fila in visibles" :key="fila.id">
                <tr :class="`fila--${tono(fila)}`" :aria-busy="enCurso(fila.id) || undefined">
                  <td class="col-num num">{{ fila.row_number }}</td>
                  <td class="col-estado">
                    <span class="estado" :class="`estado--${tono(fila)}`">
                      <X v-if="fila.is_skipped" :size="16" aria-hidden="true" />
                      <TriangleAlert v-else-if="conProblema(fila)" :size="16" aria-hidden="true" />
                      <Copy v-else-if="fila.is_duplicate" :size="16" aria-hidden="true" />
                      <Check v-else :size="16" aria-hidden="true" />
                      {{ etiquetaEstado(fila) }}
                    </span>
                  </td>

                  <td class="col-fecha">
                    <CampoFecha
                      v-if="editable(fila)"
                      :model-value="borradorDe(fila).date"
                      :etiqueta="`Fecha de la línea ${fila.row_number}`"
                      @update:model-value="editar(fila, { date: $event })"
                    />
                    <span v-else>{{ fechaCorta(fila.date) }}</span>
                  </td>

                  <td>
                    <CampoTexto
                      v-if="editable(fila)"
                      :model-value="borradorDe(fila).description"
                      etiqueta="Concepto"
                      etiqueta-oculta
                      :max-longitud="200"
                      @update:model-value="editar(fila, { description: $event })"
                    />
                    <span v-else class="concepto">{{ fila.description || '—' }}</span>
                  </td>

                  <td class="col-importe">
                    <CampoTexto
                      v-if="editable(fila)"
                      :model-value="borradorDe(fila).importe"
                      etiqueta="Importe"
                      etiqueta-oculta
                      :sufijo="simboloDe()"
                      :error="cambiada(fila) ? errorDeImporte(fila) : undefined"
                      @update:model-value="editar(fila, { importe: $event })"
                    />
                    <span v-else class="num" :class="{ gasto: (fila.amount ?? '').startsWith('-') }">
                      {{ fila.amount ? dinero(fila.amount) : '—' }}
                    </span>
                  </td>

                  <td class="col-duplicada">
                    <InterruptorBase
                      v-if="fila.is_duplicate || eranDuplicadas.includes(fila.id)"
                      :model-value="!fila.is_duplicate"
                      :etiqueta="`Importar la línea ${fila.row_number} aunque esté duplicada`"
                      etiqueta-oculta
                      tamanyo="sm"
                      :deshabilitado="enCurso(fila.id)"
                      @update:model-value="emit('duplicada', fila, !$event)"
                    />
                    <span v-else aria-hidden="true">—</span>
                  </td>

                  <td class="col-acciones">
                    <div class="acciones-fila">
                      <template v-if="editable(fila)">
                        <BotonBase
                          variante="secundaria"
                          tamanyo="sm"
                          :deshabilitado="!puedeGuardar(fila)"
                          :cargando="enCurso(fila.id)"
                          @click="guardar(fila)"
                        >
                          Guardar
                        </BotonBase>
                        <BotonBase
                          v-if="!conProblema(fila)"
                          variante="fantasma"
                          tamanyo="sm"
                          @click="descartar(fila)"
                        >
                          Cancelar
                        </BotonBase>
                      </template>
                      <BotonBase
                        v-else
                        variante="fantasma"
                        tamanyo="sm"
                        @click="abrir(fila)"
                      >
                        Editar
                      </BotonBase>
                      <BotonBase
                        v-if="fila.is_skipped"
                        variante="fantasma"
                        tamanyo="sm"
                        :icono="RotateCcw"
                        :deshabilitado="enCurso(fila.id)"
                        @click="emit('excluir', fila, false)"
                      >
                        Recuperar
                      </BotonBase>
                      <BotonBase
                        v-else
                        variante="peligro-fantasma"
                        tamanyo="sm"
                        :deshabilitado="enCurso(fila.id)"
                        @click="emit('excluir', fila, true)"
                      >
                        Excluir
                      </BotonBase>
                    </div>
                  </td>
                </tr>

                <tr v-if="fila.error" class="fila-motivo">
                  <td />
                  <td :colspan="6">
                    <span class="oculto">Motivo:</span>
                    {{ fila.error }}
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </template>
    </PestanyasBase>
  </section>
</template>

<style scoped>
.cabecera {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding: var(--sp-4) var(--sp-4) 0;
}
.titulo {
  margin: 0;
  font-size: var(--t-h2);
  font-weight: 600;
}
.ayuda {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.caja {
  padding: var(--sp-5);
}
.banda {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin: var(--sp-3) var(--sp-4) 0;
  padding: var(--sp-3);
  border-radius: var(--r-md);
  font-size: var(--t-sm);
}
.banda--aviso {
  background-color: var(--c-warning-wash);
  color: var(--c-warning);
}
.envoltorio-tabla {
  overflow-x: auto;
  padding: var(--sp-3) var(--sp-4) var(--sp-4);
}
.tabla {
  width: 100%;
  min-width: 900px;
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
  padding: var(--sp-1) var(--sp-2);
  border-bottom: 1px solid var(--c-border-soft);
  vertical-align: middle;
}
.col-num {
  width: 64px;
  text-align: right;
}
.col-estado {
  width: 132px;
}
.col-fecha {
  width: 176px;
}
/*
 * `CampoFecha` no tiene «etiqueta oculta»: dentro de la tabla la cabecera ya
 * dice qué es la columna, así que su etiqueta y su pista se sacan de la vista
 * pero se dejan en el árbol de accesibilidad, que es lo que las hace útiles.
 */
.col-fecha :deep(.campo > label),
.col-fecha :deep(.campo > .mensaje:not(.malo-texto)) {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
.col-importe {
  width: 148px;
  text-align: right;
}
.col-duplicada {
  width: 96px;
  text-align: center;
}
.col-acciones {
  width: 260px;
}
.estado {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  white-space: nowrap;
}
.estado--valida {
  color: var(--c-positive);
}
.estado--error {
  color: var(--c-warning);
  font-weight: 600;
}
.estado--duplicada {
  color: var(--c-info);
}
.estado--excluida {
  color: var(--c-text-3);
}
.fila--error > td {
  background-color: var(--c-warning-wash);
}
.fila--duplicada > td {
  background-color: var(--c-info-wash);
}
.fila--excluida > td {
  opacity: 0.55;
}
.concepto {
  display: inline-block;
  max-width: 42ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.gasto {
  color: var(--c-negative);
}
.acciones-fila {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-1);
}
.fila-motivo td {
  padding-top: 0;
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
