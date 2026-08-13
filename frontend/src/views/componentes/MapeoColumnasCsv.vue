<script setup lang="ts">
/**
 * Mapeo manual de las columnas del CSV: el caso que de verdad importa.
 *
 * La detección automática falla en cuanto un banco titula la columna «F. VALOR»
 * o mete cuatro líneas de metadatos antes de la tabla. Cuando eso pasa el lote
 * queda en `needs_mapping` y esta pantalla es la única salida: un selector por
 * campo, con la cabecera y unas filas reales delante para poder decidir.
 *
 * Tres campos son obligatorios porque sin ellos el servidor no puede interpretar
 * una fila: fecha, concepto e importe —este último, en una columna o en dos, debe
 * y haber—. Los demás son opcionales.
 *
 * Las columnas se envían **por nombre**, no por posición: es lo que espera
 * `PUT /imports/{id}/mapping`.
 */
import { computed, ref, watch } from 'vue'
import { CircleAlert, TriangleAlert, Upload } from 'lucide-vue-next'

import { nombreDelimitador, type MapeoImportacion } from '@/api/importaciones'
import BotonBase from '@/components/ui/BotonBase.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import {
  columnaAsignable,
  nombreDeColumna,
  valorDeColumna,
  type CampoCsv,
  type MapeoLocal,
} from '@/stores/csvLocal'

/** Valor del selector cuando el campo no se asigna a ninguna columna. */
const SIN_ASIGNAR = -1

const props = withDefaults(
  defineProps<{
    cabecera: string[]
    muestra: string[][]
    delimitador: string
    codificacion: string
    /** Línea del fichero en la que está la cabecera, 1-indexada. */
    lineaCabecera: number
    totalFilas: number
    sugerencia: MapeoLocal
    /** Lo que el servidor no ha sabido reconocer: fecha, concepto, importe. */
    camposQueFaltan?: string[]
    /** Explicación del servidor de por qué hace falta el mapeo. */
    mensaje?: string | null
    guardando?: boolean
  }>(),
  { camposQueFaltan: () => [], mensaje: null },
)

const emit = defineEmits<{
  guardar: [mapeo: MapeoImportacion]
  cancelar: []
  /** El fichero se ha vuelto a elegir para poder leer su cabecera. */
  reenganchar: [fichero: File]
}>()

type ModoImporte = 'unica' | 'debe-haber'

const CAMPOS_OPCIONALES: Array<{ campo: CampoCsv; etiqueta: string; ayuda: string }> = [
  { campo: 'saldo', etiqueta: 'Saldo', ayuda: 'El saldo posterior al movimiento.' },
  { campo: 'divisa', etiqueta: 'Divisa', ayuda: 'Solo si el extracto trae varias monedas.' },
  { campo: 'categoria', etiqueta: 'Categoría del banco', ayuda: 'Se usa como sugerencia.' },
]

const entrada = ref<HTMLInputElement | null>(null)
const intentado = ref(false)
const modo = ref<ModoImporte>('unica')
const seleccion = ref<Record<CampoCsv, number>>({
  fecha: SIN_ASIGNAR,
  concepto: SIN_ASIGNAR,
  importe: SIN_ASIGNAR,
  cargo: SIN_ASIGNAR,
  abono: SIN_ASIGNAR,
  saldo: SIN_ASIGNAR,
  divisa: SIN_ASIGNAR,
  categoria: SIN_ASIGNAR,
})

const numeroDeColumnas = computed(() =>
  Math.max(props.cabecera.length, ...props.muestra.map((fila) => fila.length), 0),
)

/**
 * Columnas con título, que son las únicas asignables: el mapeo viaja por nombre.
 *
 * Si el fichero no tiene ninguna fila que sirva de cabecera —solo metadatos del
 * banco antes de la tabla— no hay nada que nombrar, y decirlo es más honesto que
 * ofrecer selectores que el servidor va a rechazar.
 */
const asignables = computed(() => {
  const lista: number[] = []
  for (let indice = 0; indice < numeroDeColumnas.value; indice += 1) {
    if (columnaAsignable(props.cabecera, indice)) lista.push(indice)
  }
  return lista
})

/**
 * Con menos de tres columnas con título no hay mapeo posible: fecha, concepto e
 * importe son obligatorios y necesitan columnas distintas.
 */
const hayColumnas = computed(() => asignables.value.length >= 3)

const sinTitulo = computed(() => numeroDeColumnas.value - asignables.value.length)

