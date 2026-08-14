<script setup lang="ts">
/**
 * Alta de una factura a mano: el ticket de papel, la compra sin PDF.
 *
 * Pide lo mínimo —quién, cuándo, cuánto y el concepto— y deja añadir una línea
 * por producto. Las líneas son opcionales, pero **sin ellas la factura no aporta
 * nada al seguimiento de precios**, y eso se dice en la pantalla en vez de
 * dejar que el usuario lo descubra al mirar el histórico y encontrarlo vacío.
 *
 * El total de cada línea no se teclea: se calcula al escribir cantidad y precio,
 * como hace el servidor (RN-41), y se enseña ya sumado para que se pueda
 * comparar con el total del papel antes de guardar.
 */
import { computed, ref, watch } from 'vue'
import { Plus, Trash2, TriangleAlert } from 'lucide-vue-next'

import { apiFacturas, type FacturaManualCrear, type LineaManualCrear } from '@/api/facturas'
import BotonBase from '@/components/ui/BotonBase.vue'
import CampoFecha from '@/components/ui/CampoFecha.vue'
import CampoImporte from '@/components/ui/CampoImporte.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import { useAvisos } from '@/composables/useAvisos'
import { dinero, parsearImporte, simboloDe } from '@/lib/formato'
import { useCategorias } from '@/stores/categorias'
import { mensajeDeError } from '@/stores/comun'
import { useCuentas } from '@/stores/cuentas'

/** Una línea mientras se teclea: el precio se guarda como texto para no perder decimales. */
interface LineaEnCurso {
  descripcion: string
  cantidad: string
  unidad: string
  precio: string
}

const props = defineProps<{ abierto: boolean }>()
const emit = defineEmits<{
  'update:abierto': [valor: boolean]
  /** Guardada: el padre recarga la lista y navega si quiere. */
  creada: [id: string]
}>()

const categorias = useCategorias()
const cuentas = useCuentas()
const avisos = useAvisos()

const emisor = ref('')
const numero = ref('')
const fecha = ref<string | null>(hoy())
const totalCentimos = ref<number | null>(null)
const concepto = ref('')
const cuentaId = ref<string>('')
const nota = ref('')
const lineas = ref<LineaEnCurso[]>([linea()])
const aceptarDescuadre = ref(false)

const guardando = ref(false)
const error = ref<string | null>(null)

