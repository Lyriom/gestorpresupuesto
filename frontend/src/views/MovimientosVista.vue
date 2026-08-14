<script setup lang="ts">
/**
 * Movimientos (§2.4): lista con filtros combinables, fila expandible y detalle
 * en cajón lateral.
 *
 * Todo el estado de la lista viaja en la URL (`aQuery` / `deQuery` del router),
 * así que un enlace pegado en otro sitio reproduce exactamente la misma vista.
 * La ordenación la decide el usuario y la ejecuta el servidor: aquí nunca se
 * reordena en memoria.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus } from 'lucide-vue-next'

import { apiAjustes } from '@/api/ajustes'
import { ETIQUETA_TIPO_MOVIMIENTO, type Movimiento, type TipoMovimiento } from '@/api/movimientos'
import { centimosDeImporte, importeDeCentimos } from '@/api/comun'
import BarraBusqueda from '@/components/ui/BarraBusqueda.vue'
import BotonBase from '@/components/ui/BotonBase.vue'
import CajonLateral from '@/components/ui/CajonLateral.vue'
import CampoFecha from '@/components/ui/CampoFecha.vue'
import CampoImporte from '@/components/ui/CampoImporte.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import EtiquetaCategoria from '@/components/ui/EtiquetaCategoria.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import PaginacionBase from '@/components/ui/PaginacionBase.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import TablaDatos, { type ColumnaTabla } from '@/components/ui/TablaDatos.vue'
import { useAvisos } from '@/composables/useAvisos'
import { dinero, fechaCorta, porcentaje } from '@/lib/formato'
import { aQuery, aplicarQueryAlStore, deQuery } from '@/router'
import { ranuraDeCategoria, useCategorias } from '@/stores/categorias'
import { mensajeDeError } from '@/stores/comun'
import { useCuentas } from '@/stores/cuentas'
import { useMovimientos } from '@/stores/movimientos'
import ModalMovimiento from './componentes/ModalMovimiento.vue'

/** Fila de la tabla: `TablaDatos` pide un `Record<string, unknown>`. */
type Fila = Movimiento & Record<string, unknown>

const route = useRoute()
const router = useRouter()
const lista = useMovimientos()
const categorias = useCategorias()
const cuentas = useCuentas()
const avisos = useAvisos()

const filtrosAbiertos = ref(false)
const altaAbierta = ref(false)
const modoAlta = ref<'rapido' | 'completo'>('rapido')

const vistaAbierta = ref(false)
const nombreVista = ref('')
const guardandoVista = ref(false)
const errorVista = ref<string | null>(null)

/**
 * La vista guardada almacena la *query string* tal cual, que es lo que espera
 * `SavedViewIn`: así reabrirla es navegar a esa URL y nada más.
 */
async function guardarVista(): Promise<void> {
  errorVista.value = null
  if (!nombreVista.value.trim()) {
    errorVista.value = 'Este campo es obligatorio.'
    return
  }
  guardandoVista.value = true
  try {
    await apiAjustes.guardarVista({
      name: nombreVista.value.trim(),
      resource: 'transactions',
      filters: aQuery({
        filtros: lista.filtros,
        pagina: 1,
        tamanyoPagina: lista.tamanyoPagina,
        orden: lista.orden,
      }) as Record<string, unknown>,
    })
    avisos.exito(`Vista «${nombreVista.value.trim()}» guardada.`)
    nombreVista.value = ''
    vistaAbierta.value = false
  } catch (e) {
    errorVista.value = mensajeDeError(e, 'No se ha podido guardar la vista.')
  } finally {
    guardandoVista.value = false
  }
}

// Copia de trabajo del panel «Más filtros»: no se aplica hasta pulsar el botón.
const minimoCentimos = ref<number | null>(null)
const maximoCentimos = ref<number | null>(null)

const COLUMNAS: ColumnaTabla<Fila>[] = [
  { clave: 'date', etiqueta: 'Fecha', ordenable: true, ancho: '120px' },
  { clave: 'description', etiqueta: 'Concepto', ordenable: true },
  { clave: 'category', etiqueta: 'Temática' },
  { clave: 'account', etiqueta: 'Cuenta', soloEscritorio: true },
  { clave: 'amount', etiqueta: 'Importe', numerica: true, ordenable: true, ancho: '140px' },
]