/** Un ejemplo real de la columna ayuda más que su título. */
function ejemplo(indice: number): string {
  const celda = props.muestra.map((fila) => (fila[indice] ?? '').trim()).find((valor) => valor)
  if (!celda) return ''
  return celda.length > 24 ? `${celda.slice(0, 24)}…` : celda
}

const opciones = computed(() => {
  const lista = [{ valor: SIN_ASIGNAR, etiqueta: 'Sin asignar' }]
  for (const indice of asignables.value) {
    const muestraCelda = ejemplo(indice)
    lista.push({
      valor: indice,
      etiqueta: muestraCelda
        ? `${nombreDeColumna(props.cabecera, indice)} · ${muestraCelda}`
        : nombreDeColumna(props.cabecera, indice),
    })
  }
  return lista
})

const OPCIONES_MODO = [
  { valor: 'unica', etiqueta: 'Una sola columna con el signo' },
  { valor: 'debe-haber', etiqueta: 'Debe y haber en columnas separadas' },
]

const errores = computed(() => {
  const mapa: Partial<Record<CampoCsv, string>> = {}
  if (seleccion.value.fecha === SIN_ASIGNAR) {
    mapa.fecha = 'Indica qué columna tiene la fecha del movimiento.'
  }
  if (seleccion.value.concepto === SIN_ASIGNAR) {
    mapa.concepto = 'Indica qué columna tiene el concepto.'
  }
  if (modo.value === 'unica' && seleccion.value.importe === SIN_ASIGNAR) {
    mapa.importe = 'Indica qué columna tiene el importe.'
  }
  if (
    modo.value === 'debe-haber' &&
    seleccion.value.cargo === SIN_ASIGNAR &&
    seleccion.value.abono === SIN_ASIGNAR
  ) {
    mapa.cargo = 'Indica al menos una de las dos columnas.'
  }
  return mapa
})

const valido = computed(() => Object.keys(errores.value).length === 0)

function errorDe(campo: CampoCsv): string | undefined {
  return intentado.value ? errores.value[campo] : undefined
}

/** Campo asignado a una columna, para rotularla sobre los datos de muestra. */
const ETIQUETA_CAMPO: Record<CampoCsv, string> = {
  fecha: 'Fecha',
  concepto: 'Concepto',
  importe: 'Importe',
  cargo: 'Debe',
  abono: 'Haber',
  saldo: 'Saldo',
  divisa: 'Divisa',
  categoria: 'Categoría',
}

const camposActivos = computed<CampoCsv[]>(() => [
  'fecha',
  'concepto',
  ...(modo.value === 'unica' ? (['importe'] as CampoCsv[]) : (['cargo', 'abono'] as CampoCsv[])),
  'saldo',
  'divisa',
  'categoria',
])

function campoDeColumna(indice: number): string | null {
  const campo = camposActivos.value.find((c) => seleccion.value[c] === indice)
  return campo ? ETIQUETA_CAMPO[campo] : null
}

/** Una columna asignada a dos campos casi siempre es un despiste. */
const columnasRepetidas = computed(() => {
  const vistas = new Map<number, number>()
  for (const campo of camposActivos.value) {
    const indice = seleccion.value[campo]
    if (indice === SIN_ASIGNAR) continue
    vistas.set(indice, (vistas.get(indice) ?? 0) + 1)
  }
  return [...vistas.entries()]
    .filter(([, veces]) => veces > 1)
    .map(([indice]) => nombreDeColumna(props.cabecera, indice))
})

/** Arranca con lo que el fichero deje adivinar: casi nunca es todo. */
watch(
  () => props.sugerencia,
  (sugerencia) => {
    for (const campo of Object.keys(seleccion.value) as CampoCsv[]) {
      seleccion.value[campo] = sugerencia[campo] ?? SIN_ASIGNAR
    }
    const soloDebeHaber =
      sugerencia.importe === undefined &&
      (sugerencia.cargo !== undefined || sugerencia.abono !== undefined)
    modo.value = soloDebeHaber ? 'debe-haber' : 'unica'
  },
  { immediate: true, deep: true },
)

function elegir(campo: CampoCsv, valor: string | number | null): void {
  seleccion.value[campo] = valor === null ? SIN_ASIGNAR : Number(valor)
}

function nombreColumnaDe(campo: CampoCsv): string | null {
  const indice = seleccion.value[campo]
  return indice === SIN_ASIGNAR ? null : valorDeColumna(props.cabecera, indice)
}

