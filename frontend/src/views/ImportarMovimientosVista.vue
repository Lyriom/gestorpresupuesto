<script setup lang="ts">
/**
 * Importar movimientos desde un extracto bancario (F-25, §3.17).
 *
 * Cinco pasos y un principio: **nada se crea hasta el último** (RN-67). El
 * fichero se sube, el servidor lo analiza en segundo plano y el resultado manda
 * en lo que se ve:
 *
 * 1. Fichero: cuenta de destino y extracto, arrastrando o eligiéndolo.
 * 2. Análisis: sondeo con el ritmo que marca el servidor.
 * 3. Columnas: solo si el análisis no ha reconocido la cabecera. Es el caso
 *    interesante y tiene su propia pantalla, `MapeoColumnasCsv`.
 * 4. Revisión: todas las filas, con su estado, el motivo de las que fallan y las
 *    duplicadas marcadas y desmarcables. El total a importar se recalcula al vuelo.
 * 5. Resumen: lo que se ha creado y el botón de deshacer el lote (RN-69).
 *
 * La cabecera y la muestra del fichero salen de la lectura local (`csvLocal`):
 * ningún endpoint las publica. Todo lo demás viene del servidor.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Check,
  CircleAlert,
  FileSpreadsheet,
  FileUp,
  LoaderCircle,
  RotateCcw,
  Trash2,
  TriangleAlert,
  X,
} from 'lucide-vue-next'

import {
  ETIQUETA_FORMATO,
  nombreDelimitador,
  type Importacion,
  type MapeoImportacion,
} from '@/api/importaciones'
import BotonBase from '@/components/ui/BotonBase.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import IndicadorProgreso from '@/components/ui/IndicadorProgreso.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import { useAvisos } from '@/composables/useAvisos'
import { dinero, fechaCorta } from '@/lib/formato'
import { useCategorias } from '@/stores/categorias'
import { useCuentas } from '@/stores/cuentas'
import { useImportaciones } from '@/stores/importaciones'
import { useSesion } from '@/stores/sesion'
import HistorialImportaciones from './componentes/HistorialImportaciones.vue'
import MapeoColumnasCsv from './componentes/MapeoColumnasCsv.vue'
import RevisionFilasImportacion from './componentes/RevisionFilasImportacion.vue'

/** Cuántas filas del fichero se enseñan en la previsualización. */
const FILAS_A_MOSTRAR = 5

const route = useRoute()
const router = useRouter()
const importaciones = useImportaciones()
const cuentas = useCuentas()
const categorias = useCategorias()
const sesion = useSesion()
const avisos = useAvisos()

const entrada = ref<HTMLInputElement | null>(null)
const arrastrando = ref(false)
const loteADeshacer = ref<Importacion | null>(null)

const lote = computed(() => importaciones.lote)
const paso = computed(() => importaciones.paso)

/* ------------------------------------------------------------------ *
 * Guía de pasos
 * ------------------------------------------------------------------ */

const PASOS = [
  { clave: 'fichero', etiqueta: 'Fichero' },
  { clave: 'analisis', etiqueta: 'Análisis' },
  { clave: 'columnas', etiqueta: 'Columnas' },
  { clave: 'revision', etiqueta: 'Revisión' },
  { clave: 'resumen', etiqueta: 'Resumen' },
]

const pasoActual = computed(() => {
  switch (paso.value) {
    case 'fichero':
      return 0
    case 'analizando':
    case 'previsualizacion':
    case 'fallo':
      return 1
    case 'mapeo':
      return 2
    case 'revision':
      return 3
    default:
      return 4
  }
})

function estadoPaso(indice: number): 'hecho' | 'actual' | 'pendiente' {
  if (indice < pasoActual.value) return 'hecho'
  return indice === pasoActual.value ? 'actual' : 'pendiente'
}

/* ------------------------------------------------------------------ *
 * Paso 1: fichero y cuenta
 * ------------------------------------------------------------------ */

const cuentaId = computed({
  get: () => importaciones.cuentaId,
  set: (valor: string | number | null) => {
    importaciones.cuentaId = valor === null ? null : String(valor)
  },
})

const pesoKb = computed(() => Math.max(1, Math.round((importaciones.fichero?.size ?? 0) / 1024)))

const puedeSubir = computed(
  () => !!importaciones.fichero && !!importaciones.cuentaId && !importaciones.subiendo,
)