const filas = computed<Fila[]>(() => lista.items as Fila[])

const opcionesTipo = (['expense', 'income', 'transfer'] as TipoMovimiento[]).map((t) => ({
  valor: t,
  etiqueta: ETIQUETA_TIPO_MOVIMIENTO[t],
}))

/** Chips de los filtros aplicados, con su nombre legible. */
const chips = computed(() => {
  const f = lista.filtros
  const salida: Array<{ clave: string; etiqueta: string; ranura?: number }> = []
  for (const id of f.tematicas) {
    const c = categorias.porId.get(id)
    salida.push({
      clave: `tematica:${id}`,
      etiqueta: `Temática: ${c?.name ?? 'temática'}`,
      ranura: c ? ranuraDeCategoria(c.color, c.id) : undefined,
    })
  }
  for (const id of f.cuentas) {
    salida.push({ clave: `cuenta:${id}`, etiqueta: `Cuenta: ${cuentas.nombreDe(id)}` })
  }
  for (const t of f.tipos) {
    salida.push({ clave: `tipo:${t}`, etiqueta: ETIQUETA_TIPO_MOVIMIENTO[t] })
  }
  if (f.desde || f.hasta) {
    salida.push({
      clave: 'fechas',
      etiqueta: `${f.desde ? fechaCorta(f.desde) : '…'} – ${f.hasta ? fechaCorta(f.hasta) : '…'}`,
    })
  }
  if (f.minimo || f.maximo) {
    salida.push({
      clave: 'importes',
      etiqueta: `${f.minimo ? dinero(f.minimo) : '…'} – ${f.maximo ? dinero(f.maximo) : '…'}`,
    })
  }
  if (f.conFactura === true) salida.push({ clave: 'factura', etiqueta: 'Solo con factura' })
  if (f.soloRecurrentes) salida.push({ clave: 'recurrentes', etiqueta: 'Solo recurrentes' })
  if (f.soloSinCategorizar) {
    salida.push({ clave: 'sinclasificar', etiqueta: 'Solo sin categorizar' })
  }
  return salida
})

/**
 * Criterio aplicado, en texto. El estado vacío por filtro tiene que repetirlo
 * para que se vea por qué no sale nada (§2.4).
 */
const resumenDeFiltros = computed(() => {
  const partes = chips.value.map((c) => c.etiqueta)
  if (lista.filtros.q) partes.unshift(`Búsqueda: «${lista.filtros.q}»`)
  return partes.length > 0 ? `Filtros aplicados: ${partes.join(' · ')}.` : undefined
})

/** Vuelca el estado del store en la URL, sin apilar entradas de historial. */
function sincronizarUrl(): void {
  const query = aQuery({
    filtros: lista.filtros,
    pagina: lista.pagina,
    tamanyoPagina: lista.tamanyoPagina,
    orden: lista.orden,
  })
  void router.replace({ query })
}

async function recargar(): Promise<void> {
  sincronizarUrl()
  await lista.cargar()
}

function quitarChip(clave: string): void {
  const [tipo, valor] = clave.split(':')
  const f = lista.filtros
  if (tipo === 'tematica') lista.aplicar({ tematicas: f.tematicas.filter((x) => x !== valor) })
  else if (tipo === 'cuenta') lista.aplicar({ cuentas: f.cuentas.filter((x) => x !== valor) })
  else if (tipo === 'tipo') {
    lista.aplicar({ tipos: f.tipos.filter((x) => x !== valor) })
  } else if (clave === 'fechas') lista.aplicar({ desde: null, hasta: null })
  else if (clave === 'importes') lista.aplicar({ minimo: null, maximo: null })
  else if (clave === 'factura') lista.aplicar({ conFactura: null })
  else if (clave === 'recurrentes') lista.aplicar({ soloRecurrentes: false })
  else if (clave === 'sinclasificar') lista.aplicar({ soloSinCategorizar: false })
  void recargar()
}

function quitarTodos(): void {
  lista.limpiarFiltros()
  void recargar()
}

