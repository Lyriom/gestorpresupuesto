<script setup lang="ts">
/**
 * Facturas (§2.7): zona de arrastre y bandeja de las últimas.
 *
 * El fichero se valida aquí por extensión y tamaño para no gastar una subida en
 * balde, pero la validación que manda es la del servidor, que comprueba la firma
 * del PDF y no el `content-type` que declara el navegador (RN-43).
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { FileUp } from 'lucide-vue-next'

import {
  ETIQUETA_CONFIANZA,
  ETIQUETA_ESTADO_FACTURA,
  tonoConfianza,
  type Factura,
} from '@/api/facturas'
import BotonBase from '@/components/ui/BotonBase.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import { dinero, fechaCorta, porcentaje } from '@/lib/formato'
import { useFacturas } from '@/stores/facturas'
import { useSesion } from '@/stores/sesion'
import BloqueError from './componentes/BloqueError.vue'

const EXTENSIONES = ['.pdf', '.jpg', '.jpeg', '.png']

const router = useRouter()
const facturas = useFacturas()
const sesion = useSesion()

const entrada = ref<HTMLInputElement | null>(null)
const arrastrando = ref(false)
const errorFichero = ref<string | null>(null)

const maxMb = computed(() => sesion.maxSubidaMb)
const mensajeFormato = computed(
  () => `Solo se admiten archivos PDF, JPG o PNG de hasta ${maxMb.value} MB.`,
)

/** Alta, media o baja, con el número siempre al lado (§2.9). */
function etiquetaConfianza(valor: number): string {
  return `Confianza ${ETIQUETA_CONFIANZA[tonoConfianza(valor)].toLowerCase()}`
}

function accionDe(f: Factura): string {
  if (f.status === 'confirmed') return 'Ver'
  if (f.status === 'processing') return 'Ver el progreso'
  return 'Revisar'
}

function irA(f: Factura): void {
  if (f.status === 'confirmed') void router.push({ name: 'factura', params: { id: f.id } })
  else void router.push({ name: 'revisar-factura', params: { id: f.id } })
}

function validar(fichero: File): boolean {
  const nombre = fichero.name.toLowerCase()
  if (!EXTENSIONES.some((e) => nombre.endsWith(e))) {
    errorFichero.value = mensajeFormato.value
    return false
  }
  if (fichero.size > maxMb.value * 1024 * 1024) {
    errorFichero.value = mensajeFormato.value
    return false
  }
  errorFichero.value = null
  return true
}

async function procesar(fichero: File): Promise<void> {
  if (!validar(fichero)) return
  const subida = await facturas.subir(fichero)
  if (subida) void router.push({ name: 'revisar-factura', params: { id: subida.id } })
  else errorFichero.value = facturas.errorSubida
}

function alSoltar(evento: DragEvent): void {
  arrastrando.value = false
  const fichero = evento.dataTransfer?.files?.[0]
  if (fichero) void procesar(fichero)
}

function alElegir(evento: Event): void {
  const fichero = (evento.target as HTMLInputElement).files?.[0]
  if (fichero) void procesar(fichero)
}

onMounted(() => {
  facturas.limpiarActiva()
  void facturas.cargar({ size: 10 })
})
</script>