async function procesar(elegido: File): Promise<void> {
  await importaciones.elegirFichero(elegido, sesion.maxSubidaMb)
}

function alSoltar(evento: DragEvent): void {
  arrastrando.value = false
  const elegido = evento.dataTransfer?.files?.[0]
  if (elegido) void procesar(elegido)
}

function alElegir(evento: Event): void {
  const elegido = (evento.target as HTMLInputElement).files?.[0]
  if (elegido) void procesar(elegido)
}

async function subir(): Promise<void> {
  const subido = await importaciones.subir()
  if (subido) {
    // La URL lleva el lote: recargar la página no pierde la importación.
    void router.replace({ name: 'importacion', params: { id: subido.id } })
  }
}

/* ------------------------------------------------------------------ *
 * Paso 2: análisis
 * ------------------------------------------------------------------ */

const pasosAnalisis = computed(() => {
  const progreso = importaciones.estadoAnalisis?.progress ?? 0
  const fallo = importaciones.fallida
  return [
    { texto: 'Fichero subido', estado: 'hecho' as const },
    {
      texto: 'Leyendo el fichero',
      estado: progreso >= 100 ? 'hecho' : fallo ? 'fallo' : 'curso',
    },
    {
      texto: 'Interpretando los movimientos',
      estado: progreso >= 100 ? 'hecho' : fallo ? 'fallo' : 'pendiente',
    },
  ]
})

/* ------------------------------------------------------------------ *
 * Previsualización: cabecera y muestra del fichero
 * ------------------------------------------------------------------ */

const analisis = computed(() => importaciones.analisisLocal)

/** Cabecera del fichero. Si no hay lectura local, se rotula por posición. */
const cabecera = computed<string[]>(() => {
  if (analisis.value?.cabecera.length) return analisis.value.cabecera
  const primera = importaciones.filas[0]
  if (!primera) return []
  const claves = Object.keys(primera.raw)
  // En OFX y QIF la clave del crudo ya es el nombre del campo.
  return claves.every((clave) => /^\d+$/.test(clave)) ? [] : claves
})

const muestra = computed<string[][]>(() => {
  if (analisis.value?.muestra.length) return analisis.value.muestra.slice(0, FILAS_A_MOSTRAR)
  return importaciones.filas.slice(0, FILAS_A_MOSTRAR).map((fila) => {
    const claves = Object.keys(fila.raw).sort((a, b) => Number(a) - Number(b))
    return claves.map((clave) => fila.raw[clave])
  })
})

const columnasMuestra = computed(() =>
  Math.max(cabecera.value.length, ...muestra.value.map((fila) => fila.length), 0),
)

function nombreColumna(indice: number): string {
  const texto = (cabecera.value[indice] ?? '').trim()
  return texto || `Columna ${indice + 1}`
}

/** Qué columna ha reconocido el servidor para cada campo. */
const columnasReconocidas = computed(() => {
  const mapeo = lote.value?.mapping
  if (!mapeo) return []
  const pares: Array<[string, string | null | undefined]> = [
    ['Fecha', mapeo.date_column],
    ['Concepto', mapeo.description_column],
    ['Importe', mapeo.amount_column],
    ['Debe', mapeo.debit_column],
    ['Haber', mapeo.credit_column],
    ['Saldo', mapeo.balance_column],
    ['Divisa', mapeo.currency_column],
  ]
  return pares
    .filter(([, columna]) => !!columna)
    .map(([campo, columna]) => ({ campo, columna: columna as string }))
})

const lineaCabecera = computed(() => (analisis.value?.filaCabecera ?? 0) + 1)

/* ------------------------------------------------------------------ *
 * Paso 3: columnas a mano
 * ------------------------------------------------------------------ */

async function guardarMapeo(mapeo: MapeoImportacion): Promise<void> {
  const ok = await importaciones.guardarMapeo(mapeo)
  if (ok) avisos.info('Se está volviendo a analizar el fichero con esas columnas.')
}

function cancelarMapeo(): void {
  if (importaciones.necesitaMapeo) void descartarActual()
  else importaciones.paso = 'previsualizacion'
}

/* ------------------------------------------------------------------ *
 * Paso 4: revisión
 * ------------------------------------------------------------------ */

const omitirDuplicados = computed({
  get: () => importaciones.omitirDuplicados,
  set: (valor: boolean) => {
    importaciones.omitirDuplicados = valor
  },
})

