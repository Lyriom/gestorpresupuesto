<script setup lang="ts">
/**
 * Temáticas (§2.6): árbol con la barra compacta de cada una, menú de fila y las
 * archivadas plegadas al final.
 *
 * El reordenado y el anidado se hacen por teclado con `Ctrl+↑/↓` (subir o bajar
 * entre hermanos) y `Ctrl+←/→` (sacar del padre o meter bajo el hermano de
 * arriba). El arrastre con puntero no está: sin él la operación sigue siendo
 * completa, y un arrastre a medias es peor que ninguno.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Archive,
  ArchiveRestore,
  Ellipsis,
  GitMerge,
  Pencil,
  Plus,
  Trash2,
  Wallet,
} from 'lucide-vue-next'

import type { CategoriaNodo } from '@/api/categorias'
import BarraCategoria from '@/components/presupuesto/BarraCategoria.vue'
import type { AsignacionTematica } from '@/components/presupuesto/types'
import BotonBase from '@/components/ui/BotonBase.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import MenuDesplegable from '@/components/ui/MenuDesplegable.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import { useAvisos } from '@/composables/useAvisos'
import { useCategorias } from '@/stores/categorias'
import { usePresupuesto } from '@/stores/presupuesto'
import BloqueError from './componentes/BloqueError.vue'
import DialogoFusionTematicas from './componentes/DialogoFusionTematicas.vue'
import ModalReparto from './componentes/ModalReparto.vue'
import ModalTematica from './componentes/ModalTematica.vue'

const router = useRouter()
const categorias = useCategorias()
const presupuesto = usePresupuesto()
const avisos = useAvisos()

const edicionAbierta = ref(false)
const enEdicion = ref<CategoriaNodo | null>(null)
const padreSugerido = ref<string | null>(null)

const fusionAbierta = ref(false)
const enFusion = ref<CategoriaNodo | null>(null)

const borradoAbierto = ref(false)
const enBorrado = ref<CategoriaNodo | null>(null)
const reasignarA = ref<string | number | null>(null)
const movimientosDelBorrado = ref(0)

const repartoAbierto = ref(false)
const mostrarArchivadas = ref(false)

const ITEMS_MENU = [
  { clave: 'editar', etiqueta: 'Editar', icono: Pencil },
  { clave: 'subcategoria', etiqueta: 'Añadir subcategoría', icono: Plus },
  { clave: 'movimientos', etiqueta: 'Ver movimientos', icono: Wallet },
  { clave: 'fusionar', etiqueta: 'Fusionar con…', icono: GitMerge },
  { clave: 'archivar', etiqueta: 'Archivar', icono: Archive, separadorAntes: true },
  { clave: 'eliminar', etiqueta: 'Eliminar', icono: Trash2, peligrosa: true },
]

/** Asignación del mes por temática, para pintar la barra compacta de cada fila. */
const asignacionPorId = computed(() => {
  const mapa = new Map<string, AsignacionTematica>()
  const recorrer = (lista: AsignacionTematica[]) => {
    for (const a of lista) {
      mapa.set(a.category_id, a)
      if (a.children?.length) recorrer(a.children)
    }
  }
  recorrer(presupuesto.asignaciones)
  return mapa
})

const visibles = computed(() => categorias.filas.filter((f) => !f.nodo.is_archived))
const archivadas = computed(() => categorias.filas.filter((f) => f.nodo.is_archived))

function crear(): void {
  enEdicion.value = null
  padreSugerido.value = null
  edicionAbierta.value = true
}

async function accion(clave: string, nodo: CategoriaNodo): Promise<void> {
  if (clave === 'editar') {
    enEdicion.value = nodo
    padreSugerido.value = null
    edicionAbierta.value = true
  } else if (clave === 'subcategoria') {
    enEdicion.value = null
    padreSugerido.value = nodo.id
    edicionAbierta.value = true
  } else if (clave === 'movimientos') {
    void router.push({ name: 'movimientos', query: { tematica: nodo.id } })
  } else if (clave === 'fusionar') {
    enFusion.value = nodo
    fusionAbierta.value = true
  } else if (clave === 'archivar') {
    const ok = await categorias.archivar(nodo.id)
    if (ok) avisos.exito(`«${nodo.name}» archivada. Sigue en los informes.`)
  } else if (clave === 'eliminar') {
    enBorrado.value = nodo
    reasignarA.value = null
    const uso = await categorias.uso(nodo.id)
    movimientosDelBorrado.value = uso?.transactions ?? 0
    borradoAbierto.value = true
  }
}

async function confirmarBorrado(): Promise<void> {
  const nodo = enBorrado.value
  if (!nodo) return
  const ok = await categorias.borrar(
    nodo.id,
    reasignarA.value ? String(reasignarA.value) : undefined,
  )
  if (ok) {
    avisos.exito(`«${nodo.name}» eliminada.`)
    borradoAbierto.value = false
  }
}

