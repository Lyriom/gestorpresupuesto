/**
 * Árbol de temáticas.
 *
 * `GET /categories/tree` se carga una vez y se cachea: lo usan la BudgetBar, los
 * selectores de todos los formularios y los filtros de la lista. La jerarquía y
 * el orden vienen resueltos del servidor (`path`, `depth`, `position`).
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  apiCategorias,
  type Categoria,
  type CategoriaActualizar,
  type CategoriaCrear,
  type CategoriaFusionCrear,
  type CategoriaFusionPrevia,
  type CategoriaNodo,
  type CategoriaUso,
  type TipoTematica,
} from '@/api/categorias'
import { mensajeDeError } from './comun'

/**
 * Opción de `SelectorBase`. Se declara aquí, con la misma forma estructural, y
 * no se importa del SFC: así el store no depende de un componente.
 */
export interface OpcionTematica {
  valor: string
  etiqueta: string
  grupo?: string
  ranura?: number
}

/** Fila plana del árbol, con su sangrado ya resuelto para pintar la lista. */
export interface FilaArbol {
  nodo: CategoriaNodo
  nivel: number
  /** Nombre de la temática madre, para el chip `Madre · Hija`. */
  madre: string | null
}

function aplanar(nodos: CategoriaNodo[], nivel = 0, madre: string | null = null): FilaArbol[] {
  const filas: FilaArbol[] = []
  for (const nodo of nodos) {
    filas.push({ nodo, nivel, madre })
    if (nodo.children?.length) filas.push(...aplanar(nodo.children, nivel + 1, nodo.name))
  }
  return filas
}

/**
 * Ranura de color 1..12 a partir del `color` que guarda el backend. Los chips
 * de `EtiquetaCategoria` piden una ranura, no un color CSS; cuando no hay color
 * guardado se deriva del identificador para que sea estable.
 */
export function ranuraDeCategoria(color: string | null | undefined, id: string): number {
  const valor = (color ?? '').trim()
  const soloDigitos = /^\d+$/.exec(valor)
  if (soloDigitos) return ((Number(valor) - 1) % 12) + 1
  const conPrefijo = /^(?:--c-)?cat-?(\d+)$/i.exec(valor)
  if (conPrefijo) return ((Number(conPrefijo[1]) - 1) % 12) + 1
  let suma = 0
  for (let i = 0; i < id.length; i += 1) suma = (suma * 31 + id.charCodeAt(i)) % 100_000
  return (suma % 12) + 1
}

export const useCategorias = defineStore('categorias', () => {
  const arbol = ref<CategoriaNodo[]>([])
  const cargando = ref(false)
  const guardando = ref(false)
  const error = ref<string | null>(null)
  const mostrarArchivadas = ref(false)

  const filas = computed(() => aplanar(arbol.value))
  const planas = computed(() => filas.value.map((f) => f.nodo))
  const archivadas = computed(() => planas.value.filter((c) => c.is_archived))
  const activas = computed(() => planas.value.filter((c) => !c.is_archived))
  const cargado = computed(() => arbol.value.length > 0)

  const porId = computed(() => {
    const mapa = new Map<string, CategoriaNodo>()
    for (const c of planas.value) mapa.set(c.id, c)
    return mapa
  })

  function nombreDe(id: string | null | undefined): string {
    if (!id) return 'Sin clasificar'
    return porId.value.get(id)?.name ?? 'Temática'
  }

  /** Opciones de `SelectorBase`, agrupadas por temática madre. */
  function opciones(kind?: TipoTematica): OpcionTematica[] {
    return filas.value
      .filter((f) => !f.nodo.is_archived && (!kind || f.nodo.kind === kind))
      .map((f) => ({
        valor: f.nodo.id,
        etiqueta: f.nivel === 0 ? f.nodo.name : `${'· '.repeat(f.nivel)}${f.nodo.name}`,
        grupo: f.madre ?? undefined,
        ranura: ranuraDeCategoria(f.nodo.color, f.nodo.id),
      }))
  }

  async function cargar(periodo?: string, forzar = false): Promise<void> {
    if (cargado.value && !forzar && !periodo) return
    cargando.value = true
    error.value = null
    try {
      arbol.value = await apiCategorias.arbol({
        period: periodo,
        is_archived: mostrarArchivadas.value ? undefined : false,
      })
    } catch (e) {
      arbol.value = []
      error.value = mensajeDeError(e, 'No se han podido cargar las temáticas.')
    } finally {
      cargando.value = false
    }
  }

  async function crear(cuerpo: CategoriaCrear): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      await apiCategorias.crear(cuerpo)
      await cargar(undefined, true)
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido crear la temática.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function actualizar(id: string, cuerpo: CategoriaActualizar): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      await apiCategorias.actualizar(id, cuerpo)
      await cargar(undefined, true)
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido guardar la temática.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function archivar(id: string): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      await apiCategorias.archivar(id, true)
      await cargar(undefined, true)
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido archivar la temática.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function desarchivar(id: string): Promise<boolean> {
    guardando.value = true
    try {
      await apiCategorias.desarchivar(id)
      await cargar(undefined, true)
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido desarchivar la temática.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function borrar(id: string, reasignarA?: string): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      await apiCategorias.borrar(id, reasignarA)
      await cargar(undefined, true)
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido eliminar la temática.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function mover(id: string, parentId: string | null, position: number): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      await apiCategorias.mover(id, { parent_id: parentId, position })
      await cargar(undefined, true)
      return true
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido mover la temática.')
      return false
    } finally {
      guardando.value = false
    }
  }

  async function uso(id: string): Promise<CategoriaUso | null> {
    try {
      return await apiCategorias.uso(id)
    } catch {
      return null
    }
  }

  async function previsualizarFusion(
    cuerpo: CategoriaFusionCrear,
  ): Promise<CategoriaFusionPrevia | null> {
    try {
      return await apiCategorias.previsualizarFusion(cuerpo)
    } catch (e) {
      error.value = mensajeDeError(e, 'No se ha podido simular la fusión.')
      return null
    }
  }

  async function fusionar(cuerpo: CategoriaFusionCrear): Promise<boolean> {
    guardando.value = true
    error.value = null
    try {
      await apiCategorias.fusionar(cuerpo)
      await cargar(undefined, true)
      return true
    } catch (e) {
      error.value = mensajeDeError(
        e,
        'No se ha podido completar la fusión. Tus temáticas no han cambiado.',
      )
      return false
    } finally {
      guardando.value = false
    }
  }

  /** Descendientes de una temática: no se puede fusionar con ninguno (RN-18). */
  function descendientesDe(id: string): Set<string> {
    const nodo = porId.value.get(id)
    const conjunto = new Set<string>()
    const recorrer = (hijos: CategoriaNodo[] | undefined) => {
      for (const hijo of hijos ?? []) {
        conjunto.add(hijo.id)
        recorrer(hijo.children)
      }
    }
    recorrer(nodo?.children)
    return conjunto
  }

  return {
    arbol,
    cargando,
    guardando,
    error,
    mostrarArchivadas,
    filas,
    planas,
    activas,
    archivadas,
    cargado,
    porId,
    nombreDe,
    opciones,
    cargar,
    crear,
    actualizar,
    archivar,
    desarchivar,
    borrar,
    mover,
    uso,
    previsualizarFusion,
    fusionar,
    descendientesDe,
  }
})

export type { Categoria, CategoriaNodo }
