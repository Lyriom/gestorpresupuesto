<script setup lang="ts">
/**
 * Subida de factura: procesando (§2.8) y **revisión de líneas** (§2.9).
 *
 * Es la pantalla más importante del módulo. La lectura automática no es fiable
 * al 100 %, así que aquí todo es editable y la interfaz dice **qué revisar**:
 *
 * - Confianza alta (≥ 85 %): fila con `✓`, sin realce.
 * - Media (60–84 %): también `✓`, pero se puede repasar.
 * - Baja (< 60 %): `⚠`, fondo de aviso y una segunda línea explicando qué dudó
 *   el sistema. El número de confianza acompaña siempre al color y al icono.
 *
 * Lo único que bloquea el guardado es que falte una temática; el descuadre del
 * total es informativo y se confirma con `allow_total_mismatch`.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Check,
  CircleAlert,
  LoaderCircle,
  Plus,
  TriangleAlert,
  X,
} from 'lucide-vue-next'

import { centimosDeImporte, importeDeCentimos } from '@/api/comun'
import { ETIQUETA_CONFIANZA, ETIQUETA_METODO, tonoConfianza } from '@/api/facturas'
import BotonBase from '@/components/ui/BotonBase.vue'
import CampoFecha from '@/components/ui/CampoFecha.vue'
import CampoImporte from '@/components/ui/CampoImporte.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import IndicadorProgreso from '@/components/ui/IndicadorProgreso.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import { useAvisos } from '@/composables/useAvisos'
import { dinero, porcentaje, precioUnitario , simboloDe } from '@/lib/formato'
import { useCategorias } from '@/stores/categorias'
import { useCuentas } from '@/stores/cuentas'
import { motivoDeRevision, useFacturas, type LineaBorrador } from '@/stores/facturas'
import BloqueError from './componentes/BloqueError.vue'

const UNIDADES = ['ud', 'kg', 'g', 'l', 'ml', 'kWh', 'm³', 'h'].map((u) => ({
  valor: u,
  etiqueta: u,
}))

const route = useRoute()
const router = useRouter()
const facturas = useFacturas()
const categorias = useCategorias()
const cuentas = useCuentas()
const avisos = useAvisos()

const id = computed(() => String(route.params.id))

// Cabecera editable, en céntimos donde toca.
const emisor = ref('')
const nif = ref('')
const numero = ref('')
const fecha = ref<string | null>(null)
const baseCentimos = ref<number | null>(null)
const impuestosCentimos = ref<number | null>(null)
const totalCentimos = ref<number | null>(null)
const cuentaId = ref<string | number | null>(null)

const enviando = ref(false)
/** Cuál de los dos botones del pie está en curso, para el spinner correcto. */
const enCurso = ref<'borrador' | 'factura' | null>(null)
const claveConFoco = ref<string | null>(null)
/** Los errores de «línea sin temática» solo se pintan tras intentar guardar. */
const intentadoGuardar = ref(false)

const factura = computed(() => facturas.factura)

const pasos = computed(() => {
  const progreso = facturas.estado?.progress ?? 0
  const fallo = facturas.fallida
  return [
    { texto: 'Subido', estado: 'hecho' as const },
    {
      texto: 'Leyendo el documento',
      estado: progreso >= 40 ? 'hecho' : fallo ? 'fallo' : 'curso',
    },
    {
      texto: 'Extrayendo líneas…',
      estado: progreso >= 75 ? 'hecho' : progreso >= 40 ? (fallo ? 'fallo' : 'curso') : 'pendiente',
    },
    {
      texto: 'Comprobando importes',
      estado: progreso >= 100 ? 'hecho' : progreso >= 75 ? 'curso' : 'pendiente',
    },
  ]
})

function faltaTematica(linea: LineaBorrador): boolean {
  return intentadoGuardar.value && !linea.is_excluded && !linea.category_id
}

function editar(linea: LineaBorrador, cambios: Partial<LineaBorrador>): void {
  facturas.editarLinea(linea.clave, cambios)
}

function editarTotal(linea: LineaBorrador, centimos: number | null): void {
  editar(linea, { total: importeDeCentimos(centimos) ?? '0.00' })
}

