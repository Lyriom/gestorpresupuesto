<script setup lang="ts">
/**
 * Alta de movimiento en dos modos (§2.5 de la especificación).
 *
 * - `rapido`: tres toques y una cifra. Foco en el importe, rejilla de las
 *   temáticas más usadas, cuenta y fecha precargadas.
 * - `completo`: el mismo formulario más el reparto entre varias temáticas, con
 *   su contador «Repartido: X de Y» y el guardado bloqueado hasta que cuadre.
 *
 * El importe se maneja en céntimos porque es lo que pide `CampoImporte`, y se
 * convierte a cadena decimal al enviar, que es lo que pide el contrato (§1.7).
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowUpRight, Plus, X } from 'lucide-vue-next'

import { importeDeCentimos } from '@/api/comun'
import type { MovimientoCrear, SplitCrear, TipoMovimiento } from '@/api/movimientos'
import { apiMovimientos } from '@/api/movimientos'
import BotonBase from '@/components/ui/BotonBase.vue'
import CampoFecha from '@/components/ui/CampoFecha.vue'
import CampoImporte from '@/components/ui/CampoImporte.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import EtiquetaCategoria from '@/components/ui/EtiquetaCategoria.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import { useAvisos } from '@/composables/useAvisos'
import { euros, porcentaje } from '@/lib/formato'
import { ranuraDeCategoria, useCategorias } from '@/stores/categorias'
import { useCuentas } from '@/stores/cuentas'
import { erroresPorCampo, mensajeDeError } from '@/stores/comun'

const props = withDefaults(
  defineProps<{
    abierto: boolean
    /** Temática preseleccionada, p. ej. al venir de un segmento de la barra. */
    categoriaInicial?: string | null
    modoInicial?: 'rapido' | 'completo'
  }>(),
  { categoriaInicial: null, modoInicial: 'rapido' },
)

const emit = defineEmits<{
  'update:abierto': [valor: boolean]
  /** Se ha creado algo: quien escuche recarga lo que le toque. */
  guardado: []
}>()

const categorias = useCategorias()
const cuentas = useCuentas()
const avisos = useAvisos()

const campoImporte = ref<{ enfocar: () => void } | null>(null)

const modo = ref<'rapido' | 'completo'>(props.modoInicial)
const tipo = ref<TipoMovimiento>('expense')
const centimos = ref<number | null>(null)
const categoriaId = ref<string | number | null>(props.categoriaInicial)
const cuentaId = ref<string | number | null>(null)
const cuentaDestinoId = ref<string | number | null>(null)
const fecha = ref<string | null>(new Date().toISOString().slice(0, 10))
const concepto = ref('')
const nota = ref('')
const verTodas = ref(false)
const guardando = ref(false)
const errorGeneral = ref<string | null>(null)
const errorImporte = ref<string | null>(null)
const errorTematica = ref<string | null>(null)

interface LineaReparto {
  clave: number
  categoriaId: string | number | null
  centimos: number | null
}

let contador = 0
const reparto = ref<LineaReparto[]>([])

const TIPOS: Array<{ valor: TipoMovimiento; etiqueta: string }> = [
  { valor: 'expense', etiqueta: 'Gasto' },
  { valor: 'income', etiqueta: 'Ingreso' },
  { valor: 'transfer', etiqueta: 'Transferencia' },
]

const esTransferencia = computed(() => tipo.value === 'transfer')

const opcionesTematica = computed(() =>
  categorias.opciones(tipo.value === 'income' ? 'income' : 'expense'),
)

/**
 * Rejilla de acceso rápido: las temáticas de primer nivel, en el orden que el
 * usuario les dio en el árbol. No hay contador de uso en el árbol cacheado, así
 * que el orden propio es la mejor aproximación disponible sin otra llamada.
 */
const rejilla = computed(() =>
  categorias.arbol
    .filter((c) => !c.is_archived && c.kind === (tipo.value === 'income' ? 'income' : 'expense'))
    .slice(0, 6),
)

const totalCentimos = computed(() => centimos.value ?? 0)
const repartidoCentimos = computed(() =>
  reparto.value.reduce((suma, l) => suma + (l.centimos ?? 0), 0),
)
const restanteCentimos = computed(() => totalCentimos.value - repartidoCentimos.value)
const repartoCuadra = computed(
  () => reparto.value.length > 0 && restanteCentimos.value === 0 && totalCentimos.value > 0,
)

