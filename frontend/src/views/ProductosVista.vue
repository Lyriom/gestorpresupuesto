<script setup lang="ts">
/**
 * Catálogo de productos: buscador y lista con el último precio y su variación.
 */
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-vue-next'

import { ETIQUETA_TENDENCIA, type Producto } from '@/api/productos'
import BarraBusqueda from '@/components/ui/BarraBusqueda.vue'
import BotonBase from '@/components/ui/BotonBase.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import PaginacionBase from '@/components/ui/PaginacionBase.vue'
import TablaDatos, { type ColumnaTabla } from '@/components/ui/TablaDatos.vue'
import { euros, fechaCorta } from '@/lib/formato'
import { useProductos } from '@/stores/productos'

type Fila = Producto & Record<string, unknown>

const router = useRouter()
const productos = useProductos()

const COLUMNAS: ColumnaTabla<Fila>[] = [
  { clave: 'name', etiqueta: 'Producto', ordenable: true },
  { clave: 'last_unit_price', etiqueta: 'Último precio', numerica: true, ancho: '140px' },
  { clave: 'change_pct', etiqueta: 'Variación', numerica: true, ancho: '120px' },
  { clave: 'observations_count', etiqueta: 'Compras', numerica: true, ancho: '100px', soloEscritorio: true },
  { clave: 'last_seen_on', etiqueta: 'Última vez', ancho: '130px', soloEscritorio: true },
]

const filas = computed<Fila[]>(() => productos.items as Fila[])

function recargar(): void {
  void productos.cargar()
}

onMounted(recargar)
</script>

<template>
  <div class="vista">
    <header class="cabecera">
      <h1 class="titulo">Productos</h1>
      <InterruptorBase
        :model-value="productos.soloConSubida"
        etiqueta="Solo los que han subido"
        tamanyo="sm"
        @update:model-value="
          (v) => {
            productos.soloConSubida = v
            productos.pagina = 1
            recargar()
          }
        "
      />
    </header>

    <BarraBusqueda
      :model-value="productos.busqueda"
      placeholder="Buscar un producto…"
      :resultados="productos.total"
      :buscando="productos.cargando"
      @update:model-value="productos.busqueda = $event"
      @buscar="
        () => {
          productos.pagina = 1
          recargar()
        }
      "
      @limpiar="
        () => {
          productos.busqueda = ''
          productos.pagina = 1
          recargar()
        }
      "
    />

    <TablaDatos
      :columnas="COLUMNAS"
      :filas="filas"
      :clave-fila="(f) => f.id"
      titulo="Catálogo de productos"
      titulo-oculto
      densidad="compacta"
      :cargando="productos.cargando"
      :vacio-por-filtro="productos.busqueda.length > 0"
      :error="productos.error ?? undefined"
      @fila-clic="(f) => router.push({ name: 'producto', params: { id: f.id } })"
      @reintentar="recargar"
      @quitar-filtros="
        () => {
          productos.busqueda = ''
          recargar()
        }
      "
    >
      <template #celda-name="{ fila }">
        <span class="nombre">{{ fila.name }}</span>
        <span v-if="fila.brand || fila.size_text" class="marca">
          {{ [fila.brand, fila.size_text].filter(Boolean).join(' · ') }}
        </span>
      </template>

      <template #celda-last_unit_price="{ fila }">
        {{ fila.last_unit_price ? euros(fila.last_unit_price) : '—' }}
        <span v-if="fila.unit" class="unidad">/{{ fila.unit }}</span>
      </template>

      <template #celda-change_pct="{ fila }">
        <span
          v-if="fila.change_pct !== null && fila.change_pct !== undefined"
          class="variacion"
          :class="fila.change_pct > 0 ? 'sube' : fila.change_pct < 0 ? 'baja' : ''"
        >
          <ArrowUpRight v-if="fila.change_pct > 0" :size="14" aria-hidden="true" />
          <ArrowDownRight v-else-if="fila.change_pct < 0" :size="14" aria-hidden="true" />
          <Minus v-else :size="14" aria-hidden="true" />
          {{ fila.change_pct > 0 ? '+' : '' }}{{ fila.change_pct.toFixed(1) }} %
        </span>
        <span v-else class="tenue">{{ ETIQUETA_TENDENCIA[fila.trend] }}</span>
      </template>

      <template #celda-last_seen_on="{ fila }">{{ fechaCorta(fila.last_seen_on) }}</template>

      <template #vacio>
        <EstadoVacio
          titulo="Todavía no hay productos en el catálogo."
          descripcion="Los productos se crean solos al revisar una factura y vincular sus líneas."
          :nivel="3"
        >
          <template #accion>
            <BotonBase variante="primaria" @click="router.push({ name: 'facturas' })">
              Subir una factura
            </BotonBase>
          </template>
        </EstadoVacio>
      </template>
    </TablaDatos>

    <PaginacionBase
      :pagina="productos.pagina"
      :tamanyo-pagina="productos.tamanyoPagina"
      :total="productos.total"
      :cargando="productos.cargando"
      unidad="productos"
      @update:pagina="
        (p) => {
          productos.pagina = p
          recargar()
        }
      "
      @update:tamanyo-pagina="
        (t) => {
          productos.tamanyoPagina = t
          productos.pagina = 1
          recargar()
        }
      "
    />
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
.nombre {
  display: block;
  font-weight: 500;
}
.marca,
.unidad,
.tenue {
  color: var(--c-text-3);
  font-size: var(--t-caption);
}
.variacion {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-weight: 600;
}
.variacion.sube {
  color: var(--c-negative);
}
.variacion.baja {
  color: var(--c-positive);
}
</style>
