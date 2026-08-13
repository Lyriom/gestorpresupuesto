/**
 * Lectura local del CSV, solo para poder pintar el mapeo manual de columnas.
 *
 * El contrato de importación habla de columnas **por nombre** (`date_column:
 * "Fecha valor"`), pero ningún endpoint devuelve la cabecera del fichero: cuando
 * el análisis acaba en `needs_mapping` no se ha creado ninguna fila, así que
 * `GET /imports/{id}/preview` viene vacío y `mapping` es nulo. Sin la cabecera no
 * hay nada que ofrecerle al usuario para que diga qué columna es cada cosa.
 *
 * Así que el fichero, que el navegador ya tiene en memoria, se lee **también**
 * aquí: para sacar la cabecera, unas filas de muestra y una sugerencia inicial.
 * Nada de esto decide la importación —eso siempre lo hace el servidor con el
 * fichero que guardó—, es material de la interfaz.
 *
 * La detección de codificación, delimitador y fila de cabecera es un espejo
 * deliberadamente fiel de `backend/app/services/importacion.py`: el nombre de
 * columna que se envíe tiene que existir en la fila que el servidor considera
 * cabecera, o responde `mapeo_incompleto`.
 */

/** Campos que el análisis sabe rellenar desde una columna del fichero. */
export type CampoCsv =
  | 'fecha'
  | 'concepto'
  | 'importe'
  | 'cargo'
  | 'abono'
  | 'saldo'
  | 'divisa'
  | 'categoria'

/** Índice de columna elegido para cada campo. */
export type MapeoLocal = Partial<Record<CampoCsv, number>>

export interface AnalisisCsvLocal {
  /** Nombre con el que la muestra la interfaz: `utf-8`, `cp1252`… */
  codificacion: string
  delimitador: string
  /** Índice de la fila que hace de cabecera entre las filas no vacías. */
  filaCabecera: number
  cabecera: string[]
  muestra: string[][]
  totalFilas: number
  sugerencia: MapeoLocal
  /** Lo que no se ha reconocido y el usuario tendrá que indicar. */
  camposQueFaltan: CampoCsv[]
  /** `false` si el contenido es OFX o QIF: ahí no hay columnas que mapear. */
  esCsv: boolean
}

const DELIMITADORES = [';', ',', '\t', '|'] as const

/** Cuántas filas de muestra se guardan para la previsualización. */
const FILAS_DE_MUESTRA = 8

/** Mismos alias de cabecera que reconoce el servicio de análisis. */
const ALIAS: Record<CampoCsv, readonly string[]> = {
  fecha: [
    'fecha',
    'fecha operacion',
    'fecha de operacion',
    'f. operacion',
    'fecha valor',
    'fecha contable',
    'date',
    'completed date',
    'booking date',
    'value date',
  ],
  concepto: [
    'concepto',
    'descripcion',
    'descripcion operacion',
    'concepto ampliado',
    'movimiento',
    'detalle',
    'observaciones',
    'referencia',
    'description',
    'payee',
    'merchant',
  ],
  importe: ['importe', 'importe eur', 'importe operacion', 'cantidad', 'amount', 'importe (eur)', 'valor'],
  cargo: ['debe', 'cargo', 'cargos', 'gasto', 'pago', 'salida', 'debit', 'withdrawal'],
  abono: ['haber', 'abono', 'abonos', 'ingreso', 'entrada', 'credit', 'deposit'],
  saldo: ['saldo', 'saldo disponible', 'saldo posterior', 'balance'],
  divisa: ['divisa', 'moneda', 'currency'],
  categoria: ['categoria', 'category'],
}

/** Los tres campos sin los que el servidor no puede interpretar una fila. */
const IMPRESCINDIBLES: CampoCsv[] = ['fecha', 'concepto', 'importe']

function sinAcentos(texto: string): string {
  return texto.normalize('NFKD').replace(/\p{Diacritic}/gu, '')
}

function normalizarCabecera(texto: string): string {
  const limpio = sinAcentos(texto).toLowerCase().trim().replace(/^"+|"+$/g, '')
  return limpio.replace(/[\s_]+/g, ' ').replace(/^[\s.:]+|[\s.:]+$/g, '')
}