function tras(): void {
  void categorias.cargar(presupuesto.periodo, true)
  void presupuesto.cargar()
}

function irADetalle(asignacion: AsignacionTematica): void {
  void router.push({ name: 'movimientos', query: { tematica: asignacion.category_id } })
}

/** Reordenar y anidar por teclado. Es el único camino, así que está siempre activo. */
async function mover(indice: number, tecla: string, evento: KeyboardEvent): Promise<void> {
  if (!evento.ctrlKey && !evento.metaKey) return
  evento.preventDefault()
  const fila = visibles.value[indice]
  if (!fila) return
  const hermanos = visibles.value.filter((f) => f.nodo.parent_id === fila.nodo.parent_id)
  const posicion = hermanos.findIndex((f) => f.nodo.id === fila.nodo.id)

  if (tecla === 'ArrowUp' && posicion > 0) {
    await categorias.mover(fila.nodo.id, fila.nodo.parent_id, posicion - 1)
  } else if (tecla === 'ArrowDown' && posicion < hermanos.length - 1) {
    await categorias.mover(fila.nodo.id, fila.nodo.parent_id, posicion + 1)
  } else if (tecla === 'ArrowRight' && posicion > 0) {
    // Anidar bajo el hermano anterior.
    await categorias.mover(fila.nodo.id, hermanos[posicion - 1].nodo.id, 0)
  } else if (tecla === 'ArrowLeft' && fila.nodo.parent_id) {
    const padre = categorias.porId.get(fila.nodo.parent_id)
    await categorias.mover(fila.nodo.id, padre?.parent_id ?? null, (padre?.position ?? 0) + 1)
  }
}

onMounted(() => {
  void categorias.cargar(presupuesto.periodo, true)
  if (!presupuesto.mes) void presupuesto.cargar()
})

// El selector de mes de la barra lateral también manda aquí: la barra compacta
// de cada fila es la del periodo activo.
watch(
  () => presupuesto.periodo,
  (periodo) => void categorias.cargar(periodo, true),
)
</script>

