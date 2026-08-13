/**
 * Importación de extractos bancarios (F-25): un flujo con estado, en pasos.
 *
 * El lote manda: `status` es la única fuente de verdad de en qué punto está la
 * importación (`analyzing`, `needs_mapping`, `ready`, `committed`, `failed`), y
 * el paso visible se deriva de él. Nada se recalcula que el servidor ya calcule;
 * lo único que se deriva aquí es **cuántas filas y cuánto dinero se van a
 * importar**, porque cambia al vuelo según lo que el usuario excluya, corrija o
 * desmarque como duplicado, y eso el servidor solo lo sabe al confirmar.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  apiImportaciones,
  type EstadoAnalisis,
  type FilaImportacion,
  type FilaImportacionActualizar,
  type Importacion,
  type MapeoImportacion,
  type ResultadoImportacion,
} from '@/api/importaciones'
import { aNumero } from '@/lib/formato'
import { mensajeDeError } from './comun'
import { analizarCsvLocal, type AnalisisCsvLocal } from './csvLocal'

/** Ritmo de sondeo por defecto mientras el fichero se analiza. */
const RITMO_SONDEO_MS = 1500

/** El servidor pagina a 200 como máximo; la revisión necesita todas las filas. */
const TAMANYO_PAGINA = 200

/** Tope de filas por importación en el servicio de análisis. */
const MAX_FILAS = 5000

/** En la previsualización basta una muestra: la tabla completa es el paso siguiente. */
const FILAS_PREVISUALIZACION = TAMANYO_PAGINA

export const EXTENSIONES_ADMITIDAS = ['.csv', '.txt', '.ofx', '.qfx', '.qif'] as const

export type PasoImportacion =
  | 'fichero'
  | 'analizando'
  | 'previsualizacion'
  | 'mapeo'
  | 'revision'
  | 'resumen'
  | 'fallo'