const mensajeReparto = computed(() => {
  if (reparto.value.length === 0) return null
  if (repartoCuadra.value) {
    return `Repartido: ${euros(repartidoCentimos.value / 100)} de ${euros(totalCentimos.value / 100)} · cuadra`
  }
  if (restanteCentimos.value > 0) {
    return `El reparto no suma el importe total. Faltan ${euros(restanteCentimos.value / 100)}.`
  }
  return `El reparto supera el importe total. Sobran ${euros(-restanteCentimos.value / 100)}.`
})

function porcentajeDeLinea(linea: LineaReparto): string {
  if (totalCentimos.value <= 0 || !linea.centimos) return '—'
  return porcentaje(linea.centimos / totalCentimos.value)
}

const puedeGuardar = computed(() => {
  if (totalCentimos.value <= 0) return false
  if (esTransferencia.value) {
    return !!cuentaId.value && !!cuentaDestinoId.value && cuentaId.value !== cuentaDestinoId.value
  }
  if (!cuentaId.value) return false
  if (modo.value === 'completo' && reparto.value.length > 0) return repartoCuadra.value
  return !!categoriaId.value
})

const titulo = computed(() => (modo.value === 'rapido' ? 'Añadir gasto' : 'Nuevo movimiento'))

const hayCambios = computed(
  () => totalCentimos.value > 0 || concepto.value.length > 0 || reparto.value.length > 0,
)

function reiniciar(conservarCuentaYFecha = true): void {
  centimos.value = null
  concepto.value = ''
  nota.value = ''
  reparto.value = []
  errorGeneral.value = null
  errorImporte.value = null
  errorTematica.value = null
  if (!conservarCuentaYFecha) {
    cuentaId.value = null
    fecha.value = new Date().toISOString().slice(0, 10)
  }
}

/**
 * Cerrar con datos a medias pregunta antes de tirarlos (§4). `ModalBase` avisa
 * con `descartar`; aquí se decide, que es lo que pide el contrato del modal.
 */
const descarteAbierto = ref(false)

function cerrar(): void {
  descarteAbierto.value = false
  emit('update:abierto', false)
}

function anyadirLinea(): void {
  contador += 1
  reparto.value = [
    ...reparto.value,
    { clave: contador, categoriaId: null, centimos: restanteCentimos.value || null },
  ]
}

function quitarLinea(clave: number): void {
  reparto.value = reparto.value.filter((l) => l.clave !== clave)
}

function pasarACompleto(): void {
  modo.value = 'completo'
  if (reparto.value.length === 0) {
    contador += 1
    reparto.value = [
      { clave: contador, categoriaId: categoriaId.value, centimos: centimos.value },
    ]
    anyadirLinea()
  }
}

async function guardar(yOtro = false): Promise<void> {
  errorGeneral.value = null
  errorImporte.value = null
  errorTematica.value = null

  if (totalCentimos.value <= 0) {
    errorImporte.value = 'Introduce un importe mayor que 0.'
    campoImporte.value?.enfocar()
    return
  }
  if (!esTransferencia.value && modo.value === 'rapido' && !categoriaId.value) {
    errorTematica.value = 'Este campo es obligatorio.'
    return
  }

  const importe = importeDeCentimos(totalCentimos.value)
  if (!importe || !fecha.value) return

  guardando.value = true
  try {
    if (esTransferencia.value) {
      await apiMovimientos.crearTransferencia({
        from_account_id: String(cuentaId.value),
        to_account_id: String(cuentaDestinoId.value),
        date: fecha.value,
        amount: importe,
        description: concepto.value || null,
        note: nota.value || null,
      })
    } else {
      const splits: SplitCrear[] = reparto.value
        .filter((l) => l.categoriaId && l.centimos)
        .map((l) => ({
          category_id: String(l.categoriaId),
          amount: importeDeCentimos(l.centimos) as string,
        }))
      const cuerpo: MovimientoCrear = {
        kind: tipo.value === 'income' ? 'income' : 'expense',
        account_id: String(cuentaId.value),
        date: fecha.value,
        amount: importe,
        description: concepto.value || null,
        note: nota.value || null,
        ...(splits.length > 0
          ? { splits }
          : { category_id: categoriaId.value ? String(categoriaId.value) : null }),
      }
      await apiMovimientos.crear(cuerpo)
    }
    avisos.exito(tipo.value === 'income' ? 'Ingreso guardado.' : 'Gasto guardado.')
    emit('guardado')
    if (yOtro) reiniciar()
    else {
      reiniciar()
      cerrar()
    }
  } catch (e) {
    // Un 422 trae `detalles[]` con `campo` y `mensaje`: cada uno va a su control
    // y solo lo que no encaje en ninguno se queda en la banda general (§7).
    const campos = erroresPorCampo(e)
    errorImporte.value = campos.amount ?? null
    errorTematica.value = campos.category_id ?? campos.splits ?? null
    const colocados = new Set(['amount', 'category_id', 'splits'])
    const sobrantes = Object.keys(campos).filter((c) => !colocados.has(c))
    if (sobrantes.length > 0 || Object.keys(campos).length === 0) {
      errorGeneral.value = mensajeDeError(e, 'No se ha podido guardar el movimiento.')
    }
    if (errorImporte.value) campoImporte.value?.enfocar()
  } finally {
    guardando.value = false
  }
}

