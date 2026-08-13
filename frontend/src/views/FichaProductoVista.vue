<script setup lang="ts">
/**
 * Ficha de producto (§2.11): ¿ha subido o bajado, y dónde sale más barato?
 *
 * El gráfico de precios es **escalonado** a propósito: entre dos compras el
 * precio no sube poco a poco, se mantiene y da un salto el día de la siguiente
 * compra. Una recta inclinada contaría algo que no ha pasado.
 *
 * Las cifras de cabecera y el histórico cargan por separado: si el histórico
 * falla, lo que ya llegó se queda en pantalla.
 */
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDownRight, ArrowUpRight } from 'lucide-vue-next'

import GraficoBarras from '@/components/graficos/GraficoBarras.vue'
import GraficoLineas from '@/components/graficos/GraficoLineas.vue'
import BotonBase from '@/components/ui/BotonBase.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import { ETIQUETA_TENDENCIA } from '@/api/productos'
import { aNumero, euros, fechaCorta } from '@/lib/formato'
import { useProductos } from '@/stores/productos'
import BloqueError from './componentes/BloqueError.vue'

const route = useRoute()
const router = useRouter()
const productos = useProductos()

const id = computed(() => String(route.params.id))
const producto = computed(() => productos.producto)
const stats = computed(() => productos.estadisticas)

const unidad = computed(() => producto.value?.unit ?? productos.comparativa?.unit ?? '')

/** La serie va en orden cronológico: el store la pide con `sort=observed_at`. */
const etiquetas = computed(() => productos.precios.map((p) => fechaCorta(p.observed_at)))
const serie = computed(() => productos.precios.map((p) => aNumero(p.unit_price)))

const comparativa = computed(() => productos.comparativa?.by_payee ?? [])
const nombresComercio = computed(() => comparativa.value.map((c) => c.payee?.name ?? 'Sin comercio'))
const preciosComercio = computed(() => comparativa.value.map((c) => aNumero(c.last_unit_price)))

const masBarato = computed(() => productos.comparativa?.cheapest ?? null)

const ahorro = computed(() => {
  const barato = masBarato.value
  const actual = stats.value?.last_unit_price
  if (!barato || !actual) return null
  const diferencia = aNumero(actual) - aNumero(barato.last_unit_price)
  if (diferencia <= 0) return null
  const pct = (diferencia / aNumero(actual)) * 100
  return { diferencia, pct, comercio: barato.payee?.name ?? 'otro comercio' }
})

onMounted(() => void productos.cargarFicha(id.value))
onBeforeUnmount(() => productos.limpiarFicha())
</script>