export const useImportaciones = defineStore('importaciones', () => {
  // --- Flujo activo ---
  const paso = ref<PasoImportacion>('fichero')
  const fichero = ref<File | null>(null)
  const cuentaId = ref<string | null>(null)
  const lote = ref<Importacion | null>(null)
  const estadoAnalisis = ref<EstadoAnalisis | null>(null)
  const analisisLocal = ref<AnalisisCsvLocal | null>(null)
  const filas = ref<FilaImportacion[]>([])
  const resultado = ref<ResultadoImportacion | null>(null)

  // --- Opciones de la confirmación ---
  const omitirDuplicados = ref(true)
  const tematicaPorDefecto = ref<string | null>(null)

  // --- Estados de carga y error ---
  const subiendo = ref(false)
  const progresoSubida = ref(0)
  const cargandoLote = ref(false)
  const cargandoFilas = ref(false)
  const guardandoMapeo = ref(false)
  const confirmando = ref(false)
  const revirtiendo = ref<string | null>(null)
  const filasEnCurso = ref<string[]>([])
  const errorFichero = ref<string | null>(null)
  const error = ref<string | null>(null)
  const filasTruncadas = ref(false)

  // --- Historial ---
  const historial = ref<Importacion[]>([])
  const cargandoHistorial = ref(false)
  const errorHistorial = ref<string | null>(null)

  let sondeo: ReturnType<typeof setTimeout> | null = null

  const analizando = computed(() => lote.value?.status === 'analyzing')
  const necesitaMapeo = computed(() => lote.value?.status === 'needs_mapping')
  const fallida = computed(() => lote.value?.status === 'failed')
  const confirmada = computed(() => lote.value?.status === 'committed')

  /** Campos que el servidor no ha sabido reconocer en la cabecera del fichero. */
  const camposQueFaltan = computed(() => estadoAnalisis.value?.missing_fields ?? [])

  const conError = computed(() => filas.value.filter((f) => f.status === 'error'))
  const duplicadas = computed(() => filas.value.filter((f) => f.is_duplicate))
  const excluidas = computed(() => filas.value.filter((f) => f.is_skipped))

  /** Las filas que van a crear un movimiento si se confirma ahora mismo. */
  const importables = computed(() =>
    filas.value.filter(
      (f) =>
        f.status !== 'error' &&
        !f.is_skipped &&
        (!f.is_duplicate || !omitirDuplicados.value) &&
        f.date &&
        aNumero(f.amount) !== 0,
    ),
  )

  const totalImportar = computed(() =>
    importables.value.reduce((suma, f) => suma + aNumero(f.amount), 0),
  )
  const totalGastos = computed(() =>
    importables.value.reduce((suma, f) => suma + Math.min(aNumero(f.amount), 0), 0),
  )
  const totalIngresos = computed(() =>
    importables.value.reduce((suma, f) => suma + Math.max(aNumero(f.amount), 0), 0),
  )

  const puedeConfirmar = computed(
    () => lote.value?.status === 'ready' && importables.value.length > 0 && !confirmando.value,
  )

  function enCurso(filaId: string): boolean {
    return filasEnCurso.value.includes(filaId)
  }

  /* ---------------------------------------------------------------- *
   * Paso 1: elegir el fichero
   * ---------------------------------------------------------------- */

  /** Valida el fichero en local para no gastar una subida en balde. */
  function validar(candidato: File, maxMb: number): boolean {
    const nombre = candidato.name.toLowerCase()
    const admitida = EXTENSIONES_ADMITIDAS.some((e) => nombre.endsWith(e))
    if (!admitida) {
      errorFichero.value = 'Solo se admiten extractos en CSV, OFX o QIF.'
      return false
    }
    if (candidato.size > maxMb * 1024 * 1024) {
      errorFichero.value = `El fichero pesa más de ${maxMb} MB.`
      return false
    }
    if (candidato.size === 0) {
      errorFichero.value = 'El fichero está vacío.'
      return false
    }
    errorFichero.value = null
    return true
  }

  /**
   * Guarda el fichero elegido y lo lee en local.
   *
   * La lectura local solo alimenta la previsualización y el mapeo manual: el
   * análisis que cuenta es el del servidor sobre el fichero que ha guardado.
   */
  async function elegirFichero(candidato: File, maxMb: number): Promise<boolean> {
    if (!validar(candidato, maxMb)) return false
    fichero.value = candidato
    try {
      analisisLocal.value = await analizarCsvLocal(candidato)
    } catch {
      // Sin lectura local se pierde la cabecera, no la importación.
      analisisLocal.value = null
    }
    return true
  }

  function quitarFichero(): void {
    fichero.value = null
    analisisLocal.value = null
    errorFichero.value = null
  }

  /**
   * Vuelve a leer el mismo fichero en local sin subirlo otra vez.
   *
   * Hace falta cuando se retoma una importación en `needs_mapping` desde el
   * historial o tras recargar la página: el lote sigue en el servidor, pero la
   * cabecera del fichero solo la tiene el navegador.
   */
  async function reengancharFichero(candidato: File): Promise<void> {
    fichero.value = candidato
    try {
      analisisLocal.value = await analizarCsvLocal(candidato)
    } catch {
      analisisLocal.value = null
    }
  }

  /* ---------------------------------------------------------------- *
   * Paso 2: subir y analizar
   * ---------------------------------------------------------------- */

  async function subir(): Promise<Importacion | null> {
    if (!fichero.value || !cuentaId.value) return null
    subiendo.value = true
    progresoSubida.value = 0
    error.value = null
    errorFichero.value = null
    filas.value = []
    resultado.value = null
    estadoAnalisis.value = null
    paso.value = 'analizando'
    try {
      const subido = await apiImportaciones.subir(
        fichero.value,
        { account_id: cuentaId.value },
        (pct) => {
          progresoSubida.value = pct
        },
      )
      lote.value = subido
      arrancarSondeo(subido.id)
      return subido
    } catch (e) {
      errorFichero.value = mensajeDeError(e, 'No se ha podido subir el fichero.')
      paso.value = 'fichero'
      return null
    } finally {
      subiendo.value = false
    }
  }

  /** Sondea el análisis al ritmo que marca el propio servidor. */
  function arrancarSondeo(id: string): void {
    detenerSondeo()
    const tick = async (): Promise<void> => {
      try {
        const nuevo = await apiImportaciones.estado(id)
        estadoAnalisis.value = nuevo
        if (nuevo.status === 'analyzing') {
          const espera = (nuevo.retry_after_seconds ?? 0) * 1000 || RITMO_SONDEO_MS
          sondeo = setTimeout(() => void tick(), espera)
          return
        }
        detenerSondeo()
        await alTerminarAnalisis(id)
      } catch (e) {
        detenerSondeo()
        error.value = mensajeDeError(e, 'No se ha podido analizar el fichero.')
        paso.value = 'fallo'
      }
    }
    void tick()
  }

  function detenerSondeo(): void {
    if (sondeo) clearTimeout(sondeo)
    sondeo = null
  }

  /** Coloca el paso que toca en cuanto el análisis deja de estar en curso. */
  async function alTerminarAnalisis(id: string): Promise<void> {
    const venimosDelMapeo = paso.value === 'mapeo'
    await cargarLote(id)
    const estado = lote.value?.status
    if (estado === 'needs_mapping') {
      paso.value = 'mapeo'
      return
    }
    if (estado === 'failed') {
      paso.value = 'fallo'
      return
    }
    if (estado === 'ready') {
      // Tras un mapeo a mano no hace falta repetir la previsualización.
      paso.value = venimosDelMapeo ? 'revision' : 'previsualizacion'
      if (paso.value === 'revision') await cargarFilas()
      else await cargarFilas(FILAS_PREVISUALIZACION)
      return
    }
    if (estado === 'committed') paso.value = 'resumen'
  }

  async function cargarLote(id: string): Promise<void> {
    cargandoLote.value = true
    error.value = null
    try {
      lote.value = await apiImportaciones.obtener(id)
      if (lote.value.account_id) cuentaId.value = lote.value.account_id
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido cargar esta importación.')
      lote.value = null
    } finally {
      cargandoLote.value = false
    }
  }

  /** Retoma una importación por su identificador: del historial o de la URL. */
  async function retomar(id: string): Promise<void> {
    detenerSondeo()
    filas.value = []
    resultado.value = null
    estadoAnalisis.value = null
    paso.value = 'analizando'
    await cargarLote(id)
    const estado = lote.value?.status
    if (!estado) {
      paso.value = 'fallo'
      return
    }
    if (estado === 'analyzing') {
      arrancarSondeo(id)
      return
    }
    try {
      estadoAnalisis.value = await apiImportaciones.estado(id)
    } catch {
      // El sondeo es un extra: sin él solo se pierde la lista de campos que faltan.
    }
    if (estado === 'needs_mapping') {
      paso.value = 'mapeo'
      return
    }
    if (estado === 'failed') {
      paso.value = 'fallo'
      return
    }
    if (estado === 'committed') {
      paso.value = 'resumen'
      return
    }
    paso.value = 'revision'
    await cargarFilas()
  }

  /* ---------------------------------------------------------------- *
   * Paso 3: mapeo manual de columnas
   * ---------------------------------------------------------------- */

  async function guardarMapeo(mapeo: MapeoImportacion): Promise<boolean> {
    if (!lote.value) return false
    guardandoMapeo.value = true
    error.value = null
    try {
      lote.value = await apiImportaciones.fijarMapeo(lote.value.id, mapeo)
      arrancarSondeo(lote.value.id)
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido aplicar el mapeo de columnas.')
      return false
    } finally {
      guardandoMapeo.value = false
    }
  }

  function irAlMapeo(): void {
    paso.value = 'mapeo'
  }

  /* ---------------------------------------------------------------- *
   * Paso 4: revisión de las filas
   * ---------------------------------------------------------------- */

  /** Trae todas las filas del lote, paginando hasta el tope del análisis. */
  async function cargarFilas(tope = MAX_FILAS): Promise<void> {
    if (!lote.value) return
    cargandoFilas.value = true
    error.value = null
    filasTruncadas.value = false
    try {
      const acumuladas: FilaImportacion[] = []
      let pagina = 1
      let paginas = 1
      do {
        const respuesta = await apiImportaciones.filas(lote.value.id, {
          page: pagina,
          size: TAMANYO_PAGINA,
          sort: 'row_number',
        })
        acumuladas.push(...respuesta.items)
        paginas = respuesta.pages
        pagina += 1
      } while (pagina <= paginas && acumuladas.length < tope)
      filasTruncadas.value = acumuladas.length >= tope && pagina <= paginas
      filas.value = acumuladas
    } catch (e) {
      error.value = mensajeDeError(e, 'No se han podido cargar las filas del fichero.')
    } finally {
      cargandoFilas.value = false
    }
  }

  async function irALaRevision(): Promise<void> {
    paso.value = 'revision'
    if (filas.value.length < (lote.value?.rows_total ?? 0)) await cargarFilas()
  }

  function reemplazar(fila: FilaImportacion): void {
    filas.value = filas.value.map((f) => (f.id === fila.id ? fila : f))
  }

  /** Corrige una fila. El servidor recalcula la huella y le quita el error. */
  async function corregirFila(
    filaId: string,
    cambios: FilaImportacionActualizar,
  ): Promise<boolean> {
    if (!lote.value) return false
    filasEnCurso.value = [...filasEnCurso.value, filaId]
    try {
      reemplazar(await apiImportaciones.corregirFila(lote.value.id, filaId, cambios))
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido guardar la corrección.')
      return false
    } finally {
      filasEnCurso.value = filasEnCurso.value.filter((id) => id !== filaId)
    }
  }

  function excluirFila(fila: FilaImportacion, excluida: boolean): Promise<boolean> {
    return corregirFila(fila.id, { is_skipped: excluida })
  }

  /** Marca o desmarca el duplicado: RN-68 lo decide el usuario. */
  function marcarDuplicada(fila: FilaImportacion, duplicada: boolean): Promise<boolean> {
    return corregirFila(fila.id, { is_duplicate: duplicada })
  }

  /* ---------------------------------------------------------------- *
   * Paso 5: confirmar, resumir y deshacer
   * ---------------------------------------------------------------- */

  async function confirmar(): Promise<ResultadoImportacion | null> {
    if (!lote.value) return null
    confirmando.value = true
    error.value = null
    try {
      const salida = await apiImportaciones.confirmar(lote.value.id, {
        skip_duplicates: omitirDuplicados.value,
        create_missing_payees: true,
        default_category_id: tematicaPorDefecto.value,
      })
      resultado.value = salida
      await cargarLote(lote.value.id)
      paso.value = 'resumen'
      void cargarHistorial()
      return salida
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido confirmar la importación.')
      return null
    } finally {
      confirmando.value = false
    }
  }

  async function revertir(id: string): Promise<ResultadoImportacion | null> {
    revirtiendo.value = id
    error.value = null
    try {
      const salida = await apiImportaciones.revertir(id)
      if (lote.value?.id === id) {
        resultado.value = salida
        await cargarLote(id)
      }
      await cargarHistorial()
      return salida
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido deshacer la importación.')
      return null
    } finally {
      revirtiendo.value = null
    }
  }

  /** Descarta un lote sin confirmar: borra el fichero y sus filas. */
  async function descartar(id: string): Promise<boolean> {
    error.value = null
    try {
      await apiImportaciones.borrar(id)
      if (lote.value?.id === id) reiniciar()
      await cargarHistorial()
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido descartar la importación.')
      return false
    }
  }

  /* ---------------------------------------------------------------- *
   * Historial
   * ---------------------------------------------------------------- */

  async function cargarHistorial(): Promise<void> {
    cargandoHistorial.value = true
    errorHistorial.value = null
    try {
      const pagina = await apiImportaciones.listar({ size: 20, sort: '-created_at' })
      historial.value = pagina.items
    } catch (e) {
      historial.value = []
      errorHistorial.value = mensajeDeError(e, 'No se ha podido cargar el historial.')
    } finally {
      cargandoHistorial.value = false
    }
  }

  /** Deja el flujo listo para otro fichero, sin tocar el historial. */
  function reiniciar(): void {
    detenerSondeo()
    paso.value = 'fichero'
    fichero.value = null
    lote.value = null
    estadoAnalisis.value = null
    analisisLocal.value = null
    filas.value = []
    resultado.value = null
    progresoSubida.value = 0
    errorFichero.value = null
    error.value = null
    filasTruncadas.value = false
    omitirDuplicados.value = true
    tematicaPorDefecto.value = null
  }

  return {
    paso,
    fichero,
    cuentaId,
    lote,
    estadoAnalisis,
    analisisLocal,
    filas,
    resultado,
    omitirDuplicados,
    tematicaPorDefecto,
    subiendo,
    progresoSubida,
    cargandoLote,
    cargandoFilas,
    guardandoMapeo,
    confirmando,
    revirtiendo,
    errorFichero,
    error,
    filasTruncadas,
    historial,
    cargandoHistorial,
    errorHistorial,
    analizando,
    necesitaMapeo,
    fallida,
    confirmada,
    camposQueFaltan,
    conError,
    duplicadas,
    excluidas,
    importables,
    totalImportar,
    totalGastos,
    totalIngresos,
    puedeConfirmar,
    enCurso,
    elegirFichero,
    quitarFichero,
    reengancharFichero,
    subir,
    arrancarSondeo,
    detenerSondeo,
    cargarLote,
    retomar,
    guardarMapeo,
    irAlMapeo,
    cargarFilas,
    irALaRevision,
    corregirFila,
    excluirFila,
    marcarDuplicada,
    confirmar,
    revertir,
    descartar,
    cargarHistorial,
    reiniciar,
  }
})