<template>
  <div class="vista">
    <h1 class="titulo">Facturas</h1>

    <div
      class="zona"
      :class="{ activa: arrastrando, mala: !!errorFichero }"
      @dragover.prevent="arrastrando = true"
      @dragleave.prevent="arrastrando = false"
      @drop.prevent="alSoltar"
    >
      <FileUp :size="32" aria-hidden="true" />
      <p class="titular">Arrastra aquí tu factura o ticket</p>
      <p class="o">
        o
        <BotonBase variante="enlace" @click="entrada?.click()">selecciona un archivo</BotonBase>
      </p>
      <p class="limites">
        PDF, JPG o PNG · hasta {{ maxMb }} MB · una factura por archivo
      </p>
      <input
        ref="entrada"
        class="oculto"
        type="file"
        accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
        aria-label="Selecciona una factura o un ticket"
        @change="alElegir"
      />
    </div>

    <p v-if="errorFichero" class="error-fichero" role="alert">{{ errorFichero }}</p>

    <section class="bloque" aria-labelledby="titulo-ultimas">
      <h2 id="titulo-ultimas" class="titulo-bloque">Últimas facturas</h2>

      <div v-if="facturas.cargando" class="tarjeta caja">
        <EsqueletoCarga variante="texto" :lineas="5" anuncio="Cargando las facturas" />
      </div>

      <BloqueError
        v-else-if="facturas.error"
        titulo="No se han podido cargar las facturas"
        @reintentar="facturas.cargar({ size: 10 })"
      />

      <div v-else-if="facturas.items.length === 0" class="tarjeta caja">
        <EstadoVacio
          titulo="Todavía no has subido ninguna factura."
          descripcion="Sube un PDF y se extraerán las líneas, los productos y los precios."
          :nivel="3"
        />
      </div>

      <ul v-else class="tarjeta lista">
        <li v-for="f in facturas.items" :key="f.id">
          <span class="fecha">{{ fechaCorta(f.date ?? f.uploaded_at) }}</span>
          <span class="emisor">{{ f.issuer || f.filename }}</span>
          <span class="importe num">{{ f.total ? dinero(f.total) : '—' }}</span>
          <span class="estado" :class="`estado--${f.status}`">
            {{ ETIQUETA_ESTADO_FACTURA[f.status] }}
          </span>
          <span class="confianza" :class="`confianza--${tonoConfianza(f.confidence)}`">
            {{ etiquetaConfianza(f.confidence) }} · {{ porcentaje(f.confidence, 0) }}
          </span>
          <BotonBase variante="fantasma" tamanyo="sm" @click="irA(f)">{{ accionDe(f) }}</BotonBase>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.vista {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}
.titulo {
  margin: 0;
  font-size: var(--t-h1);
  line-height: var(--t-h1-lh);
  font-weight: 600;
}

/* El borde discontinuo significa «esto está por rellenar»: es su único uso. */
.zona {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-8) var(--sp-4);
  border: 1px dashed var(--c-border-strong);
  border-radius: var(--r-xl);
  background-color: var(--c-surface);
  color: var(--c-text-3);
  text-align: center;
}
.zona.activa {
  border-color: var(--c-accent);
  background-color: var(--c-surface-2);
}
.zona.mala {
  border-color: var(--c-negative);
}
.titular {
  margin: 0;
  font-size: var(--t-h3);
  font-weight: 600;
  color: var(--c-text-1);
}
.o,
.limites {
  margin: 0;
  font-size: var(--t-sm);
}
.error-fichero {
  margin: 0;
  padding: var(--sp-3);
  border-radius: var(--r-md);
  background-color: var(--c-negative-wash);
  color: var(--c-negative);
  font-size: var(--t-sm);
}

.bloque {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.titulo-bloque {
  margin: 0;
  font-size: var(--t-h2);
  line-height: var(--t-h2-lh);
  font-weight: 600;
}
.caja {
  padding: var(--sp-5);
}

.lista {
  margin: 0;
  padding: var(--sp-2) var(--sp-4);
  list-style: none;
}
.lista li {
  display: grid;
  grid-template-columns: 6.5rem minmax(0, 1fr) 6rem auto auto auto;
  align-items: center;
  gap: var(--sp-3);
  min-height: 48px;
}
.lista li + li {
  border-top: 1px solid var(--c-border-soft);
}
.fecha {
  color: var(--c-text-3);
  font-size: var(--t-caption);
}
.emisor {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.importe {
  text-align: right;
}
.estado,
.confianza {
  font-size: var(--t-caption);
  white-space: nowrap;
}
.estado--pending_review {
  color: var(--c-warning);
  font-weight: 600;
}
.estado--failed {
  color: var(--c-negative);
  font-weight: 600;
}
.estado--confirmed,
.estado--processing,
.estado--discarded {
  color: var(--c-text-3);
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

@media (max-width: 767px) {
  .lista li {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .estado,
  .fecha {
    display: none;
  }
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