function volcarCabecera(): void {
  const f = factura.value
  if (!f) return
  emisor.value = f.issuer ?? ''
  nif.value = f.issuer_tax_id ?? ''
  numero.value = f.number ?? ''
  fecha.value = f.date ?? null
  baseCentimos.value = centimosDeImporte(f.taxable_base)
  impuestosCentimos.value = centimosDeImporte(f.tax_amount)
  totalCentimos.value = centimosDeImporte(f.total)
  cuentaId.value = f.account_id ?? cuentas.activas[0]?.id ?? null
}

async function guardarCabecera(): Promise<void> {
  await facturas.guardarCabecera({
    issuer: emisor.value || null,
    issuer_tax_id: nif.value || null,
    number: numero.value || null,
    date: fecha.value,
    taxable_base: importeDeCentimos(baseCentimos.value),
    tax_amount: importeDeCentimos(impuestosCentimos.value),
    total: importeDeCentimos(totalCentimos.value),
    account_id: cuentaId.value ? String(cuentaId.value) : null,
  })
}

async function guardarBorrador(): Promise<void> {
  enviando.value = true
  enCurso.value = 'borrador'
  await guardarCabecera()
  const ok = await facturas.guardarBorrador()
  enviando.value = false
  enCurso.value = null
  if (ok) {
    avisos.exito('Revisión guardada. La factura queda pendiente de revisar.')
    void router.push({ name: 'facturas' })
  }
}

async function guardarFactura(): Promise<void> {
  intentadoGuardar.value = true
  const pendiente = facturas.lineasSinTematica[0]
  if (pendiente) {
    claveConFoco.value = pendiente.clave
    await nextTick()
    document.getElementById(`tematica-${pendiente.clave}`)?.scrollIntoView({ block: 'center' })
    return
  }
  if (!cuentaId.value) {
    avisos.aviso('Elige la cuenta con la que se pagó la factura.')
    return
  }
  enviando.value = true
  enCurso.value = 'factura'
  await guardarCabecera()
  const resultado = await facturas.confirmar({
    account_id: String(cuentaId.value),
    allow_total_mismatch: true,
  })
  enviando.value = false
  enCurso.value = null
  if (!resultado) {
    avisos.error('No se ha podido guardar la factura.', {
      accion: { etiqueta: 'Reintentar', alPulsar: () => void guardarFactura() },
    })
    return
  }
  const n = resultado.splits_created || 1
  avisos.exito(`Factura guardada. Se ha creado ${n === 1 ? '1 movimiento' : `${n} movimientos`}.`)
  void router.push({ name: 'factura', params: { id: id.value } })
}

function cancelar(): void {
  void router.push({ name: 'facturas' })
}

async function cargar(): Promise<void> {
  await facturas.cargarFactura(id.value)
  const estado = factura.value?.status
  if (estado === 'pending_review' || estado === 'failed' || estado === 'confirmed') {
    await facturas.cargarRevision(id.value)
  }
  volcarCabecera()
}

onMounted(() => {
  void categorias.cargar()
  void cuentas.cargar()
  void cargar()
})

// El sondeo del procesado carga la cabecera por su cuenta cuando termina, así
// que los campos se rellenan al cambiar de estado y no solo al montar.
watch(
  () => `${factura.value?.id ?? ''}|${factura.value?.status ?? ''}`,
  () => volcarCabecera(),
)

onBeforeUnmount(() => facturas.detenerSondeo())
</script>