<template>
  <div class="vista">
    <header class="cabecera">
      <h1 class="titulo">Temáticas</h1>
      <div class="acciones">
        <BotonBase variante="secundaria" @click="repartoAbierto = true">
          Cambiar asignación
        </BotonBase>
        <BotonBase variante="primaria" :icono="Plus" @click="crear">Nueva temática</BotonBase>
      </div>
    </header>

    <p class="pista-teclado">
      Con el foco en una fila: <kbd>Ctrl</kbd> + <kbd>↑</kbd> / <kbd>↓</kbd> reordena y
      <kbd>Ctrl</kbd> + <kbd>←</kbd> / <kbd>→</kbd> cambia el nivel de anidación.
    </p>

    <div v-if="categorias.cargando" class="tarjeta caja">
      <EsqueletoCarga variante="barra" :lineas="6" anuncio="Cargando las temáticas" />
    </div>

    <BloqueError
      v-else-if="categorias.error"
      titulo="No se han podido cargar las temáticas"
      :nivel="2"
      @reintentar="categorias.cargar(presupuesto.periodo, true)"
    />

    <div v-else-if="visibles.length === 0" class="tarjeta caja">
      <EstadoVacio
        titulo="Todavía no has creado ninguna temática."
        descripcion="Empieza por las de siempre: vivienda, alimentación, transporte."
        :nivel="2"
      >
        <template #accion>
          <BotonBase variante="primaria" @click="crear">Crear la primera</BotonBase>
        </template>
      </EstadoVacio>
    </div>

    <ul v-else class="tarjeta arbol">
      <li
        v-for="(fila, i) in visibles"
        :key="fila.nodo.id"
        class="fila"
        :style="{ '--nivel': fila.nivel }"
        tabindex="0"
        @keydown="mover(i, $event.key, $event)"
      >
        <div class="contenido-fila">
          <BarraCategoria
            v-if="asignacionPorId.get(fila.nodo.id)"
            :asignacion="asignacionPorId.get(fila.nodo.id) as AsignacionTematica"
            :dia-actual="presupuesto.mes?.day_of_period"
            :dias-del-periodo="presupuesto.mes?.days_in_period"
            :periodo="presupuesto.mes?.period"
            @activar="irADetalle"
            @asignar="repartoAbierto = true"
          />
          <p v-else class="sin-presupuesto">
            <span class="nombre-simple">{{ fila.nodo.name }}</span>
            <span class="tenue">Sin presupuesto este mes</span>
            <BotonBase variante="enlace" tamanyo="sm" @click="repartoAbierto = true">
              Asignar
            </BotonBase>
          </p>
        </div>

        <MenuDesplegable
          :etiqueta="`Acciones de ${fila.nodo.name}`"
          alineacion="derecha"
          :items="ITEMS_MENU"
          @seleccionar="accion($event, fila.nodo)"
        >
          <template #disparador="{ alternar, atributos }">
            <BotonBase
              v-bind="atributos"
              variante="fantasma"
              tamanyo="sm"
              solo-icono
              :icono="Ellipsis"
              :etiqueta-accesible="`Acciones de ${fila.nodo.name}`"
              @click="alternar()"
            />
          </template>
        </MenuDesplegable>
      </li>
    </ul>

    <div v-if="archivadas.length > 0" class="archivadas">
      <BotonBase variante="fantasma" tamanyo="sm" @click="mostrarArchivadas = !mostrarArchivadas">
        Archivadas ({{ archivadas.length }})
      </BotonBase>
      <ul v-if="mostrarArchivadas" class="tarjeta lista-archivadas">
        <li v-for="fila in archivadas" :key="fila.nodo.id">
          <span>{{ fila.nodo.name }}</span>
          <BotonBase
            variante="fantasma"
            tamanyo="sm"
            :icono="ArchiveRestore"
            @click="categorias.desarchivar(fila.nodo.id)"
          >
            Desarchivar
          </BotonBase>
        </li>
      </ul>
    </div>

    <ModalTematica
      v-model:abierto="edicionAbierta"
      :tematica="enEdicion"
      :padre-id="padreSugerido"
      @guardado="tras"
    />

    <DialogoFusionTematicas
      v-model:abierto="fusionAbierta"
      :origen="enFusion"
      @fusionado="tras"
    />

    <ModalReparto v-model:abierto="repartoAbierto" @guardado="tras" />

    <ModalBase
      v-model:abierto="borradoAbierto"
      :titulo="`¿Eliminar «${enBorrado?.name ?? ''}»?`"
      tamanyo="sm"
      :guardando="categorias.guardando"
      :error="categorias.error ?? undefined"
      @cerrar="borradoAbierto = false"
    >
      <p v-if="movimientosDelBorrado === 0" class="parrafo">
        No tiene movimientos asociados.
      </p>
      <template v-else>
        <p class="parrafo">
          «{{ enBorrado?.name }}» tiene {{ movimientosDelBorrado }} movimientos. Puedes fusionarla
          con otra temática o eliminarla reasignando su histórico.
        </p>
        <SelectorBase
          v-model="reasignarA"
          etiqueta="Reasignar su histórico a"
          placeholder="Elige una temática…"
          :opciones="categorias.opciones().filter((o) => o.valor !== enBorrado?.id)"
          requerido
        />
      </template>

      <template #pie>
        <BotonBase variante="contorno" @click="borradoAbierto = false">Cancelar</BotonBase>
        <BotonBase
          variante="peligro"
          :cargando="categorias.guardando"
          :deshabilitado="movimientosDelBorrado > 0 && !reasignarA"
          @click="confirmarBorrado"
        >
          Eliminar
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
.cabecera {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
}
.titulo {
  margin: 0;
  font-size: var(--t-h1);
  line-height: var(--t-h1-lh);
  font-weight: 600;
}
.acciones {
  display: flex;
  gap: var(--sp-2);
}
.pista-teclado {
  margin: 0;
  font-size: var(--t-caption);
  color: var(--c-text-3);
}
.pista-teclado kbd {
  padding: 0 4px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  background-color: var(--c-surface-2);
  font-family: var(--font-mono);
  font-size: var(--t-micro);
}
.caja {
  padding: var(--sp-5);
}

.arbol {
  margin: 0;
  padding: var(--sp-2) var(--sp-4);
  list-style: none;
}
.fila {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding-left: calc(var(--nivel) * var(--sp-6));
  border-radius: var(--r-md);
}
.fila + .fila {
  border-top: 1px solid var(--c-border-soft);
}
.fila:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: -2px;
}
.contenido-fila {
  flex: 1 1 auto;
  min-width: 0;
}
.sin-presupuesto {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin: 0;
  min-height: 48px;
}
.nombre-simple {
  font-weight: 500;
}
.tenue {
  color: var(--c-text-3);
  font-size: var(--t-caption);
}

.archivadas {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  align-items: flex-start;
}
.lista-archivadas {
  width: 100%;
  margin: 0;
  padding: var(--sp-2) var(--sp-4);
  list-style: none;
}
.lista-archivadas li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  min-height: 44px;
  font-size: var(--t-sm);
}
.lista-archivadas li + li {
  border-top: 1px solid var(--c-border-soft);
}

.parrafo {
  margin: 0 0 var(--sp-3);
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
</style>