function hoy(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function linea(): LineaEnCurso {
  return { descripcion: '', cantidad: '1', unidad: '', precio: '' }
}

// --- El concepto: temática que existe o nombre nuevo -------------------------

const tematicasDeGasto = computed(() =>
  categorias.activas.filter((c) => c.kind === 'expense').map((c) => c.name),
)

/** La temática que coincide con lo escrito, comparando como lo haría una persona. */
const tematicaElegida = computed(() => {
  const buscado = normalizar(concepto.value)
  if (!buscado) return null
  return (
    categorias.activas.find((c) => c.kind === 'expense' && normalizar(c.name) === buscado) ?? null
  )
})

const conceptoEsNuevo = computed(() => concepto.value.trim() !== '' && !tematicaElegida.value)

/** Las que empiezan por lo escrito, para sugerir sin obligar. */
const sugerencias = computed(() => {
  const buscado = normalizar(concepto.value)
  if (!buscado) return []
  return tematicasDeGasto.value
    .filter((nombre) => normalizar(nombre).includes(buscado) && normalizar(nombre) !== buscado)
    .slice(0, 5)
})

function normalizar(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .trim()
    .toLowerCase()
}

// --- Totales ----------------------------------------------------------------

const lineasConDatos = computed(() =>
  lineas.value.filter((l) => l.descripcion.trim() !== '' && parsearImporte(l.precio) !== null),
)

function totalDe(l: LineaEnCurso): number | null {
  const precio = parsearImporte(l.precio)
  if (precio === null) return null
  const cantidad = parsearImporte(l.cantidad) ?? 1
  return Math.round(precio * cantidad * 100) / 100
}

const sumaLineas = computed(() =>
  lineasConDatos.value.reduce((suma, l) => suma + (totalDe(l) ?? 0), 0),
)

const totalPapel = computed(() => (totalCentimos.value ?? 0) / 100)

/** Diferencia entre lo que suman las líneas y el total del papel. */
const descuadre = computed(() => {
  if (totalCentimos.value === null || lineasConDatos.value.length === 0) return 0
  return Math.round((sumaLineas.value - totalPapel.value) * 100) / 100
})

const hayDescuadre = computed(() => Math.abs(descuadre.value) >= 0.01)

const puedeGuardar = computed(
  () =>
    emisor.value.trim() !== '' &&
    fecha.value !== null &&
    (totalCentimos.value ?? 0) > 0 &&
    concepto.value.trim() !== '' &&
    (!hayDescuadre.value || aceptarDescuadre.value),
)

// --- Guardar ----------------------------------------------------------------

async function guardar(): Promise<void> {
  if (!puedeGuardar.value) return
  guardando.value = true
  error.value = null
  const cuerpo: FacturaManualCrear = {
    issuer: emisor.value.trim(),
    number: numero.value.trim() || null,
    date: fecha.value as string,
    total: totalPapel.value.toFixed(2),
    note: nota.value.trim() || null,
    allow_total_mismatch: aceptarDescuadre.value,
    lines: lineasConDatos.value.map(
      (l): LineaManualCrear => ({
        description: l.descripcion.trim(),
        quantity: (parsearImporte(l.cantidad) ?? 1).toString(),
        unit: l.unidad.trim() || null,
        // El precio va tal cual se escribió, con sus decimales: el kWh a 0,1489
        // los pierde si se redondea a céntimos.
        unit_price: (parsearImporte(l.precio) as number).toString(),
      }),
    ),
  }
  // Una de las dos formas, nunca las dos: el servidor lo rechaza.
  if (tematicaElegida.value) cuerpo.category_id = tematicaElegida.value.id
  else cuerpo.category_name = concepto.value.trim()
  if (cuentaId.value) cuerpo.account_id = cuentaId.value

  try {
    const creada = await apiFacturas.crearAMano(cuerpo)
    avisos.exito(
      cuentaId.value
        ? `Factura de ${emisor.value.trim()} guardada y anotada como gasto.`
        : `Factura de ${emisor.value.trim()} guardada. Revísala cuando quieras.`,
    )
    if (conceptoEsNuevo.value) void categorias.cargar(undefined, true)
    emit('creada', creada.id)
    cerrar()
  } catch (e) {
    error.value = mensajeDeError(e, 'No se ha podido guardar la factura.')
  } finally {
    guardando.value = false
  }
}

function cerrar(): void {
  emit('update:abierto', false)
}

function reiniciar(): void {
  emisor.value = ''
  numero.value = ''
  fecha.value = hoy()
  totalCentimos.value = null
  concepto.value = ''
  cuentaId.value = ''
  nota.value = ''
  lineas.value = [linea()]
  aceptarDescuadre.value = false
  error.value = null
}

watch(
  () => props.abierto,
  (abierto) => {
    if (!abierto) return
    reiniciar()
    if (!categorias.cargado) void categorias.cargar()
    if (!cuentas.cargado) void cuentas.cargar()
  },
)
</script>

<template>
  <ModalBase
    :abierto="abierto"
    titulo="Añadir una factura a mano"
    subtitulo="Para el ticket de papel o la compra de la que no tienes PDF"
    tamanyo="xl"
    :guardando="guardando"
    :error="error ?? undefined"
    @update:abierto="emit('update:abierto', $event)"
  >
    <div class="formulario">
      <div class="rejilla">
        <CampoTexto
          v-model="emisor"
          etiqueta="Emisor"
          ayuda="La tienda o la empresa que la emitió"
          requerido
        />
        <CampoTexto v-model="numero" etiqueta="Nº de factura" ayuda="Opcional" />
        <CampoFecha v-model="fecha" etiqueta="Fecha" requerido />
        <CampoImporte v-model="totalCentimos" etiqueta="Total de la factura" requerido />
      </div>

      <div class="concepto">
        <CampoTexto
          v-model="concepto"
          etiqueta="Concepto"
          :ayuda="
            conceptoEsNuevo
              ? `Se creará la temática «${concepto.trim()}»`
              : 'La temática a la que va este gasto'
          "
          requerido
        />
        <p v-if="sugerencias.length" class="sugerencias">
          <span class="etiqueta-sugerencias">¿Querías decir?</span>
          <BotonBase
            v-for="nombre in sugerencias"
            :key="nombre"
            variante="enlace"
            @click="concepto = nombre"
          >
            {{ nombre }}
          </BotonBase>
        </p>
      </div>

      <section class="lineas" aria-labelledby="titulo-lineas">
        <div class="cabecera-lineas">
          <h3 id="titulo-lineas">Productos</h3>
          <p class="pista">
            Opcional, pero es lo que permite seguir si un producto sube de precio.
          </p>
        </div>

        <div v-for="(l, indice) in lineas" :key="indice" class="fila-linea">
          <CampoTexto
            v-model="l.descripcion"
            etiqueta="Producto"
            :etiqueta-oculta="indice > 0"
            class="col-descripcion"
          />
          <CampoTexto
            v-model="l.cantidad"
            etiqueta="Cant."
            :etiqueta-oculta="indice > 0"
            class="col-corta"
          />
          <CampoTexto
            v-model="l.unidad"
            etiqueta="Unidad"
            :etiqueta-oculta="indice > 0"
            class="col-corta"
          />
          <CampoTexto
            v-model="l.precio"
            :etiqueta="`Precio (${simboloDe()})`"
            :etiqueta-oculta="indice > 0"
            class="col-corta"
          />
          <p class="total-linea" :class="{ vacio: totalDe(l) === null }">
            {{ totalDe(l) === null ? '—' : dinero(totalDe(l)) }}
          </p>
          <BotonBase
            variante="fantasma"
            :aria-label="`Quitar la línea ${indice + 1}`"
            :deshabilitado="lineas.length === 1"
            @click="lineas.splice(indice, 1)"
          >
            <Trash2 :size="16" aria-hidden="true" />
          </BotonBase>
        </div>

        <BotonBase variante="secundaria" @click="lineas.push(linea())">
          <Plus :size="16" aria-hidden="true" />
          Añadir producto
        </BotonBase>

        <p v-if="lineasConDatos.length" class="suma">
          Las líneas suman <strong>{{ dinero(sumaLineas) }}</strong>
        </p>
      </section>

      <div v-if="hayDescuadre" class="descuadre" role="alert">
        <TriangleAlert :size="18" aria-hidden="true" />
        <div>
          <p>
            Las líneas suman {{ dinero(sumaLineas) }} y el total es
            {{ dinero(totalPapel) }}:
            {{ descuadre > 0 ? 'sobran' : 'faltan' }} {{ dinero(Math.abs(descuadre)) }}.
          </p>
          <p class="pista">
            Si la factura lleva impuestos es normal, porque las líneas suman la base.
          </p>
          <InterruptorBase v-model="aceptarDescuadre" etiqueta="Guardar así, es correcto" />
        </div>
      </div>

      <div class="rejilla">
        <SelectorBase
          v-model="cuentaId"
          etiqueta="Anotar el gasto en"
          ayuda="Si eliges cuenta, se guarda y se anota el gasto de una vez"
          :opciones="[{ valor: '', etiqueta: 'Solo guardar la factura' }, ...cuentas.opciones]"
        />
        <CampoTexto v-model="nota" etiqueta="Nota" ayuda="Opcional" />
      </div>
    </div>

    <template #pie>
      <BotonBase variante="secundaria" :deshabilitado="guardando" @click="cerrar">
        Cancelar
      </BotonBase>
      <BotonBase
        variante="primaria"
        :deshabilitado="!puedeGuardar"
        :cargando="guardando"
        @click="guardar"
      >
        {{ cuentaId ? 'Guardar y anotar el gasto' : 'Guardar factura' }}
      </BotonBase>
    </template>
  </ModalBase>
</template>

<style scoped>
.formulario {
  display: flex;
  flex-direction: column;
  gap: var(--e-5);
}

.rejilla {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
  gap: var(--e-4);
}

.concepto {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.sugerencias {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--e-3);
  margin: 0;
  font-size: var(--t-sm);
}

.etiqueta-sugerencias {
  color: var(--c-texto-suave);
}

.lineas {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding-top: var(--e-4);
  border-top: 1px solid var(--c-borde);
}

.cabecera-lineas h3 {
  margin: 0;
  font-size: var(--t-md);
}

.pista {
  margin: var(--e-1) 0 0;
  font-size: var(--t-sm);
  color: var(--c-texto-suave);
}

.fila-linea {
  display: grid;
  grid-template-columns: minmax(8rem, 1fr) 5rem 5rem 6rem 6rem auto;
  align-items: end;
  gap: var(--e-2);
}

.total-linea {
  margin: 0 0 var(--e-2);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.total-linea.vacio {
  color: var(--c-texto-suave);
}

.suma {
  margin: 0;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.descuadre {
  display: flex;
  gap: var(--e-3);
  padding: var(--e-4);
  border: 1px solid var(--c-aviso-borde, var(--c-borde));
  border-radius: var(--r-md);
  background: var(--c-aviso-fondo, transparent);
}

.descuadre p {
  margin: 0;
}

@media (width < 40rem) {
  .fila-linea {
    grid-template-columns: 1fr 1fr;
  }

  .col-descripcion {
    grid-column: 1 / -1;
  }
}
</style>