<template>
  <div class="vista">
    <nav class="miga" aria-label="Migas de pan">
      <BotonBase variante="enlace" tamanyo="sm" @click="cancelar">Facturas</BotonBase>
      <span aria-hidden="true">›</span>
      <span>{{ facturas.procesando ? 'Procesando' : 'Revisar' }}</span>
    </nav>

    <BloqueError
      v-if="facturas.errorFactura && !factura"
      titulo="No se ha podido cargar esta factura"
      :nivel="2"
      @reintentar="cargar"
    />

    <div v-else-if="facturas.cargandoFactura && !factura" class="tarjeta caja">
      <EsqueletoCarga variante="bloque" alto="120px" anuncio="Cargando la factura" />
    </div>

    <!-- §2.8 Procesando -->
    <section v-else-if="facturas.procesando" class="tarjeta procesando">
      <p class="nombre-fichero">
        {{ factura?.filename }} ·
        {{ Math.round((factura?.size_bytes ?? 0) / 1024) }} KB
      </p>

      <IndicadorProgreso
        etiqueta="Progreso de la lectura"
        :valor="facturas.estado?.progress ?? 0"
        :estado="pasos.find((p) => p.estado === 'curso')?.texto"
        mostrar-texto
      />

      <ul class="pasos">
        <li v-for="p in pasos" :key="p.texto" :class="`paso--${p.estado}`">
          <Check v-if="p.estado === 'hecho'" :size="16" aria-hidden="true" />
          <LoaderCircle v-else-if="p.estado === 'curso'" :size="16" class="girando" aria-hidden="true" />
          <X v-else-if="p.estado === 'fallo'" :size="16" aria-hidden="true" />
          <span v-else class="circulo" aria-hidden="true" />
          {{ p.texto }}
        </li>
      </ul>

      <p class="nota">Suele tardar menos de 20 segundos.</p>
      <BotonBase variante="contorno" @click="cancelar">Cancelar</BotonBase>
    </section>

    <!-- §2.9 Revisión -->
    <template v-else-if="factura">
      <div v-if="facturas.fallida" class="banda banda--error" role="alert">
        No se ha podido leer el documento{{ factura.error ? `: ${factura.error}` : '' }}. Puedes
        meter los datos a mano sobre esta misma factura.
        <BotonBase variante="secundaria" tamanyo="sm" @click="facturas.anyadirLineaEnBorrador()">
          Añadir línea manual
        </BotonBase>
      </div>

      <div v-if="!facturas.cuadra && facturas.borrador.length > 0" class="banda banda--aviso">
        <TriangleAlert :size="16" aria-hidden="true" />
        El total no coincide con la suma de las líneas. Diferencia de
        {{ dinero(Math.abs(facturas.diferencia)) }}.
      </div>
      <div v-if="facturas.lineasDeConfianzaBaja.length > 0" class="banda banda--aviso">
        <TriangleAlert :size="16" aria-hidden="true" />
        {{ facturas.lineasDeConfianzaBaja.length }}
        {{ facturas.lineasDeConfianzaBaja.length === 1 ? 'línea tiene' : 'líneas tienen' }}
        confianza baja y conviene revisarlas.
      </div>
      <div
        v-for="(aviso, i) in factura.warnings"
        :key="`w-${i}`"
        class="banda banda--aviso"
      >
        <CircleAlert :size="16" aria-hidden="true" />
        {{ aviso }}
      </div>

      <!-- Cabecera editable -->
      <section class="tarjeta caja" aria-labelledby="titulo-cabecera">
        <h1 id="titulo-cabecera" class="titulo">Revisar la factura</h1>
        <div class="rejilla-cabecera">
          <CampoTexto v-model="emisor" etiqueta="Emisor" placeholder="Mercadona, S.A." />
          <CampoTexto v-model="nif" etiqueta="NIF" monoespaciado placeholder="A46103834" />
          <CampoTexto v-model="numero" etiqueta="Número" monoespaciado />
          <CampoFecha v-model="fecha" etiqueta="Fecha" />
          <CampoImporte v-model="baseCentimos" etiqueta="Base imponible" />
          <CampoImporte v-model="impuestosCentimos" etiqueta="Impuestos" />
          <CampoImporte v-model="totalCentimos" etiqueta="Total" />
          <SelectorBase
            v-model="cuentaId"
            etiqueta="Cuenta con la que se pagó"
            placeholder="Elige una cuenta"
            :opciones="cuentas.opciones"
            requerido
          />
        </div>
        <p class="lectura">
          Lectura: <span class="chip">{{ ETIQUETA_METODO[factura.extraction_method] }}</span>
          · Confianza global {{ porcentaje(factura.confidence, 0) }}
          <span :class="`confianza--${tonoConfianza(factura.confidence)}`">
            · {{ ETIQUETA_CONFIANZA[tonoConfianza(factura.confidence)] }}
          </span>
          <BotonBase variante="enlace" tamanyo="sm" :href="`/api/v1/invoices/${factura.id}/file?disposition=inline`">
            Ver PDF original
          </BotonBase>
        </p>
      </section>

      <!-- Líneas -->
      <section class="tarjeta" aria-labelledby="titulo-lineas">
        <h2 id="titulo-lineas" class="titulo-bloque">Líneas extraídas</h2>

        <div v-if="facturas.cargandoFactura" class="caja">
          <EsqueletoCarga variante="texto" :lineas="6" anuncio="Cargando las líneas" />
        </div>

        <p v-else-if="facturas.borrador.length === 0" class="vacio">
          No se ha detectado ninguna línea en este documento.
        </p>

        <div v-else class="envoltorio-tabla" tabindex="0">
          <table class="tabla">
            <caption class="oculto">
              Líneas de la factura, editables, con su confianza de lectura
            </caption>
            <thead>
              <tr>
                <th scope="col" class="col-icono"><span class="oculto">Revisión</span></th>
                <th scope="col">Descripción</th>
                <th scope="col">Cantidad</th>
                <th scope="col">Unidad</th>
                <th scope="col">Precio unit.</th>
                <th scope="col">Total</th>
                <th scope="col">Temática</th>
                <th scope="col" class="col-conf">Confianza</th>
                <th scope="col" class="col-icono"><span class="oculto">Acciones</span></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="linea in facturas.borrador" :key="linea.clave">
                <tr
                  :class="{
                    'fila--baja': tonoConfianza(linea.confidence) === 'baja',
                    'fila--excluida': linea.is_excluded,
                    'fila--foco': claveConFoco === linea.clave,
                  }"
                >
                  <td class="col-icono">
                    <TriangleAlert
                      v-if="tonoConfianza(linea.confidence) === 'baja'"
                      :size="16"
                      class="icono-aviso"
                      aria-hidden="true"
                    />
                    <Check v-else :size="16" class="icono-ok" aria-hidden="true" />
                  </td>
                  <td>
                    <CampoTexto
                      :model-value="linea.description"
                      etiqueta="Descripción"
                      etiqueta-oculta
                      @update:model-value="editar(linea, { description: $event })"
                    />
                  </td>
                  <td class="estrecha">
                    <CampoTexto
                      :model-value="linea.quantity ?? ''"
                      etiqueta="Cantidad"
                      etiqueta-oculta
                      @update:model-value="editar(linea, { quantity: $event || null })"
                    />
                  </td>
                  <td class="estrecha">
                    <SelectorBase
                      :model-value="linea.unit ?? null"
                      etiqueta="Unidad"
                      etiqueta-oculta
                      placeholder="ud"
                      :opciones="UNIDADES"
                      @update:model-value="editar(linea, { unit: $event ? String($event) : null })"
                    />
                  </td>
                  <td class="estrecha">
                    <CampoTexto
                      :model-value="linea.unit_price ?? ''"
                      etiqueta="Precio unitario"
                      etiqueta-oculta
                      :sufijo="simboloDe()"
                      @update:model-value="editar(linea, { unit_price: $event || null })"
                    />
                  </td>
                  <td class="estrecha">
                    <CampoImporte
                      :model-value="centimosDeImporte(linea.total)"
                      etiqueta="Total de la línea"
                      etiqueta-oculta
                      @update:model-value="editarTotal(linea, $event)"
                    />
                  </td>
                  <td :id="`tematica-${linea.clave}`">
                    <SelectorBase
                      :model-value="linea.category_id ?? null"
                      etiqueta="Temática"
                      etiqueta-oculta
                      placeholder="Sin clasificar"
                      :opciones="categorias.opciones('expense')"
                      :error="faltaTematica(linea) ? 'Esta línea no tiene temática asignada.' : undefined"
                      @update:model-value="
                        editar(linea, { category_id: $event ? String($event) : null })
                      "
                    />
                  </td>
                  <td class="col-conf num" :class="`confianza--${tonoConfianza(linea.confidence)}`">
                    {{ porcentaje(linea.confidence, 0) }}
                  </td>
                  <td class="col-icono">
                    <BotonBase
                      variante="fantasma"
                      tamanyo="sm"
                      solo-icono
                      :icono="X"
                      :etiqueta-accesible="`Eliminar la línea ${linea.description || 'sin descripción'}`"
                      @click="facturas.quitarLineaDelBorrador(linea.clave)"
                    />
                  </td>
                </tr>
                <tr v-if="motivoDeRevision(linea)" class="fila-motivo">
                  <td />
                  <td :colspan="8">{{ motivoDeRevision(linea) }}</td>
                </tr>
                <tr v-if="linea.change_pct !== null && linea.change_pct !== undefined" class="fila-motivo">
                  <td />
                  <td :colspan="8" class="motivo-precio">
                    Antes {{ precioUnitario(linea.last_unit_price) }} ·
                    <span class="oculto">{{ linea.change_pct > 0 ? 'Ha subido' : 'Ha bajado' }}</span>
                    {{ linea.change_pct > 0 ? '+' : '' }}{{ porcentaje(linea.change_pct / 100) }}
                    frente a la última compra
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <div class="pie-lineas">
          <BotonBase variante="fantasma" :icono="Plus" @click="facturas.anyadirLineaEnBorrador()">
            Añadir línea manual
          </BotonBase>
          <p class="sumas num" :class="{ mal: !facturas.cuadra }">
            Suma de líneas {{ dinero(facturas.sumaLineas) }} · Total de la factura
            {{ dinero(facturas.totalFactura) }}
            <template v-if="!facturas.cuadra">
              · Diferencia {{ dinero(Math.abs(facturas.diferencia)) }}
            </template>
          </p>
        </div>
      </section>

      <footer class="acciones">
        <BotonBase variante="contorno" :deshabilitado="enviando" @click="cancelar">
          Cancelar
        </BotonBase>
        <BotonBase
          variante="secundaria"
          :cargando="enCurso === 'borrador'"
          :deshabilitado="enviando"
          @click="guardarBorrador"
        >
          Guardar como borrador
        </BotonBase>
        <BotonBase
          variante="primaria"
          :cargando="enCurso === 'factura'"
          :deshabilitado="enviando"
          @click="guardarFactura"
        >
          Guardar factura
        </BotonBase>
      </footer>
    </template>
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
.caja {
  padding: var(--sp-5);
}
.titulo {
  margin: 0 0 var(--sp-4);
  font-size: var(--t-h1);
  line-height: var(--t-h1-lh);
  font-weight: 600;
}
.titulo-bloque {
  margin: 0;
  padding: var(--sp-4) var(--sp-4) 0;
  font-size: var(--t-h2);
  font-weight: 600;
}