const tematicaPorDefecto = computed({
  get: () => importaciones.tematicaPorDefecto,
  set: (valor: string | number | null) => {
    importaciones.tematicaPorDefecto = valor === null ? null : String(valor)
  },
})

const cuantosImportables = computed(() => importaciones.importables.length)

async function confirmar(): Promise<void> {
  const resultado = await importaciones.confirmar()
  if (!resultado) return
  const n = resultado.transactions_created
  avisos.exito(
    n === 1 ? 'Se ha importado 1 movimiento.' : `Se han importado ${n} movimientos.`,
  )
}

/* ------------------------------------------------------------------ *
 * Deshacer, descartar y volver a empezar
 * ------------------------------------------------------------------ */

function pedirDeshacer(candidato: Importacion): void {
  loteADeshacer.value = candidato
}

async function deshacer(): Promise<void> {
  const candidato = loteADeshacer.value
  if (!candidato) return
  loteADeshacer.value = null
  const resultado = await importaciones.revertir(candidato.id)
  if (!resultado) return
  const n = resultado.transactions_deleted
  avisos.exito(
    n === 1 ? 'Se ha borrado 1 movimiento importado.' : `Se han borrado ${n} movimientos.`,
  )
  for (const aviso of resultado.warnings) avisos.aviso(aviso)
}

async function descartarActual(): Promise<void> {
  const actual = lote.value
  if (!actual) {
    importaciones.reiniciar()
    return
  }
  const ok = await importaciones.descartar(actual.id)
  if (ok) {
    avisos.info('Importación descartada.')
    volverAlInicio()
  }
}

function volverAlInicio(): void {
  importaciones.reiniciar()
  if (route.name !== 'importaciones') void router.replace({ name: 'importaciones' })
}

async function retomar(candidato: Importacion): Promise<void> {
  await router.push({ name: 'importacion', params: { id: candidato.id } })
}

/* ------------------------------------------------------------------ *
 * Ciclo de vida
 * ------------------------------------------------------------------ */

const idDeLaRuta = computed(() => {
  const bruto = route.params.id
  const valor = Array.isArray(bruto) ? bruto[0] : bruto
  return valor ? String(valor) : null
})

async function sincronizarConLaRuta(): Promise<void> {
  const id = idDeLaRuta.value
  if (!id) return
  if (importaciones.lote?.id === id) return
  await importaciones.retomar(id)
}

onMounted(() => {
  void cuentas.cargar()
  void categorias.cargar()
  void importaciones.cargarHistorial()
  if (idDeLaRuta.value) void sincronizarConLaRuta()
  else importaciones.reiniciar()
  // La cuenta más usada suele ser la primera: se propone, no se impone.
  if (!importaciones.cuentaId) importaciones.cuentaId = cuentas.activas[0]?.id ?? null
})

watch(idDeLaRuta, () => void sincronizarConLaRuta())

// Sin cuentas cargadas al montar, la propuesta llega con la respuesta.
watch(
  () => cuentas.activas.length,
  () => {
    if (!importaciones.cuentaId) importaciones.cuentaId = cuentas.activas[0]?.id ?? null
  },
)

onBeforeUnmount(() => importaciones.detenerSondeo())
</script>