watch(
  () => props.abierto,
  (abierto) => {
    if (!abierto) return
    modo.value = props.modoInicial
    categoriaId.value = props.categoriaInicial
    reiniciar()
    void categorias.cargar()
    void cuentas.cargar()
    // La última cuenta usada no está en el contrato: se toma la primera activa.
    if (!cuentaId.value) cuentaId.value = cuentas.activas[0]?.id ?? null
    // El flujo de 10 segundos empieza tecleando la cifra, así que el foco va al
    // importe y no al primer control del modal, que es el tipo de movimiento.
    void nextTick(() => campoImporte.value?.enfocar())
  },
)

watch(
  () => cuentas.activas.length,
  () => {
    if (!cuentaId.value) cuentaId.value = cuentas.activas[0]?.id ?? null
  },
)
</script>

<template>
  <ModalBase
    :abierto="abierto"
    :titulo="titulo"
    :tamanyo="modo === 'completo' ? 'lg' : 'md'"
    :guardando="guardando"
    :error="errorGeneral ?? undefined"
    :cambios-sin-guardar="hayCambios"
    @update:abierto="emit('update:abierto', $event)"
    @cerrar="cerrar"
    @descartar="descarteAbierto = true"
  >
    <div class="cuerpo">
      <fieldset class="tipos">
        <legend class="oculto">Tipo de movimiento</legend>
        <label v-for="t in TIPOS" :key="t.valor" class="tipo">
          <input v-model="tipo" type="radio" name="tipo-movimiento" :value="t.valor" />
          <span>{{ t.etiqueta }}</span>
        </label>
      </fieldset>

      <CampoImporte
        ref="campoImporte"
        v-model="centimos"
        :etiqueta="modo === 'rapido' ? 'Importe' : 'Importe total'"
        :tamanyo="modo === 'rapido' ? 'display' : 'cuerpo'"
        :teclas-rapidas="modo === 'rapido'"
        :error="errorImporte ?? undefined"
        requerido
      />

      <template v-if="!esTransferencia">
        <div v-if="modo === 'rapido'" class="bloque">
          <p class="rotulo">Temática</p>
          <div class="rejilla-tematicas">
            <EtiquetaCategoria
              v-for="c in rejilla"
              :key="c.id"
              :nombre="c.name"
              :ranura="ranuraDeCategoria(c.color, c.id)"
              seleccionable
              :seleccionada="categoriaId === c.id"
              @alternar="categoriaId = categoriaId === c.id ? null : c.id"
            />
            <BotonBase variante="enlace" tamanyo="sm" @click="verTodas = !verTodas">
              {{ verTodas ? 'Ocultar la lista' : 'Ver todas' }}
            </BotonBase>
          </div>
          <SelectorBase
            v-if="verTodas || (!!categoriaId && !rejilla.some((c) => c.id === categoriaId))"
            v-model="categoriaId"
            etiqueta="Temática"
            etiqueta-oculta
            placeholder="Busca una temática"
            :opciones="opcionesTematica"
            :cargando="categorias.cargando"
            :error="errorTematica ?? undefined"
          />
          <p v-else-if="errorTematica" class="error-inline" role="alert">{{ errorTematica }}</p>
        </div>

        <div v-else class="bloque">
          <p class="rotulo">Reparto entre temáticas</p>
          <ul class="lineas">
            <li v-for="linea in reparto" :key="linea.clave" class="linea">
              <SelectorBase
                v-model="linea.categoriaId"
                etiqueta="Temática"
                etiqueta-oculta
                placeholder="Elige una temática"
                :opciones="opcionesTematica"
              />
              <CampoImporte v-model="linea.centimos" etiqueta="Importe" etiqueta-oculta />
              <span class="pct num">{{ porcentajeDeLinea(linea) }}</span>
              <BotonBase
                variante="fantasma"
                tamanyo="sm"
                solo-icono
                :icono="X"
                etiqueta-accesible="Quitar esta línea del reparto"
                @click="quitarLinea(linea.clave)"
              />
            </li>
          </ul>
          <BotonBase variante="fantasma" tamanyo="sm" :icono="Plus" @click="anyadirLinea">
            Añadir otra temática
          </BotonBase>
          <p
            v-if="mensajeReparto"
            class="reparto-total num"
            :class="{ mal: !repartoCuadra }"
            role="status"
          >
            {{ mensajeReparto }}
          </p>
        </div>
      </template>

      <div class="fila">
        <SelectorBase
          v-model="cuentaId"
          :etiqueta="esTransferencia ? 'Cuenta de origen' : 'Cuenta'"
          placeholder="Elige una cuenta"
          :opciones="cuentas.opciones"
          :cargando="cuentas.cargando"
          requerido
        />
        <SelectorBase
          v-if="esTransferencia"
          v-model="cuentaDestinoId"
          etiqueta="Cuenta de destino"
          placeholder="Elige una cuenta"
          :opciones="cuentas.opciones"
          requerido
        />
        <CampoFecha v-model="fecha" etiqueta="Fecha" requerido />
      </div>

      <CampoTexto
        v-model="concepto"
        etiqueta="Concepto"
        :placeholder="modo === 'rapido' ? 'Mercadona' : 'Compra semanal'"
        :ayuda="modo === 'rapido' ? 'Opcional' : undefined"
      />

      <CampoTexto v-if="modo === 'completo'" v-model="nota" etiqueta="Notas" />

      <BotonBase
        v-if="modo === 'rapido' && !esTransferencia"
        variante="enlace"
        :icono-final="ArrowUpRight"
        @click="pasarACompleto"
      >
        Repartir entre varias temáticas
      </BotonBase>
    </div>

    <template #pie>
      <BotonBase v-if="modo === 'completo'" variante="contorno" @click="cerrar">Cancelar</BotonBase>
      <BotonBase
        v-else
        variante="contorno"
        :deshabilitado="!puedeGuardar || guardando"
        @click="guardar(true)"
      >
        Guardar y añadir otro
      </BotonBase>
      <BotonBase
        variante="primaria"
        :cargando="guardando"
        :deshabilitado="!puedeGuardar"
        @click="guardar(false)"
      >
        Guardar
      </BotonBase>
    </template>
  </ModalBase>

  <ModalBase
    v-model:abierto="descarteAbierto"
    titulo="Tienes cambios sin guardar"
    tamanyo="sm"
    @cerrar="descarteAbierto = false"
  >
    <p class="parrafo">¿Quieres descartarlos?</p>
    <template #pie>
      <BotonBase variante="contorno" @click="descarteAbierto = false">Seguir editando</BotonBase>
      <BotonBase variante="peligro" @click="cerrar">Descartar</BotonBase>
    </template>
  </ModalBase>