/* --- Procesando --- */
.procesando {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-4);
  padding: var(--sp-8) var(--sp-4);
  text-align: center;
}
.nombre-fichero {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.procesando :deep(.progreso),
.procesando > :nth-child(2) {
  width: min(480px, 100%);
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

/* --- Bandas de aviso --- */
.banda {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
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

/* --- Cabecera --- */
.rejilla-cabecera {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--sp-3);
}
.lectura {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: var(--sp-4) 0 0;
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
.confianza--alta {
  color: var(--c-positive);
}
.confianza--media {
  color: var(--c-text-2);
}
.confianza--baja {
  color: var(--c-warning);
  font-weight: 600;
}

/* --- Tabla de líneas --- */
.envoltorio-tabla {
  overflow-x: auto;
  padding: var(--sp-3) var(--sp-4);
}
.tabla {
  width: 100%;
  min-width: 1000px;
  border-collapse: collapse;
  font-size: var(--t-sm);
}
.tabla thead th {
  padding: var(--sp-2);
  text-align: left;
  border-bottom: 1px solid var(--c-border);
  color: var(--c-text-3);
  font-weight: 500;
  white-space: nowrap;
}
.tabla td {
  padding: var(--sp-1) var(--sp-2);
  border-bottom: 1px solid var(--c-border-soft);
  vertical-align: middle;
}
.col-icono {
  width: 36px;
  text-align: center;
}
.col-conf {
  width: 84px;
  text-align: right;
}
.estrecha {
  width: 120px;
}
.icono-ok {
  color: var(--c-positive);
}
.icono-aviso {
  color: var(--c-warning);
}
.fila--baja > td {
  background-color: var(--c-warning-wash);
}
.fila--excluida > td {
  opacity: 0.55;
}
.fila--foco > td {
  outline: 2px solid var(--c-negative);
  outline-offset: -2px;
}
.fila-motivo td {
  padding-top: 0;
  border-bottom: 1px solid var(--c-border-soft);
  color: var(--c-warning);
  font-size: var(--t-caption);
}
.motivo-precio {
  color: var(--c-info);
}
.vacio {
  margin: 0;
  padding: var(--sp-5);
  color: var(--c-text-2);
  font-size: var(--t-sm);
}

.pie-lineas {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4) var(--sp-4);
  border-top: 1px solid var(--c-border);
}
.sumas {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.sumas.mal {
  color: var(--c-warning);
  font-weight: 600;
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
