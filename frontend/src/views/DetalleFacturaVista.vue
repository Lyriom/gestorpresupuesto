<script setup lang="ts">
/**
 * Detalle de una factura ya guardada (§2.10).
 *
 * Modo lectura: lo confirmado en la revisión, más el enlace al movimiento que
 * generó. Editar devuelve a la pantalla de revisión con los valores guardados.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Download, Pencil, Trash2 } from 'lucide-vue-next'

import { apiFacturas, ETIQUETA_METODO } from '@/api/facturas'
import { apiMovimientos, type Movimiento } from '@/api/movimientos'
import BotonBase from '@/components/ui/BotonBase.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import EtiquetaCategoria from '@/components/ui/EtiquetaCategoria.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import { useAvisos } from '@/composables/useAvisos'
import { euros, fechaCorta } from '@/lib/formato'
import { ranuraDeCategoria } from '@/stores/categorias'
import { useFacturas } from '@/stores/facturas'
import BloqueError from './componentes/BloqueError.vue'

const route = useRoute()
const router = useRouter()
const facturas = useFacturas()
const avisos = useAvisos()

const id = computed(() => String(route.params.id))
const factura = computed(() => facturas.factura)

const movimiento = ref<Movimiento | null>(null)
const borradoAbierto = ref(false)

const urlPdf = computed(() => apiFacturas.urlFichero(id.value, 'inline'))
const urlDescarga = computed(() => apiFacturas.urlFichero(id.value, 'attachment'))

async function cargar(): Promise<void> {
  await facturas.cargarFactura(id.value)
  const transaccion = factura.value?.transaction_id
  if (!transaccion) {
    movimiento.value = null
    return
  }
  try {
    movimiento.value = await apiMovimientos.obtener(transaccion)
  } catch {
    movimiento.value = null
  }
}

async function eliminar(): Promise<void> {
  const ok = await facturas.borrar(id.value, factura.value?.status === 'confirmed')
  if (!ok) return
  avisos.exito('Factura eliminada.')
  void router.push({ name: 'facturas' })
}

onMounted(() => void cargar())
</script>

<template>
  <div class="vista">
    <nav class="miga" aria-label="Migas de pan">
      <BotonBase variante="enlace" tamanyo="sm" @click="router.push({ name: 'facturas' })">
        Facturas
      </BotonBase>
      <span aria-hidden="true">›</span>
      <span>{{ factura?.issuer || 'Factura' }}</span>
    </nav>

    <BloqueError
      v-if="facturas.errorFactura && !factura"
      titulo="No se ha podido cargar esta factura"
      :nivel="2"
      @reintentar="cargar"
    />

    <div v-else-if="facturas.cargandoFactura && !factura" class="tarjeta caja">
      <EsqueletoCarga variante="texto" :lineas="6" anuncio="Cargando la factura" />
    </div>

    <template v-else-if="factura">
      <section class="tarjeta caja" aria-labelledby="titulo-factura">
        <h1 id="titulo-factura" class="titulo">Factura de {{ factura.issuer || 'emisor sin leer' }}</h1>
        <p class="meta">
          <template v-if="factura.issuer_tax_id">NIF {{ factura.issuer_tax_id }} · </template>
          <template v-if="factura.number">Número {{ factura.number }} · </template>
          {{ fechaCorta(factura.date ?? factura.uploaded_at) }}
        </p>
        <p class="meta">
          Lectura: <span class="chip">{{ ETIQUETA_METODO[factura.extraction_method] }}</span>
          · Confianza {{ Math.round(factura.confidence * 100) }} %
          <BotonBase variante="enlace" tamanyo="sm" :href="urlPdf">Ver PDF original</BotonBase>
        </p>

        <dl class="importes num">
          <div>
            <dt>Base imponible</dt>
            <dd>{{ euros(factura.taxable_base) }}</dd>
          </div>
          <div>
            <dt>Impuestos</dt>
            <dd>{{ euros(factura.tax_amount) }}</dd>
          </div>
          <div>
            <dt>Total</dt>
            <dd class="grande">{{ euros(factura.total) }}</dd>
          </div>
        </dl>
      </section>

      <section class="tarjeta" aria-labelledby="titulo-lineas">
        <h2 id="titulo-lineas" class="titulo-bloque">Líneas</h2>
        <div class="envoltorio-tabla">
          <table class="tabla">
            <caption class="oculto">Líneas de la factura</caption>
            <thead>
              <tr>
                <th scope="col">Descripción</th>
                <th scope="col" class="num-col">Cantidad</th>
                <th scope="col">Unidad</th>
                <th scope="col" class="num-col">Precio unit.</th>
                <th scope="col" class="num-col">Total</th>
                <th scope="col">Temática</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="l in factura.lines" :key="l.id" :class="{ excluida: l.is_excluded }">
                <th scope="row" class="descripcion">{{ l.description }}</th>
                <td class="num-col num">{{ l.quantity ?? '—' }}</td>
                <td>{{ l.unit ?? '—' }}</td>
                <td class="num-col num">{{ l.unit_price ? euros(l.unit_price) : '—' }}</td>
                <td class="num-col num">{{ euros(l.total) }}</td>
                <td>
                  <EtiquetaCategoria
                    v-if="l.category"
                    :nombre="l.category.name"
                    :ranura="ranuraDeCategoria(l.category.color, l.category.id)"
                    tamanyo="sm"
                  />
                  <span v-else class="tenue">Sin clasificar</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="tarjeta caja" aria-labelledby="titulo-movimiento">
        <h2 id="titulo-movimiento" class="titulo-bloque sin-relleno">Movimiento vinculado</h2>
        <p v-if="movimiento" class="movimiento">
          {{ fechaCorta(movimiento.date) }} ·
          {{ movimiento.description || movimiento.payee?.name || 'Sin concepto' }} ·
          <span class="num">{{ euros(movimiento.signed_amount, { signoSiempre: true }) }}</span>
          <BotonBase
            variante="enlace"
            tamanyo="sm"
            @click="router.push({ name: 'movimientos', query: { factura_id: id } })"
          >
            Ver movimiento
          </BotonBase>
        </p>
        <p v-else class="tenue">
          Sin movimiento vinculado.
          <BotonBase
            variante="enlace"
            tamanyo="sm"
            @click="router.push({ name: 'revisar-factura', params: { id } })"
          >
            Vincular a un movimiento
          </BotonBase>
        </p>
      </section>

      <footer class="acciones">
        <BotonBase variante="secundaria" :icono="Download" :href="urlDescarga">
          Descargar PDF
        </BotonBase>
        <BotonBase
          variante="secundaria"
          :icono="Pencil"
          @click="router.push({ name: 'revisar-factura', params: { id } })"
        >
          Editar
        </BotonBase>
        <BotonBase variante="peligro-fantasma" :icono="Trash2" @click="borradoAbierto = true">
          Eliminar factura
        </BotonBase>
      </footer>
    </template>

    <ModalBase
      v-model:abierto="borradoAbierto"
      titulo="¿Eliminar esta factura?"
      tamanyo="sm"
      @cerrar="borradoAbierto = false"
    >
      <p class="parrafo">
        Los movimientos que creó no se eliminarán, pero perderán el enlace al PDF.
      </p>
      <template #pie>
        <BotonBase variante="contorno" @click="borradoAbierto = false">Cancelar</BotonBase>
        <BotonBase variante="peligro" @click="eliminar">Eliminar factura</BotonBase>
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
.caja {
  padding: var(--sp-5);
}
.titulo {
  margin: 0 0 var(--sp-2);
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
.titulo-bloque.sin-relleno {
  padding: 0 0 var(--sp-2);
}
.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0 0 var(--sp-2);
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

.importes {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-6);
  margin: var(--sp-4) 0 0;
}
.importes dt {
  font-size: var(--t-caption);
  color: var(--c-text-3);
}
.importes dd {
  margin: 0;
  font-size: var(--t-h3);
  font-weight: 600;
}
.importes .grande {
  font-size: var(--t-display);
}

.envoltorio-tabla {
  overflow-x: auto;
  padding: var(--sp-3) var(--sp-4) var(--sp-4);
}
.tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-sm);
}
.tabla th,
.tabla td {
  padding: var(--sp-2);
  text-align: left;
  border-bottom: 1px solid var(--c-border-soft);
  white-space: nowrap;
}
.tabla thead th {
  color: var(--c-text-3);
  font-weight: 500;
}
.descripcion {
  font-weight: 500;
  white-space: normal;
}
.num-col {
  text-align: right;
}
.excluida {
  opacity: 0.55;
}
.tenue {
  color: var(--c-text-3);
  font-size: var(--t-caption);
}
.movimiento {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: var(--t-sm);
}
.acciones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}
.parrafo {
  margin: 0;
  font-size: var(--t-sm);
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
</style>