function aplicarMasFiltros(): void {
  lista.aplicar({
    minimo: importeDeCentimos(minimoCentimos.value),
    maximo: importeDeCentimos(maximoCentimos.value),
  })
  filtrosAbiertos.value = false
  void recargar()
}

function abrirMasFiltros(): void {
  minimoCentimos.value = centimosDeImporte(lista.filtros.minimo)
  maximoCentimos.value = centimosDeImporte(lista.filtros.maximo)
  filtrosAbiertos.value = true
}

/**
 * Borrar un movimiento es destructivo y §4 exige confirmarlo nombrando importe y
 * fecha, así que primero se pregunta.
 */
const borradoAbierto = ref(false)
const enBorrado = ref<Movimiento | null>(null)

function pedirBorrado(m: Movimiento): void {
  enBorrado.value = m
  borradoAbierto.value = true
}

const textoBorrado = computed(() => {
  const m = enBorrado.value
  if (!m) return ''
  const tipo = m.kind === 'income' ? 'el ingreso' : 'el gasto'
  return `Se eliminará ${tipo} de ${dinero(m.amount)} del ${fechaCorta(m.date)}. Esta acción no se puede deshacer.`
})

async function confirmarBorrado(): Promise<void> {
  const m = enBorrado.value
  if (!m) return
  const ok = await lista.borrar(m.id)
  if (ok) {
    avisos.exito('Movimiento eliminado.')
    borradoAbierto.value = false
    enBorrado.value = null
  }
}

function abrirCompleto(): void {
  modoAlta.value = 'completo'
  altaAbierta.value = true
}

function abrirRapido(): void {
  modoAlta.value = 'rapido'
  altaAbierta.value = true
}

onMounted(() => {
  aplicarQueryAlStore(route.query)
  void categorias.cargar()
  void cuentas.cargar()
  void lista.cargar()
})

// El enlace de vuelta del navegador también tiene que mover la lista.
watch(
  () => route.fullPath,
  () => {
    const nuevo = deQuery(route.query)
    const actual = aQuery({
      filtros: lista.filtros,
      pagina: lista.pagina,
      tamanyoPagina: lista.tamanyoPagina,
      orden: lista.orden,
    })
    if (JSON.stringify(aQuery(nuevo)) === JSON.stringify(actual)) return
    aplicarQueryAlStore(route.query)
    void lista.cargar()
  },
)
</script>