/**
 * Decodifica el fichero probando las codificaciones en el mismo orden que el
 * servidor: utf-8 (con y sin BOM) y luego cp1252, que es lo que exportan casi
 * todos los bancos españoles.
 */
function decodificar(datos: ArrayBuffer): { texto: string; codificacion: string } {
  const bytes = new Uint8Array(datos)
  const conBom = bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf
  try {
    const texto = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    return {
      texto: conBom && texto.charCodeAt(0) === 0xfeff ? texto.slice(1) : texto,
      codificacion: conBom ? 'utf-8-sig' : 'utf-8',
    }
  } catch {
    return { texto: new TextDecoder('windows-1252').decode(bytes), codificacion: 'cp1252' }
  }
}

/**
 * Parte el texto en filas y celdas respetando las comillas.
 *
 * No se puede partir por comas y saltos de línea a lo bruto: un concepto de
 * banco lleva comas dentro de comillas y, a veces, saltos de línea.
 */
function partirCsv(texto: string, delimitador: string): string[][] {
  const filas: string[][] = []
  let fila: string[] = []
  let celda = ''
  let enComillas = false

  for (let i = 0; i < texto.length; i += 1) {
    const caracter = texto[i]
    if (enComillas) {
      if (caracter === '"') {
        if (texto[i + 1] === '"') {
          celda += '"'
          i += 1
        } else {
          enComillas = false
        }
      } else {
        celda += caracter
      }
      continue
    }
    if (caracter === '"') {
      enComillas = true
    } else if (caracter === delimitador) {
      fila.push(celda)
      celda = ''
    } else if (caracter === '\n' || caracter === '\r') {
      if (caracter === '\r' && texto[i + 1] === '\n') i += 1
      fila.push(celda)
      filas.push(fila)
      fila = []
      celda = ''
    } else {
      celda += caracter
    }
  }
  if (celda !== '' || fila.length > 0) {
    fila.push(celda)
    filas.push(fila)
  }
  return filas.filter((f) => f.some((c) => c !== ''))
}

/**
 * Elige el delimitador que parte el fichero en columnas de forma consistente.
 *
 * Gana el que da más columnas con el mismo número en todas las líneas; a
 * igualdad manda el orden de la lista, que empieza por el punto y coma
 * precisamente para no confundir la coma decimal de «-30,15» con un separador.
 */
function detectarDelimitador(texto: string): string {
  const lineas = texto
    .split(/\r\n|\n|\r/)
    .slice(0, 20)
    .filter((linea) => linea.trim() !== '')
  if (lineas.length === 0) return ';'

  let mejor = ';'
  let mejorPuntuacion: [number, number] = [-1, -1]
  for (const candidato of DELIMITADORES) {
    const filas = partirCsv(lineas.join('\n'), candidato)
    const anchuras = new Set(
      filas.filter((f) => f.some((c) => c.trim() !== '')).map((f) => f.length),
    )
    if (anchuras.size === 0) continue
    const columnas = Math.max(...anchuras)
    if (columnas < 2) continue
    const puntuacion: [number, number] = [anchuras.size === 1 ? 1 : 0, columnas]
    if (
      puntuacion[0] > mejorPuntuacion[0] ||
      (puntuacion[0] === mejorPuntuacion[0] && puntuacion[1] > mejorPuntuacion[1])
    ) {
      mejor = candidato
      mejorPuntuacion = puntuacion
    }
  }
  return mejor
}

/** Asocia las columnas de una posible cabecera con los campos que se necesitan. */
export function detectarMapeo(cabecera: string[]): MapeoLocal {
  const mapeo: MapeoLocal = {}
  const normalizadas = cabecera.map(normalizarCabecera)
  for (const campo of Object.keys(ALIAS) as CampoCsv[]) {
    const alias = ALIAS[campo]
    for (let indice = 0; indice < normalizadas.length; indice += 1) {
      const celda = normalizadas[indice]
      if (!celda) continue
      if (alias.includes(celda) || alias.some((a) => celda.startsWith(a))) {
        if (mapeo[campo] === undefined) mapeo[campo] = indice
        break
      }
    }
  }
  return mapeo
}