<template>
  <div class="vista">
    <nav class="miga" aria-label="Migas de pan">
      <BotonBase variante="enlace" tamanyo="sm" @click="router.push({ name: 'ajustes' })">
        Ajustes
      </BotonBase>
      <span aria-hidden="true">›</span>
      <span>Importar movimientos</span>
    </nav>

    <h1 class="titulo">Importar movimientos</h1>

    <ol class="pasos-guia" aria-label="Pasos de la importación">
      <li
        v-for="(p, i) in PASOS"
        :key="p.clave"
        :class="`guia--${estadoPaso(i)}`"
        :aria-current="estadoPaso(i) === 'actual' ? 'step' : undefined"
      >
        <span class="indice num" aria-hidden="true">
          <Check v-if="estadoPaso(i) === 'hecho'" :size="14" />
          <template v-else>{{ i + 1 }}</template>
        </span>
        <span class="etiqueta-paso">{{ p.etiqueta }}</span>
        <span v-if="estadoPaso(i) === 'hecho'" class="oculto">(completado)</span>
      </li>
    </ol>

    <p v-if="importaciones.error" class="banda banda--error" role="alert">
      <CircleAlert :size="16" aria-hidden="true" />
      {{ importaciones.error }}
    </p>

    <!-- ------------------------------------------------ Paso 1: fichero -->
    <template v-if="paso === 'fichero'">
      <section class="tarjeta caja" aria-labelledby="t-fichero">
        <h2 id="t-fichero" class="titulo-bloque">Elige el extracto y la cuenta</h2>

        <SelectorBase
          v-model="cuentaId"
          etiqueta="Cuenta de destino"
          placeholder="Elige una cuenta"
          :opciones="cuentas.opciones"
          :cargando="cuentas.cargando"
          ayuda="Los movimientos del fichero se crearán en esta cuenta."
          requerido
        />

        <div
          class="zona"
          :class="{ activa: arrastrando, mala: !!importaciones.errorFichero }"
          @dragover.prevent="arrastrando = true"
          @dragleave.prevent="arrastrando = false"
          @drop.prevent="alSoltar"
        >
          <FileUp :size="32" aria-hidden="true" />
          <p class="titular">Arrastra aquí el extracto de tu banco</p>
          <p class="o">
            o
            <BotonBase variante="enlace" @click="entrada?.click()">
              selecciona un fichero
            </BotonBase>
          </p>
          <p class="limites">
            CSV, OFX o QIF · hasta {{ sesion.maxSubidaMb }} MB · el formato se detecta por el
            contenido
          </p>
          <input
            ref="entrada"
            class="oculto"
            type="file"
            accept=".csv,.txt,.ofx,.qfx,.qif,text/csv"
            aria-label="Selecciona el fichero del extracto"
            @change="alElegir"
          />
        </div>

        <p v-if="importaciones.errorFichero" class="banda banda--error" role="alert">
          <CircleAlert :size="16" aria-hidden="true" />
          {{ importaciones.errorFichero }}
        </p>

        <div v-if="importaciones.fichero" class="elegido">
          <FileSpreadsheet :size="20" aria-hidden="true" />
          <span class="nombre">{{ importaciones.fichero.name }}</span>
          <span class="meta num">{{ pesoKb }} KB</span>
          <span v-if="analisis?.esCsv" class="meta">
            {{ nombreDelimitador(analisis.delimitador) }} · {{ analisis.codificacion }} ·
            <span class="num">{{ analisis.totalFilas }}</span>
            {{ analisis.totalFilas === 1 ? 'movimiento' : 'movimientos' }}
          </span>
          <BotonBase
            variante="fantasma"
            tamanyo="sm"
            solo-icono
            :icono="X"
            etiqueta-accesible="Quitar el fichero elegido"
            @click="importaciones.quitarFichero()"
          />
        </div>

        <div class="acciones">
          <BotonBase
            variante="primaria"
            :deshabilitado="!puedeSubir"
            :cargando="importaciones.subiendo"
            @click="subir"
          >
            Analizar el fichero
          </BotonBase>
        </div>
      </section>

      <HistorialImportaciones
        :items="importaciones.historial"
        :cargando="importaciones.cargandoHistorial"
        :error="importaciones.errorHistorial"
        :revirtiendo="importaciones.revirtiendo"
        @retomar="retomar"
        @revertir="pedirDeshacer"
        @descartar="importaciones.descartar($event.id)"
        @reintentar="importaciones.cargarHistorial()"
      />
    </template>

    <!-- ------------------------------------------------ Paso 2: análisis -->
    <section v-else-if="paso === 'analizando'" class="tarjeta analizando">
      <p class="nombre-fichero">
        {{ lote?.filename ?? importaciones.fichero?.name }}
        <template v-if="lote"> · {{ ETIQUETA_FORMATO[lote.format] }}</template>
      </p>

      <IndicadorProgreso
        v-if="importaciones.subiendo"
        etiqueta="Progreso de la subida"
        :valor="importaciones.progresoSubida"
        estado="Subiendo el fichero"
        mostrar-texto
      />
      <IndicadorProgreso
        v-else
        etiqueta="Progreso del análisis"
        :valor="importaciones.estadoAnalisis?.progress ?? 10"
        estado="Analizando el fichero"
        indeterminado
      />

      <ul class="pasos">
        <li v-for="p in pasosAnalisis" :key="p.texto" :class="`paso--${p.estado}`">
          <Check v-if="p.estado === 'hecho'" :size="16" aria-hidden="true" />
          <LoaderCircle
            v-else-if="p.estado === 'curso'"
            :size="16"
            class="girando"
            aria-hidden="true"
          />
          <X v-else-if="p.estado === 'fallo'" :size="16" aria-hidden="true" />
          <span v-else class="circulo" aria-hidden="true" />
          {{ p.texto }}
        </li>
      </ul>

      <p class="nota">Suele tardar unos segundos. No se crea ningún movimiento todavía.</p>
      <BotonBase variante="contorno" @click="volverAlInicio">Cancelar</BotonBase>
    </section>

    <!-- ------------------------------------------------ Previsualización -->
    <section
      v-else-if="paso === 'previsualizacion'"
      class="tarjeta caja"
      aria-labelledby="t-previa"
    >
      <h2 id="t-previa" class="titulo-bloque">Así se ha leído el fichero</h2>

      <dl class="deteccion">
        <div>
          <dt>Formato</dt>
          <dd>{{ lote ? ETIQUETA_FORMATO[lote.format] : '—' }}</dd>
        </div>
        <div>
          <dt>Delimitador</dt>
          <dd>{{ nombreDelimitador(lote?.detected_delimiter) }}</dd>
        </div>
        <div>
          <dt>Codificación</dt>
          <dd>{{ lote?.detected_encoding ?? '—' }}</dd>
        </div>
        <div v-if="analisis?.esCsv">
          <dt>Cabecera</dt>
          <dd class="num">Línea {{ lineaCabecera }}</dd>
        </div>
        <div>
          <dt>Movimientos leídos</dt>
          <dd class="num">{{ lote?.rows_total ?? 0 }}</dd>
        </div>
        <div>
          <dt>Con error</dt>
          <dd class="num">{{ lote?.rows_error ?? 0 }}</dd>
        </div>
        <div>
          <dt>Duplicados</dt>
          <dd class="num">{{ lote?.rows_duplicated ?? 0 }}</dd>
        </div>
        <div v-if="lote?.date_from">
          <dt>Periodo</dt>
          <dd>{{ fechaCorta(lote.date_from) }} – {{ fechaCorta(lote.date_to) }}</dd>
        </div>
      </dl>

      <p v-if="columnasReconocidas.length > 0" class="reconocidas">
        Columnas reconocidas:
        <span v-for="c in columnasReconocidas" :key="c.campo" class="chip">
          {{ c.campo }}: {{ c.columna }}
        </span>
      </p>

      <div v-if="importaciones.cargandoFilas" class="caja-interna">
        <EsqueletoCarga variante="texto" :lineas="5" anuncio="Cargando la muestra del fichero" />
      </div>

      <div
        v-else-if="columnasMuestra > 0"
        class="envoltorio-tabla"
        tabindex="0"
        role="group"
        aria-label="Muestra del fichero, desplazable en horizontal"
      >
        <table class="tabla-muestra">
          <caption class="oculto">
            Cabecera y primeras filas del fichero tal y como se han leído
          </caption>
          <thead>
            <tr>
              <th v-for="i in columnasMuestra" :key="`h-${i}`" scope="col">
                {{ nombreColumna(i - 1) }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(fila, f) in muestra" :key="`m-${f}`">
              <td v-for="i in columnasMuestra" :key="`m-${f}-${i}`">{{ fila[i - 1] ?? '' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-for="(aviso, i) in lote?.warnings ?? []" :key="`a-${i}`" class="banda banda--aviso">
        <TriangleAlert :size="16" aria-hidden="true" />
        {{ aviso }}
      </p>

      <div class="acciones">
        <BotonBase variante="fantasma" :icono="Trash2" @click="descartarActual">
          Descartar
        </BotonBase>
        <BotonBase variante="secundaria" @click="importaciones.irAlMapeo()">
          Cambiar las columnas
        </BotonBase>
        <BotonBase variante="primaria" @click="importaciones.irALaRevision()">
          Revisar los movimientos
        </BotonBase>
      </div>
    </section>

    <!-- ------------------------------------------------ Paso 3: columnas -->
    <MapeoColumnasCsv
      v-else-if="paso === 'mapeo'"
      :cabecera="analisis?.cabecera ?? []"
      :muestra="analisis?.muestra ?? []"
      :delimitador="analisis?.delimitador ?? lote?.detected_delimiter ?? ';'"
      :codificacion="analisis?.codificacion ?? lote?.detected_encoding ?? 'utf-8'"
      :linea-cabecera="lineaCabecera"
      :total-filas="analisis?.totalFilas ?? lote?.rows_total ?? 0"
      :sugerencia="analisis?.sugerencia ?? {}"
      :campos-que-faltan="importaciones.camposQueFaltan"
      :mensaje="lote?.error"
      :guardando="importaciones.guardandoMapeo"
      @guardar="guardarMapeo"
      @cancelar="cancelarMapeo"
      @reenganchar="importaciones.reengancharFichero($event)"
    />

    <!-- ------------------------------------------------ Paso 4: revisión -->
    <template v-else-if="paso === 'revision'">
      <section class="tarjeta caja" aria-labelledby="t-resumen-revision">
        <h2 id="t-resumen-revision" class="titulo-bloque">Qué se va a importar</h2>

        <div class="cifras" role="status">
          <p class="cifra">
            <span class="valor num">{{ cuantosImportables }}</span>
            <span class="rotulo">
              {{ cuantosImportables === 1 ? 'movimiento' : 'movimientos' }} a importar
            </span>
          </p>
          <p class="cifra">
            <span class="valor num">{{ dinero(importaciones.totalImportar) }}</span>
            <span class="rotulo">saldo del lote</span>
          </p>
          <p class="cifra">
            <span class="valor num gasto">{{ dinero(importaciones.totalGastos) }}</span>
            <span class="rotulo">en gastos</span>
          </p>
          <p class="cifra">
            <span class="valor num ingreso">{{ dinero(importaciones.totalIngresos) }}</span>
            <span class="rotulo">en ingresos</span>
          </p>
          <p class="cifra">
            <span class="valor num">{{ importaciones.conError.length }}</span>
            <span class="rotulo">con error, no se importan</span>
          </p>
          <p class="cifra">
            <span class="valor num">{{ importaciones.duplicadas.length }}</span>
            <span class="rotulo">duplicados</span>
          </p>
          <p class="cifra">
            <span class="valor num">{{ importaciones.excluidas.length }}</span>
            <span class="rotulo">excluidos a mano</span>
          </p>
        </div>

        <div class="opciones">
          <InterruptorBase
            v-model="omitirDuplicados"
            etiqueta="Omitir los movimientos duplicados"
            descripcion="Un duplicado es un movimiento con la misma fecha, importe y concepto que otro ya registrado en esta cuenta."
          />
          <SelectorBase
            v-model="tematicaPorDefecto"
            etiqueta="Temática por defecto"
            placeholder="Sin clasificar"
            :opciones="categorias.opciones()"
            :cargando="categorias.cargando"
            ayuda="Se aplica a los movimientos para los que no se reconozca el comercio."
          />
        </div>
      </section>

      <RevisionFilasImportacion
        :filas="importaciones.filas"
        :cargando="importaciones.cargandoFilas"
        :truncadas="importaciones.filasTruncadas"
        :en-curso="importaciones.enCurso"
        @corregir="importaciones.corregirFila"
        @excluir="importaciones.excluirFila"
        @duplicada="importaciones.marcarDuplicada"
      />

      <footer class="acciones">
        <BotonBase
          variante="contorno"
          :deshabilitado="importaciones.confirmando"
          @click="descartarActual"
        >
          Descartar la importación
        </BotonBase>
        <BotonBase variante="secundaria" @click="importaciones.irAlMapeo()">
          Cambiar las columnas
        </BotonBase>
        <BotonBase
          variante="primaria"
          :deshabilitado="!importaciones.puedeConfirmar"
          :cargando="importaciones.confirmando"
          @click="confirmar"
        >
          Importar {{ cuantosImportables }}
          {{ cuantosImportables === 1 ? 'movimiento' : 'movimientos' }}
        </BotonBase>
      </footer>
    </template>

    <!-- ------------------------------------------------ Paso 5: resumen -->
    <section v-else-if="paso === 'resumen'" class="tarjeta caja" aria-labelledby="t-final">
      <div class="remate" :class="{ 'remate--deshecha': !!lote?.rolled_back_at }">
        <Check v-if="!lote?.rolled_back_at" :size="24" aria-hidden="true" />
        <RotateCcw v-else :size="24" aria-hidden="true" />
        <h2 id="t-final" class="titulo-bloque">
          <template v-if="lote?.rolled_back_at">Importación deshecha</template>
          <template v-else-if="importaciones.resultado">
            Se
            {{ importaciones.resultado.transactions_created === 1 ? 'ha' : 'han' }}
            importado {{ importaciones.resultado.transactions_created }}
            {{ importaciones.resultado.transactions_created === 1 ? 'movimiento' : 'movimientos' }}
          </template>
          <template v-else>
            Esta importación ya está confirmada: {{ lote?.transactions_created ?? 0 }}
            {{ (lote?.transactions_created ?? 0) === 1 ? 'movimiento' : 'movimientos' }}
          </template>
        </h2>
      </div>

      <dl v-if="importaciones.resultado" class="deteccion">
        <div>
          <dt>Duplicados omitidos</dt>
          <dd class="num">{{ importaciones.resultado.duplicates_skipped }}</dd>
        </div>
        <div>
          <dt>Filas no importadas</dt>
          <dd class="num">{{ importaciones.resultado.rows_failed }}</dd>
        </div>
        <div>
          <dt>Comercios nuevos</dt>
          <dd class="num">{{ importaciones.resultado.payees_created }}</dd>
        </div>
        <div v-if="lote?.committed_at">
          <dt>Confirmada</dt>
          <dd>{{ fechaCorta(lote.committed_at) }}</dd>
        </div>
      </dl>

      <p
        v-for="(aviso, i) in importaciones.resultado?.warnings ?? []"
        :key="`r-${i}`"
        class="banda banda--aviso"
      >
        <TriangleAlert :size="16" aria-hidden="true" />
        {{ aviso }}
      </p>

      <p v-if="lote?.rolled_back_at" class="nota">
        Los movimientos que creó este lote se han borrado. Los que hubieras editado a mano se
        conservan.
      </p>

      <div class="acciones">
        <BotonBase variante="fantasma" @click="volverAlInicio">Importar otro fichero</BotonBase>
        <BotonBase
          v-if="lote && !lote.rolled_back_at"
          variante="peligro-fantasma"
          :icono="RotateCcw"
          :cargando="importaciones.revirtiendo === lote.id"
          @click="pedirDeshacer(lote)"
        >
          Deshacer la importación
        </BotonBase>
        <BotonBase variante="primaria" @click="router.push({ name: 'movimientos' })">
          Ver los movimientos
        </BotonBase>
      </div>
    </section>

    <!-- ------------------------------------------------ Fallo -->
    <section v-else class="tarjeta caja" aria-label="No se ha podido leer el fichero">
      <EstadoVacio
        tipo="error"
        titulo="No se ha podido leer el fichero"
        :descripcion="
          lote?.error ??
          importaciones.error ??
          'El fichero no tiene el formato de un extracto bancario.'
        "
        :nivel="3"
      >
        <template #accion>
          <BotonBase variante="contorno" @click="volverAlInicio">Elegir otro fichero</BotonBase>
        </template>
        <template v-if="analisis?.esCsv && lote" #ayuda>
          <BotonBase variante="enlace" @click="importaciones.irAlMapeo()">
            Volver a indicar las columnas
          </BotonBase>
        </template>
      </EstadoVacio>
    </section>

    <ModalBase
      :abierto="!!loteADeshacer"
      titulo="Deshacer la importación"
      subtitulo="Se borran solo los movimientos que creó este lote."
      tamanyo="sm"
      @update:abierto="loteADeshacer = null"
      @cerrar="loteADeshacer = null"
    >
      <p class="texto-modal">
        Se borrarán los
        <strong class="num">{{ loteADeshacer?.transactions_created ?? 0 }}</strong>
        movimientos que se crearon al importar
        <strong>{{ loteADeshacer?.filename }}</strong>. Los que hayas editado a mano después se
        conservan.
      </p>
      <template #pie>
        <BotonBase variante="contorno" @click="loteADeshacer = null">Cancelar</BotonBase>
        <BotonBase
          variante="peligro"
          :cargando="!!importaciones.revirtiendo"
          @click="deshacer"
        >
          Deshacer
        </BotonBase>
      </template>
    </ModalBase>
  </div>
</template>

<style scoped>
.vista {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.miga {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.titulo {
  margin: 0;
  font-size: var(--t-h1);
  line-height: var(--t-h1-lh);
  font-weight: 600;
}
.titulo-bloque {
  margin: 0;
  font-size: var(--t-h2);
  font-weight: 600;
}
.caja {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-5);
}
.caja-interna {
  padding: var(--sp-3) 0;
}

/* --- Guía de pasos --- */
.pasos-guia {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2) var(--sp-4);
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--t-sm);
}
.pasos-guia li {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--c-text-3);
}
.indice {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 1px solid var(--c-border-strong);
  border-radius: var(--r-full);
  font-size: var(--t-micro);
}
.guia--hecho {
  color: var(--c-positive);
}
.guia--hecho .indice {
  border-color: var(--c-positive);
}
.guia--actual {
  color: var(--c-text-1);
  font-weight: 600;
}
.guia--actual .indice {
  border-color: var(--c-accent);
  color: var(--c-accent);
}

/* --- Bandas --- */
.banda {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  padding: var(--sp-3);
  border-radius: var(--r-md);
  font-size: var(--t-sm);
}
.banda--aviso {
  background-color: var(--c-warning-wash);
  color: var(--c-warning);
}
.banda--error {
  background-color: var(--c-negative-wash);
  color: var(--c-negative);
}

/* --- Zona de arrastre --- */
.zona {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-8) var(--sp-4);
  border: 2px dashed var(--c-border-strong);
  border-radius: var(--r-lg);
  background-color: var(--c-surface-2);
  color: var(--c-text-2);
  text-align: center;
}
.zona.activa {
  border-color: var(--c-accent);
  background-color: var(--c-accent-wash);
}
.zona.mala {
  border-color: var(--c-negative);
}
.titular {
  margin: 0;
  font-size: var(--t-body);
  font-weight: 600;
  color: var(--c-text-1);
}
.o,
.limites {
  margin: 0;
  font-size: var(--t-sm);
}
.limites {
  font-size: var(--t-caption);
  color: var(--c-text-3);
}
.elegido {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-3);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  font-size: var(--t-sm);
}
.nombre {
  font-weight: 600;
}
.meta {
  color: var(--c-text-2);
}
.elegido > :last-child {
  margin-left: auto;
}