function guardar(): void {
  intentado.value = true
  if (!valido.value) return
  emit('guardar', {
    date_column: nombreColumnaDe('fecha') ?? '',
    description_column: nombreColumnaDe('concepto'),
    amount_column: modo.value === 'unica' ? nombreColumnaDe('importe') : null,
    debit_column: modo.value === 'debe-haber' ? nombreColumnaDe('cargo') : null,
    credit_column: modo.value === 'debe-haber' ? nombreColumnaDe('abono') : null,
    balance_column: nombreColumnaDe('saldo'),
    currency_column: nombreColumnaDe('divisa'),
    category_column: nombreColumnaDe('categoria'),
    delimiter: props.delimitador || ';',
    encoding: props.codificacion.slice(0, 20) || 'utf-8',
    decimal_separator: ',',
    thousands_separator: '.',
    date_format: '%d/%m/%Y',
    invert_sign: false,
    skip_rows: 0,
  })
}

function alElegirFichero(evento: Event): void {
  const elegido = (evento.target as HTMLInputElement).files?.[0]
  if (elegido) emit('reenganchar', elegido)
}
</script>

<template>
  <section class="tarjeta bloque" aria-labelledby="titulo-mapeo">
    <div class="cabecera">
      <h2 id="titulo-mapeo" class="titulo">Indica qué columna es cada cosa</h2>
      <p class="explicacion">
        <TriangleAlert :size="16" aria-hidden="true" />
        <span>
          No se han reconocido las columnas del fichero{{
            camposQueFaltan.length > 0 ? ` de ${camposQueFaltan.join(', ')}` : ''
          }}. Asígnalas a mano y el fichero se volverá a analizar.
        </span>
      </p>
      <p v-if="mensaje" class="detalle-servidor">{{ mensaje }}</p>
    </div>

    <!-- Sin cabecera con títulos no hay columnas que ofrecer. -->
    <div v-if="!hayColumnas" class="caja">
      <EstadoVacio
        :tipo="numeroDeColumnas === 0 ? 'sin-filtros' : 'error'"
        :titulo="
          numeroDeColumnas === 0
            ? 'Vuelve a elegir el fichero para ver sus columnas'
            : 'El fichero no tiene una fila de cabecera'
        "
        :descripcion="
          numeroDeColumnas === 0
            ? 'La importación sigue guardada, pero los títulos de las columnas solo están en el fichero de tu equipo. No se subirá otra vez.'
            : 'Las columnas se asignan por su título y aquí no hay títulos suficientes: hacen falta al menos los de la fecha, el concepto y el importe. Añade una primera línea con los títulos de las columnas y vuelve a subir el fichero.'
        "
        :nivel="3"
      >
        <template #accion>
          <BotonBase variante="contorno" :icono="Upload" @click="entrada?.click()">
            Elegir el fichero
          </BotonBase>
        </template>
      </EstadoVacio>
      <input
        ref="entrada"
        class="oculto"
        type="file"
        accept=".csv,.txt,text/csv"
        aria-label="Vuelve a elegir el fichero del extracto"
        @change="alElegirFichero"
      />
    </div>

    <template v-else>
      <p class="deteccion">
        Delimitador detectado: <strong>{{ nombreDelimitador(delimitador) }}</strong> · Codificación:
        <strong>{{ codificacion }}</strong> · Cabecera en la línea
        <strong class="num">{{ lineaCabecera }}</strong> ·
        <strong class="num">{{ totalFilas }}</strong>
        {{ totalFilas === 1 ? 'movimiento' : 'movimientos' }}
      </p>

      <div class="rejilla">
        <SelectorBase
          :model-value="seleccion.fecha"
          etiqueta="Fecha"
          :opciones="opciones"
          :error="errorDe('fecha')"
          ayuda="Obligatoria."
          requerido
          @update:model-value="elegir('fecha', $event)"
        />
        <SelectorBase
          :model-value="seleccion.concepto"
          etiqueta="Concepto"
          :opciones="opciones"
          :error="errorDe('concepto')"
          ayuda="Obligatorio."
          requerido
          @update:model-value="elegir('concepto', $event)"
        />
        <SelectorBase
          :model-value="modo"
          etiqueta="Cómo viene el importe"
          :opciones="OPCIONES_MODO"
          @update:model-value="modo = $event === 'debe-haber' ? 'debe-haber' : 'unica'"
        />
        <SelectorBase
          v-if="modo === 'unica'"
          :model-value="seleccion.importe"
          etiqueta="Importe"
          :opciones="opciones"
          :error="errorDe('importe')"
          ayuda="Obligatorio. El signo menos marca el gasto."
          requerido
          @update:model-value="elegir('importe', $event)"
        />
        <template v-else>
          <SelectorBase
            :model-value="seleccion.cargo"
            etiqueta="Debe (cargos)"
            :opciones="opciones"
            :error="errorDe('cargo')"
            ayuda="Se importa como gasto."
            @update:model-value="elegir('cargo', $event)"
          />
          <SelectorBase
            :model-value="seleccion.abono"
            etiqueta="Haber (abonos)"
            :opciones="opciones"
            ayuda="Se importa como ingreso."
            @update:model-value="elegir('abono', $event)"
          />
        </template>
        <SelectorBase
          v-for="opcional in CAMPOS_OPCIONALES"
          :key="opcional.campo"
          :model-value="seleccion[opcional.campo]"
          :etiqueta="opcional.etiqueta"
          :opciones="opciones"
          :ayuda="opcional.ayuda"
          @update:model-value="elegir(opcional.campo, $event)"
        />
      </div>

      <p v-if="sinTitulo > 0" class="repetidas">
        <CircleAlert :size="16" aria-hidden="true" />
        {{ sinTitulo === 1 ? 'Una columna no tiene' : `${sinTitulo} columnas no tienen` }} título en
        la cabecera, así que no se {{ sinTitulo === 1 ? 'puede' : 'pueden' }} asignar.
      </p>
      <p v-if="columnasRepetidas.length > 0" class="repetidas" role="status">
        <CircleAlert :size="16" aria-hidden="true" />
        Has asignado la misma columna a más de un campo: {{ columnasRepetidas.join(', ') }}.
      </p>

      <h3 class="titulo-muestra">Cómo queda el fichero</h3>
      <div class="envoltorio-tabla" tabindex="0" role="group" aria-label="Muestra del fichero, desplazable">
        <table class="tabla">
          <caption class="oculto">
            Primeras filas del fichero con el campo asignado a cada columna
          </caption>
          <thead>
            <tr>
              <th v-for="indice in numeroDeColumnas" :key="`c-${indice}`" scope="col">
                <span class="nombre-col">{{ nombreDeColumna(cabecera, indice - 1) }}</span>
                <span v-if="campoDeColumna(indice - 1)" class="chip-campo">
                  {{ campoDeColumna(indice - 1) }}
                </span>
                <span v-else class="chip-campo chip-campo--sin">
                  {{ columnaAsignable(cabecera, indice - 1) ? 'Sin usar' : 'Sin título' }}
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(fila, i) in muestra" :key="`f-${i}`">
              <td v-for="indice in numeroDeColumnas" :key="`f-${i}-${indice}`">
                {{ fila[indice - 1] ?? '' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer class="acciones">
        <BotonBase variante="contorno" :deshabilitado="guardando" @click="emit('cancelar')">
          Cancelar
        </BotonBase>
        <BotonBase variante="primaria" :cargando="guardando" @click="guardar">
          Analizar con estas columnas
        </BotonBase>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.bloque {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-5);
}
.cabecera {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.titulo {
  margin: 0;
  font-size: var(--t-h2);
  font-weight: 600;
}
.explicacion {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  margin: 0;
  padding: var(--sp-3);
  border-radius: var(--r-md);
  background-color: var(--c-warning-wash);
  color: var(--c-warning);
  font-size: var(--t-sm);
}
.detalle-servidor,
.deteccion {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.caja {
  padding: var(--sp-4) 0;
}
.rejilla {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sp-3);
}
.repetidas {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-info);
}
.titulo-muestra {
  margin: 0;
  font-size: var(--t-h3);
  font-weight: 600;
}
.envoltorio-tabla {
  overflow-x: auto;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
}
.tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-caption);
}
.tabla th {
  padding: var(--sp-2);
  text-align: left;
  border-bottom: 1px solid var(--c-border);
  vertical-align: top;
  white-space: nowrap;
}
.tabla td {
  padding: var(--sp-2);
  border-bottom: 1px solid var(--c-border-soft);
  white-space: nowrap;
}
.nombre-col {
  display: block;
  font-weight: 600;
  color: var(--c-text-1);
}
.chip-campo {
  display: inline-block;
  margin-top: 2px;
  padding: 0 var(--sp-2);
  border-radius: var(--r-full);
  background-color: var(--c-accent-wash);
  color: var(--c-accent);
  font-size: var(--t-micro);
  font-weight: 500;
}
.chip-campo--sin {
  background-color: var(--c-surface-2);
  color: var(--c-text-3);
  font-weight: 400;
}
.acciones {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--sp-2);
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