function camposQueFaltan(mapeo: MapeoLocal): CampoCsv[] {
  const faltan: CampoCsv[] = []
  if (mapeo.fecha === undefined) faltan.push('fecha')
  if (mapeo.concepto === undefined) faltan.push('concepto')
  if (mapeo.importe === undefined && mapeo.cargo === undefined && mapeo.abono === undefined) {
    faltan.push('importe')
  }
  return faltan
}

/**
 * Busca la fila que hace de cabecera entre las primeras quince.
 *
 * Varios bancos meten el titular, el IBAN y el periodo antes de la tabla, así
 * que la cabecera real puede estar en la fila 5 o en la 8. El desempate es el
 * mismo que hace el servidor: gana la primera fila con más campos reconocidos.
 */
function localizarCabecera(filas: string[][]): { indice: number; mapeo: MapeoLocal } {
  let indice = 0
  let mejorMapeo: MapeoLocal = {}
  let mejorPuntuacion = -1
  for (let i = 0; i < Math.min(filas.length, 15); i += 1) {
    const mapeo = detectarMapeo(filas[i])
    const puntuacion = (['fecha', 'concepto', 'importe', 'cargo', 'abono'] as CampoCsv[]).filter(
      (campo) => mapeo[campo] !== undefined,
    ).length
    if (puntuacion > mejorPuntuacion) {
      indice = i
      mejorMapeo = mapeo
      mejorPuntuacion = puntuacion
    }
    if (camposQueFaltan(mapeo).length === 0) return { indice: i, mapeo }
  }
  return { indice, mapeo: mejorMapeo }
}

/** `true` si el contenido es OFX o QIF, donde los campos ya vienen separados. */
function esEstructurado(texto: string): boolean {
  const cabeza = texto.slice(0, 4096).toUpperCase()
  return (
    cabeza.includes('OFXHEADER') ||
    cabeza.includes('<OFX>') ||
    cabeza.includes('<STMTTRN>') ||
    cabeza.includes('!TYPE:')
  )
}

/** Lee el fichero elegido y devuelve lo que la pantalla necesita mostrar. */
export async function analizarCsvLocal(fichero: File): Promise<AnalisisCsvLocal> {
  const { texto, codificacion } = decodificar(await fichero.arrayBuffer())
  const vacio: AnalisisCsvLocal = {
    codificacion,
    delimitador: ';',
    filaCabecera: 0,
    cabecera: [],
    muestra: [],
    totalFilas: 0,
    sugerencia: {},
    camposQueFaltan: IMPRESCINDIBLES,
    esCsv: false,
  }
  if (!texto.trim()) return vacio
  if (esEstructurado(texto)) return vacio

  const delimitador = detectarDelimitador(texto)
  const filas = partirCsv(texto, delimitador)
  const { indice, mapeo } = localizarCabecera(filas)
  return {
    codificacion,
    delimitador,
    filaCabecera: indice,
    cabecera: filas[indice] ?? [],
    muestra: filas.slice(indice + 1, indice + 1 + FILAS_DE_MUESTRA),
    totalFilas: Math.max(0, filas.length - indice - 1),
    sugerencia: mapeo,
    camposQueFaltan: camposQueFaltan(mapeo),
    esCsv: true,
  }
}

/** Nombre visible de una columna: su cabecera, o su posición si viene vacía. */
export function nombreDeColumna(cabecera: string[], indice: number): string {
  const texto = (cabecera[indice] ?? '').trim()
  return texto || `Columna ${indice + 1}`
}

/**
 * Nombre con el que hay que enviar una columna en el mapeo, o `null` si no tiene
 * título y por tanto no se puede asignar.
 *
 * El servidor resuelve el mapeo buscando el nombre **literal** en la fila que
 * considera cabecera (sin distinguir mayúsculas ni espacios de los extremos), así
 * que una columna sin título no hay forma de nombrarla: cualquier invento
 * responde `mapeo_incompleto`.
 */
export function valorDeColumna(cabecera: string[], indice: number): string | null {
  const texto = (cabecera[indice] ?? '').trim()
  return texto ? texto.slice(0, 120) : null
}

/** `true` si la columna tiene título y se le puede asignar un campo. */
export function columnaAsignable(cabecera: string[], indice: number): boolean {
  return valorDeColumna(cabecera, indice) !== null
}
