import { computed, readonly, ref } from 'vue'

export type TipoAviso = 'exito' | 'info' | 'aviso' | 'error'

export interface AccionAviso {
  etiqueta: string
  alPulsar: () => void
}

export interface OpcionesAviso {
  mensaje: string
  tipo?: TipoAviso
  titulo?: string
  /** Milisegundos. 0 = no se cierra solo. Por defecto, lo que diga el tipo. */
  duracion?: number
  accion?: AccionAviso
}

export interface Aviso {
  id: number
  tipo: TipoAviso
  mensaje: string
  titulo?: string
  duracion: number
  accion?: AccionAviso
}

/** §5.9: éxito 4 s · info 5 s · aviso 7 s · error no se cierra solo. */
const DURACIONES: Record<TipoAviso, number> = {
  exito: 4000,
  info: 5000,
  aviso: 7000,
  error: 0,
}

const MAX_VISIBLES = 3

interface Temporizador {
  restante: number
  desde: number
  handle: ReturnType<typeof setTimeout> | null
}

const visibles = ref<Aviso[]>([])
const cola = ref<Aviso[]>([])
const pausado = ref(false)
const temporizadores = new Map<number, Temporizador>()
let siguienteId = 1

function arrancar(id: number): void {
  const t = temporizadores.get(id)
  if (!t || t.restante <= 0) return
  t.desde = Date.now()
  t.handle = setTimeout(() => cerrar(id), t.restante)
}

function detener(id: number): void {
  const t = temporizadores.get(id)
  if (!t || t.handle === null) return
  clearTimeout(t.handle)
  t.handle = null
  t.restante = Math.max(0, t.restante - (Date.now() - t.desde))
}

function mostrar(aviso: Aviso): void {
  visibles.value = [...visibles.value, aviso]
  temporizadores.set(aviso.id, { restante: aviso.duracion, desde: Date.now(), handle: null })
  if (aviso.duracion > 0 && !pausado.value) arrancar(aviso.id)
}

function cerrar(id: number): void {
  detener(id)
  temporizadores.delete(id)
  visibles.value = visibles.value.filter((a) => a.id !== id)
  const siguiente = cola.value.shift()
  if (siguiente) mostrar(siguiente)
}

function avisar(opciones: OpcionesAviso): number {
  const tipo = opciones.tipo ?? 'info'
  const aviso: Aviso = {
    id: siguienteId++,
    tipo,
    mensaje: opciones.mensaje,
    titulo: opciones.titulo,
    duracion: opciones.duracion ?? DURACIONES[tipo],
    accion: opciones.accion,
  }
  if (visibles.value.length < MAX_VISIBLES) mostrar(aviso)
  else cola.value.push(aviso)
  return aviso.id
}

/** Se pausa al pasar el puntero o al recibir el foco la región de avisos. */
function pausar(): void {
  if (pausado.value) return
  pausado.value = true
  for (const id of temporizadores.keys()) detener(id)
}

function reanudar(): void {
  if (!pausado.value) return
  pausado.value = false
  for (const id of temporizadores.keys()) arrancar(id)
}

function limpiar(): void {
  for (const id of [...temporizadores.keys()]) {
    detener(id)
    temporizadores.delete(id)
  }
  visibles.value = []
  cola.value = []
}

const atajo = (tipo: TipoAviso) => (mensaje: string, extra?: Omit<OpcionesAviso, 'mensaje' | 'tipo'>) =>
  avisar({ ...extra, mensaje, tipo })

/**
 * Cola de avisos flotantes. Es un singleton de módulo, no un store de Pinia:
 * no tiene estado de dominio y cualquier capa (incluido el cliente HTTP) debe
 * poder llamarlo sin depender de la app montada.
 */
export function useAvisos() {
  return {
    avisos: readonly(visibles),
    enEspera: computed(() => cola.value.length),
    pausado: readonly(pausado),
    avisar,
    exito: atajo('exito'),
    info: atajo('info'),
    aviso: atajo('aviso'),
    error: atajo('error'),
    cerrar,
    pausar,
    reanudar,
    limpiar,
  }
}