</template>

<style scoped>
.cuerpo {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.tipos {
  display: flex;
  gap: var(--sp-1);
  margin: 0;
  padding: 2px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-full);
  background-color: var(--c-surface-2);
}
.tipo {
  flex: 1 1 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  border-radius: var(--r-full);
  color: var(--c-text-2);
  font-size: var(--t-sm);
  cursor: pointer;
}
.tipo:has(input:checked) {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
  font-weight: 600;
}
.tipo:has(input:focus-visible) {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}
.tipo input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}

.bloque {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.rotulo {
  margin: 0;
  font-size: var(--t-sm);
  font-weight: 600;
  color: var(--c-text-2);
}

.rejilla-tematicas {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
}

.lineas {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.linea {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) 4rem auto;
  align-items: end;
  gap: var(--sp-2);
}
.pct {
  padding-bottom: var(--sp-2);
  text-align: right;
  color: var(--c-text-3);
  font-size: var(--t-caption);
}

.reparto-total {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-positive);
}
.reparto-total.mal {
  color: var(--c-negative);
  font-weight: 600;
}

.fila {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--sp-3);
}

.error-inline {
  margin: 0;
  color: var(--c-negative);
  font-size: var(--t-caption);
}

.parrafo {
  margin: 0;
  font-size: var(--t-body);
  line-height: var(--t-body-lh);
  color: var(--c-text-2);
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

@media (max-width: 639px) {
  .linea {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas: 'tematica quitar' 'importe pct';
  }
}
</style>