<template>
  <div class="vista">
    <nav class="miga" aria-label="Migas de pan">
      <BotonBase variante="enlace" tamanyo="sm" @click="router.push({ name: 'productos' })">
        Productos
      </BotonBase>
      <span aria-hidden="true">›</span>
      <span>{{ producto?.name ?? 'Producto' }}</span>
    </nav>

    <BloqueError
      v-if="productos.errorFicha"
      titulo="No se ha podido cargar este producto"
      :nivel="2"
      @reintentar="productos.cargarFicha(id)"
    />

    <div v-else-if="productos.cargandoFicha" class="tarjeta caja">
      <EsqueletoCarga variante="texto" :lineas="4" anuncio="Cargando el producto" />
    </div>

    <template v-else-if="producto">
      <header class="tarjeta caja">
        <h1 class="titulo">{{ producto.name }}</h1>
        <p v-if="producto.brand || producto.size_text" class="marca">
          {{ [producto.brand, producto.size_text].filter(Boolean).join(' · ') }}
        </p>

        <div class="cifras">
          <div class="cifra">
            <p class="rotulo">Precio actual</p>
            <p class="valor num">
              {{ stats?.last_unit_price ? euros(stats.last_unit_price) : '—' }}
              <span v-if="unidad" class="unidad">/{{ unidad }}</span>
            </p>
          </div>

          <div class="cifra">
            <p class="rotulo">Comparado con el anterior</p>
            <p
              v-if="stats?.change_pct !== null && stats?.change_pct !== undefined"
              class="valor num"
              :class="stats.change_pct > 0 ? 'sube' : 'baja'"
            >
              <ArrowUpRight v-if="stats.change_pct > 0" :size="18" aria-hidden="true" />
              <ArrowDownRight v-else :size="18" aria-hidden="true" />
              {{ stats.change_pct > 0 ? '+' : '' }}{{ stats.change_pct.toFixed(1) }} %
            </p>
            <p v-else class="valor tenue">Sin histórico suficiente</p>
          </div>
        </div>

        <p v-if="stats" class="linea-stats num">
          Mínimo {{ euros(stats.min_unit_price) }} · Máximo {{ euros(stats.max_unit_price) }} ·
          Medio {{ euros(stats.average_unit_price) }} · Tendencia
          <span class="chip">{{ ETIQUETA_TENDENCIA[stats.trend] }}</span>
        </p>
      </header>

      <!-- Histórico de precio -->
      <BloqueError
        v-if="productos.errorHistorico"
        titulo="No se ha podido cargar el histórico de este producto"
        @reintentar="productos.cargarHistorico(id)"
      />

      <div v-else-if="productos.cargandoHistorico" class="tarjeta caja">
        <EsqueletoCarga variante="bloque" alto="260px" anuncio="Cargando el histórico de precios" />
      </div>

      <div v-else-if="productos.sinCompras" class="tarjeta caja">
        <EstadoVacio
          titulo="Este producto no tiene compras registradas."
          descripcion="Se irá llenando en cuanto revises una factura que lo incluya."
          :nivel="2"
        />
      </div>

      <template v-else>
        <GraficoLineas
          v-if="productos.hayHistorico"
          titulo="Histórico de precio"
          subtitulo="Precio por unidad en cada compra registrada"
          columna-etiquetas="Fecha"
          :etiquetas="etiquetas"
          :series="[{ nombre: 'Precio', datos: serie, color: 'cat-1', escalonada: true }]"
          :unidad="unidad || undefined"
          :resumen="`Evolución del precio de ${producto.name} en ${productos.precios.length} compras.`"
        />
        <p v-else class="tarjeta caja tenue">
          Sin histórico suficiente: hace falta una segunda compra para dibujar la evolución.
        </p>

        <GraficoBarras
          v-if="comparativa.length > 0"
          titulo="Comparativa por comercio"
          subtitulo="Último precio visto en cada uno"
          columna-etiquetas="Comercio"
          :etiquetas="nombresComercio"
          :series="[{ nombre: 'Último precio', datos: preciosComercio }]"
          :resumen="`Precio de ${producto.name} en ${comparativa.length} comercios.`"
        />

        <p v-if="ahorro" class="tarjeta caja ahorro num">
          Ahorras {{ euros(ahorro.diferencia) }}<template v-if="unidad">/{{ unidad }}</template>
          comprando en {{ ahorro.comercio }} (un {{ ahorro.pct.toFixed(1) }} % menos).
        </p>

        <!-- Historial de compras: la tabla gemela obligatoria del gráfico -->
        <section class="tarjeta" aria-labelledby="titulo-historial">
          <h2 id="titulo-historial" class="titulo-bloque">Historial de compras</h2>
          <div class="envoltorio-tabla">
            <table class="tabla">
              <caption class="oculto">Compras registradas de {{ producto.name }}</caption>
              <thead>
                <tr>
                  <th scope="col">Fecha</th>
                  <th scope="col">Comercio</th>
                  <th scope="col" class="num-col">Cantidad</th>
                  <th scope="col" class="num-col">Precio unit.</th>
                  <th scope="col" class="num-col">Total</th>
                  <th scope="col"><span class="oculto">Factura</span></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in [...productos.precios].reverse()" :key="p.id">
                  <th scope="row">{{ fechaCorta(p.observed_at) }}</th>
                  <td>{{ p.payee?.name ?? '—' }}</td>
                  <td class="num-col num">{{ p.quantity ?? '—' }} {{ p.unit ?? '' }}</td>
                  <td class="num-col num">{{ euros(p.unit_price) }}</td>
                  <td class="num-col num">{{ p.total ? euros(p.total) : '—' }}</td>
                  <td>
                    <BotonBase
                      v-if="p.invoice_id"
                      variante="enlace"
                      tamanyo="sm"
                      @click="router.push({ name: 'factura', params: { id: p.invoice_id } })"
                    >
                      Ver factura
                    </BotonBase>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
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
  margin: 0;
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
.marca {
  margin: var(--sp-1) 0 0;
  font-size: var(--t-sm);
  color: var(--c-text-3);
}

.cifras {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-8);
  margin-top: var(--sp-4);
}
.rotulo {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-3);
}
.valor {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  margin: var(--sp-1) 0 0;
  font-size: var(--t-display);
  font-weight: 600;
}
.valor.sube {
  color: var(--c-negative);
}
.valor.baja {
  color: var(--c-positive);
}
.unidad {
  font-size: var(--t-sm);
  color: var(--c-text-3);
}
.linea-stats {
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
.tenue {
  color: var(--c-text-3);
  font-size: var(--t-sm);
}
.ahorro {
  margin: 0;
  color: var(--c-positive);
  font-weight: 600;
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
.num-col {
  text-align: right;
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