<template>
  <div class="vista">
    <header class="cabecera">
      <h1 class="titulo">Movimientos</h1>
      <div class="acciones">
        <BotonBase variante="secundaria" @click="abrirCompleto">Nuevo movimiento completo</BotonBase>
        <BotonBase variante="primaria" :icono="Plus" @click="abrirRapido">Añadir gasto</BotonBase>
      </div>
    </header>

    <BarraBusqueda
      :model-value="lista.filtros.q"
      :resultados="lista.total"
      :buscando="lista.recargando"
      :filtros-activos="lista.filtrosActivos"
      :chips="chips"
      @update:model-value="lista.filtros.q = $event"
      @buscar="
        (texto) => {
          lista.aplicar({ q: texto })
          recargar()
        }
      "
      @limpiar="
        () => {
          lista.aplicar({ q: '' })
          recargar()
        }
      "
      @quitar-chip="quitarChip"
      @quitar-todos="quitarTodos"
      @abrir-filtros="abrirMasFiltros"
    >
      <template #filtros>
        <SelectorBase
          :model-value="lista.filtros.tematicas[0] ?? null"
          etiqueta="Temática"
          etiqueta-oculta
          placeholder="Temática"
          :opciones="categorias.opciones()"
          :cargando="categorias.cargando"
          @update:model-value="
            (v) => {
              lista.aplicar({ tematicas: v ? [String(v)] : [] })
              recargar()
            }
          "
        />
        <SelectorBase
          :model-value="lista.filtros.cuentas[0] ?? null"
          etiqueta="Cuenta"
          etiqueta-oculta
          placeholder="Cuenta"
          :opciones="cuentas.opciones"
          :cargando="cuentas.cargando"
          @update:model-value="
            (v) => {
              lista.aplicar({ cuentas: v ? [String(v)] : [] })
              recargar()
            }
          "
        />
      </template>

      <template #acciones>
        <BotonBase
          variante="fantasma"
          tamanyo="sm"
          :deshabilitado="!lista.hayFiltros"
          @click="vistaAbierta = true"
        >
          Guardar vista
        </BotonBase>
      </template>
    </BarraBusqueda>

    <TablaDatos
      :columnas="COLUMNAS"
      :filas="filas"
      :clave-fila="(f) => f.id"
      titulo="Movimientos filtrados"
      titulo-oculto
      :orden="lista.orden"
      :cargando="lista.cargando"
      :recargando="lista.recargando"
      expandible
      :vacio-por-filtro="lista.hayFiltros"
      :error="lista.error ?? undefined"
      :rotulo-totales="`Total de ${lista.total} resultados filtrados: ${dinero(lista.totalFiltrado)}`"
      @update:orden="
        (o) => {
          lista.orden = o
          recargar()
        }
      "
      @fila-clic="(f) => lista.abrirDetalle(f.id)"
      @reintentar="lista.cargar()"
      @quitar-filtros="quitarTodos"
    >
      <template #vacio>
        <EstadoVacio
          v-if="lista.hayFiltros"
          tipo="sin-filtros"
          titulo="Ningún movimiento coincide con estos filtros."
          :descripcion="resumenDeFiltros"
          :nivel="3"
        >
          <template #accion>
            <BotonBase variante="contorno" @click="quitarTodos">Quitar todos</BotonBase>
          </template>
        </EstadoVacio>
        <EstadoVacio
          v-else
          titulo="Todavía no has apuntado ningún movimiento."
          :nivel="3"
        >
          <template #accion>
            <BotonBase variante="primaria" @click="altaAbierta = true">Añadir el primero</BotonBase>
          </template>
        </EstadoVacio>
      </template>

      <template #celda-date="{ fila }">{{ fechaCorta(fila.date) }}</template>

      <template #celda-description="{ fila }">
        {{ fila.description || fila.payee?.name || 'Sin concepto' }}
      </template>

      <template #celda-category="{ fila }">
        <EtiquetaCategoria
          v-if="fila.category"
          :nombre="fila.category.name"
          :ranura="ranuraDeCategoria(fila.category.color, fila.category.id)"
          tamanyo="sm"
        />
        <EtiquetaCategoria v-else-if="fila.is_split" nombre="Repartido" :ranura="0" tamanyo="sm" />
        <span v-else class="tenue">Sin clasificar</span>
      </template>

      <template #celda-account="{ fila }">{{ fila.account?.name ?? '—' }}</template>

      <template #celda-amount="{ fila }">
        <span :class="fila.kind === 'income' ? 'positivo' : ''">
          {{ dinero(fila.signed_amount, { signoSiempre: true }) }}
        </span>
      </template>

      <template #detalle="{ fila }">
        <div class="detalle">
          <p class="detalle-titulo">Desglose del movimiento</p>
          <ul v-if="fila.splits.length > 0" class="splits">
            <li v-for="s in fila.splits" :key="s.id">
              <EtiquetaCategoria
                v-if="s.category"
                :nombre="s.category.name"
                :ranura="ranuraDeCategoria(s.category.color, s.category.id)"
                tamanyo="sm"
              />
              <span class="num">{{ dinero(s.amount) }}</span>
              <span class="num tenue">
                {{ porcentaje(Number(s.amount) / Number(fila.amount)) }}
              </span>
            </li>
          </ul>
          <p v-else class="tenue">Este movimiento va entero a una sola temática.</p>

          <p class="linea-meta">
            Cuenta: {{ fila.account?.name ?? '—' }}
            <template v-if="fila.invoice_id">
              · Factura vinculada
              <BotonBase
                variante="enlace"
                tamanyo="sm"
                @click="router.push({ name: 'factura', params: { id: fila.invoice_id } })"
              >
                Ver factura
              </BotonBase>
            </template>
          </p>
          <p class="linea-meta">
            Notas: {{ fila.note || '—' }} · Etiquetas:
            <template v-if="fila.tags.length > 0">
              {{ fila.tags.map((t) => t.name).join(', ') }}
            </template>
            <template v-else>—</template>
          </p>
        </div>
      </template>
    </TablaDatos>

    <PaginacionBase
      :pagina="lista.pagina"
      :tamanyo-pagina="lista.tamanyoPagina"
      :total="lista.total"
      :cargando="lista.recargando"
      unidad="movimientos"
      @update:pagina="
        (p) => {
          lista.pagina = p
          recargar()
        }
      "
      @update:tamanyo-pagina="
        (t) => {
          lista.tamanyoPagina = t
          lista.pagina = 1
          recargar()
        }
      "
    />

    <!-- Más filtros -->
    <ModalBase
      v-model:abierto="filtrosAbiertos"
      titulo="Más filtros"
      tamanyo="md"
      @cerrar="filtrosAbiertos = false"
    >
      <div class="rejilla-filtros">
        <CampoFecha
          :model-value="lista.filtros.desde"
          etiqueta="Desde"
          @update:model-value="lista.filtros.desde = $event"
        />
        <CampoFecha
          :model-value="lista.filtros.hasta"
          etiqueta="Hasta"
          @update:model-value="lista.filtros.hasta = $event"
        />
        <CampoImporte v-model="minimoCentimos" etiqueta="Importe mínimo" />
        <CampoImporte v-model="maximoCentimos" etiqueta="Importe máximo" />
        <SelectorBase
          :model-value="lista.filtros.tipos[0] ?? null"
          etiqueta="Tipo"
          placeholder="Cualquiera"
          :opciones="opcionesTipo"
          @update:model-value="
            (v) => (lista.filtros.tipos = v ? [String(v) as TipoMovimiento] : [])
          "
        />
      </div>
      <div class="interruptores">
        <InterruptorBase
          :model-value="lista.filtros.conFactura === true"
          etiqueta="Solo con factura"
          @update:model-value="lista.filtros.conFactura = $event ? true : null"
        />
        <InterruptorBase
          :model-value="lista.filtros.soloRecurrentes"
          etiqueta="Solo recurrentes"
          @update:model-value="lista.filtros.soloRecurrentes = $event"
        />
        <InterruptorBase
          :model-value="lista.filtros.soloSinCategorizar"
          etiqueta="Solo sin categorizar"
          @update:model-value="lista.filtros.soloSinCategorizar = $event"
        />
        <InterruptorBase
          :model-value="lista.filtros.incluirHijas"
          etiqueta="Incluir subcategorías de la temática filtrada"
          descripcion="Activado, el filtro por temática incluye todo su subárbol."
          @update:model-value="lista.filtros.incluirHijas = $event"
        />
      </div>

      <template #pie>
        <BotonBase variante="contorno" @click="quitarTodos">Quitar todos</BotonBase>
        <BotonBase variante="primaria" @click="aplicarMasFiltros">Aplicar filtros</BotonBase>
      </template>
    </ModalBase>

    <!-- Guardar vista -->
    <ModalBase
      v-model:abierto="vistaAbierta"
      titulo="Guardar esta vista"
      subtitulo="Guarda la combinación de filtros con un nombre para volver a ella."
      tamanyo="sm"
      :guardando="guardandoVista"
      :error="errorVista ?? undefined"
      @cerrar="vistaAbierta = false"
    >
      <CampoTexto
        v-model="nombreVista"
        etiqueta="Nombre de la vista"
        placeholder="Alimentación de este trimestre"
        requerido
        @enter="guardarVista"
      />
      <template #pie>
        <BotonBase variante="contorno" @click="vistaAbierta = false">Cancelar</BotonBase>
        <BotonBase variante="primaria" :cargando="guardandoVista" @click="guardarVista">
          Guardar
        </BotonBase>
      </template>
    </ModalBase>

    <!-- Detalle -->
    <CajonLateral
      :abierto="lista.seleccionado !== null"
      :titulo="lista.seleccionado?.description || lista.seleccionado?.payee?.name || 'Movimiento'"
      :subtitulo="
        lista.seleccionado
          ? `${lista.seleccionado.account?.name ?? ''} · ${fechaCorta(lista.seleccionado.date)}`
          : undefined
      "
      @update:abierto="(v) => (v ? undefined : lista.cerrarDetalle())"
      @cerrar="lista.cerrarDetalle()"
    >
      <div v-if="lista.seleccionado" class="cajon">
        <p class="importe-grande num num-grande">
          {{ dinero(lista.seleccionado.signed_amount, { signoSiempre: true }) }}
        </p>
        <dl class="datos">
          <dt>Fecha</dt>
          <dd>{{ fechaCorta(lista.seleccionado.date) }}</dd>
          <dt>Cuenta</dt>
          <dd>{{ lista.seleccionado.account?.name ?? '—' }}</dd>
          <dt>Comercio</dt>
          <dd>{{ lista.seleccionado.payee?.name ?? '—' }}</dd>
          <dt>Temática</dt>
          <dd>
            <EtiquetaCategoria
              v-if="lista.seleccionado.category"
              :nombre="lista.seleccionado.category.name"
              :ranura="
                ranuraDeCategoria(
                  lista.seleccionado.category.color,
                  lista.seleccionado.category.id,
                )
              "
              tamanyo="sm"
            />
            <span v-else-if="lista.seleccionado.is_split">Repartido entre varias</span>
            <span v-else>Sin clasificar</span>
          </dd>
          <dt>Notas</dt>
          <dd>{{ lista.seleccionado.note || '—' }}</dd>
        </dl>
        <ul v-if="lista.seleccionado.splits.length > 0" class="splits">
          <li v-for="s in lista.seleccionado.splits" :key="s.id">
            <EtiquetaCategoria
              v-if="s.category"
              :nombre="s.category.name"
              :ranura="ranuraDeCategoria(s.category.color, s.category.id)"
              tamanyo="sm"
            />
            <span class="num">{{ dinero(s.amount) }}</span>
          </li>
        </ul>
      </div>

      <template #pie>
        <BotonBase
          v-if="lista.seleccionado"
          variante="peligro-fantasma"
          @click="pedirBorrado(lista.seleccionado)"
        >
          Eliminar
        </BotonBase>
        <BotonBase
          v-if="lista.seleccionado?.invoice_id"
          variante="secundaria"
          @click="
            router.push({ name: 'factura', params: { id: lista.seleccionado.invoice_id } })
          "
        >
          Ver factura
        </BotonBase>
      </template>
    </CajonLateral>

    <ModalMovimiento
      v-model:abierto="altaAbierta"
      :modo-inicial="modoAlta"
      @guardado="lista.cargar()"
    />

    <ModalBase
      v-model:abierto="borradoAbierto"
      titulo="¿Eliminar este movimiento?"
      tamanyo="sm"
      :guardando="lista.guardando"
      :error="lista.error ?? undefined"
      @cerrar="borradoAbierto = false"
    >
      <p class="parrafo">{{ textoBorrado }}</p>
      <template #pie>
        <BotonBase variante="contorno" @click="borradoAbierto = false">Cancelar</BotonBase>
        <BotonBase variante="peligro" :cargando="lista.guardando" @click="confirmarBorrado">
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
.parrafo {
  margin: 0;
  font-size: var(--t-body);
  line-height: var(--t-body-lh);
  color: var(--c-text-2);
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

.tenue {
  color: var(--c-text-3);
  font-size: var(--t-caption);
}
.positivo {
  color: var(--c-positive);
}

.detalle {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.detalle-titulo {
  margin: 0;
  font-size: var(--t-sm);
  font-weight: 600;
}
.splits {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  margin: 0;
  padding: 0;
  list-style: none;
}
.splits li {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.linea-meta {
  margin: 0;
  font-size: var(--t-caption);
  color: var(--c-text-2);
}

.rejilla-filtros {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--sp-3);
}
.interruptores {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin-top: var(--sp-4);
}

.cajon {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.importe-grande {
  margin: 0;
  font-size: var(--t-display);
  font-weight: 600;
}
.datos {
  display: grid;
  grid-template-columns: 8rem minmax(0, 1fr);
  gap: var(--sp-2) var(--sp-3);
  margin: 0;
  font-size: var(--t-sm);
}
.datos dt {
  color: var(--c-text-3);
}
.datos dd {
  margin: 0;
}
</style>