/* --- Análisis --- */
.analizando {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-4);
  padding: var(--sp-8) var(--sp-4);
  text-align: center;
}
.analizando > :nth-child(2) {
  width: min(480px, 100%);
}
.nombre-fichero {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.pasos {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
  text-align: left;
  font-size: var(--t-sm);
}
.pasos li {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--c-text-3);
}
.paso--hecho {
  color: var(--c-positive);
}
.paso--curso {
  color: var(--c-text-1);
  font-weight: 600;
}
.paso--fallo {
  color: var(--c-negative);
  font-weight: 600;
}
.circulo {
  display: inline-block;
  width: 10px;
  height: 10px;
  margin: 3px;
  border: 1px solid var(--c-border-strong);
  border-radius: var(--r-full);
}
.girando {
  animation: girar 900ms linear infinite;
}
@keyframes girar {
  to {
    rotate: 360deg;
  }
}
@media (prefers-reduced-motion: reduce) {
  .girando {
    animation: none;
  }
}
.nota {
  margin: 0;
  font-size: var(--t-caption);
  color: var(--c-text-3);
}

/* --- Previsualización --- */
.deteccion {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--sp-3);
  margin: 0;
}
.deteccion dt {
  color: var(--c-text-3);
  font-size: var(--t-caption);
}
.deteccion dd {
  margin: 0;
  font-size: var(--t-sm);
  font-weight: 600;
}
.reconocidas {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.chip {
  padding: 1px var(--sp-2);
  border: 1px solid var(--c-border);
  border-radius: var(--r-full);
  background-color: var(--c-surface-2);
  font-size: var(--t-caption);
}
.envoltorio-tabla {
  overflow-x: auto;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
}
.tabla-muestra {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-caption);
}
.tabla-muestra th {
  padding: var(--sp-2);
  text-align: left;
  border-bottom: 1px solid var(--c-border);
  white-space: nowrap;
}
.tabla-muestra td {
  padding: var(--sp-2);
  border-bottom: 1px solid var(--c-border-soft);
  white-space: nowrap;
}

/* --- Revisión --- */
.cifras {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--sp-3);
}
.cifra {
  display: flex;
  flex-direction: column;
  margin: 0;
}
.valor {
  font-size: var(--t-h3);
  font-weight: 600;
}
.rotulo {
  font-size: var(--t-caption);
  color: var(--c-text-3);
}
.gasto {
  color: var(--c-negative);
}
.ingreso {
  color: var(--c-positive);
}
.opciones {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--sp-4);
  align-items: start;
  padding-top: var(--sp-2);
  border-top: 1px solid var(--c-border);
}

/* --- Resumen --- */
.remate {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  color: var(--c-positive);
}
.remate--deshecha {
  color: var(--c-text-2);
}
.remate h2 {
  color: var(--c-text-1);
}
.texto-modal {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
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
