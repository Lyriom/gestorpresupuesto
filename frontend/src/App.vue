<script setup lang="ts">
/**
 * Raíz de la aplicación: elige el marco y monta la vista.
 *
 * `LayoutApp` vive aquí y no dentro de cada vista para que la barra lateral, el
 * selector de mes y el estado de plegado sobrevivan a la navegación. Las
 * pantallas de sesión (`layout: 'auth'`) y las que ocupan la pantalla completa
 * (`'desnudo'`) traen su propio marco.
 *
 * El modal de alta rápida también vive aquí: se dispara desde el botón de la
 * lateral, desde el flotante de móvil y desde el atajo `n`, que son tres sitios
 * que no pertenecen a ninguna vista concreta.
 */
import { computed, ref, watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import {
  ChartPie,
  FileText,
  Landmark,
  LayoutDashboard,
  Package,
  Settings,
  Tags,
  Wallet,
} from 'lucide-vue-next'

import BotonBase from '@/components/ui/BotonBase.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import { atajosRegistrados } from '@/composables/useAtajos'
import LayoutApp from '@/layouts/LayoutApp.vue'
import ModalMovimiento from '@/views/componentes/ModalMovimiento.vue'
import { useAlertas } from '@/stores/alertas'
import { usePresupuesto } from '@/stores/presupuesto'
import { useSesion } from '@/stores/sesion'

const route = useRoute()
const router = useRouter()
const sesion = useSesion()
const presupuesto = usePresupuesto()
const alertas = useAlertas()

const enApp = computed(() => route.meta.layout === 'app' && sesion.autenticado)
const rutaActiva = computed(() => `/${String(route.path).split('/')[1] ?? ''}`)

const altaAbierta = ref(false)
const ayudaAbierta = ref(false)

/** Los atajos vivos, agrupados como los pide la ayuda del sistema de diseño. */
const atajos = atajosRegistrados()
const gruposDeAtajos = computed(() => {
  const grupos = new Map<string, Array<{ combinacion: string; descripcion: string }>>()
  for (const a of atajos.value) {
    const grupo = a.grupo ?? 'General'
    const lista = grupos.get(grupo) ?? []
    lista.push({ combinacion: a.combinacion, descripcion: a.descripcion })
    grupos.set(grupo, lista)
  }
  return [...grupos.entries()]
})

const destinos = computed(() => [
  { clave: 'panel', etiqueta: 'Panel', icono: LayoutDashboard, ruta: '/', enMovil: true },
  {
    clave: 'movimientos',
    etiqueta: 'Movimientos',
    icono: Wallet,
    ruta: '/movimientos',
    enMovil: true,
  },
  { clave: 'tematicas', etiqueta: 'Temáticas', icono: Tags, ruta: '/tematicas', enMovil: true },
  {
    clave: 'facturas',
    etiqueta: 'Facturas',
    icono: FileText,
    ruta: '/facturas',
    enMovil: true,
  },
  { clave: 'productos', etiqueta: 'Productos', icono: Package, ruta: '/productos' },
  { clave: 'informes', etiqueta: 'Informes', icono: ChartPie, ruta: '/informes', enMovil: true },
  { clave: 'cuentas', etiqueta: 'Cuentas', icono: Landmark, ruta: '/cuentas' },
  { clave: 'ajustes', etiqueta: 'Ajustes', icono: Settings, ruta: '/ajustes' },
])

function navegar(ruta: string): void {
  void router.push(ruta)
}

async function cerrarSesion(): Promise<void> {
  await sesion.salir()
  void router.push({ name: 'entrar' })
}

function trasGuardar(): void {
  // El presupuesto del mes cambia con cada gasto: se recarga sin salir de la vista.
  void presupuesto.cargar()
}

watch(
  () => sesion.autenticado,
  (dentro) => {
    if (!dentro) return
    presupuesto.periodo = sesion.periodoActual
    void alertas.cargarContador()
  },
  { immediate: true },
)
</script>

<template>
  <LayoutApp
    v-if="enApp"
    :ruta-activa="rutaActiva"
    :periodo="presupuesto.periodo"
    :usuario="sesion.usuarioDelLayout"
    :minutos-de-sesion="sesion.minutosDeSesion"
    :destinos="destinos"
    @navegar="navegar"
    @update:periodo="presupuesto.establecerPeriodo($event)"
    @anyadir-gasto="altaAbierta = true"
    @cerrar-sesion="cerrarSesion"
    @abrir-ajustes="navegar('/ajustes')"
    @abrir-perfil="navegar('/ajustes')"
    @abrir-ayuda="ayudaAbierta = true"
    @renovar-sesion="sesion.comprobarSesion()"
  >
    <RouterView />
  </LayoutApp>

  <RouterView v-else />

  <ModalMovimiento v-model:abierto="altaAbierta" @guardado="trasGuardar" />

  <ModalBase
    v-model:abierto="ayudaAbierta"
    titulo="Atajos de teclado"
    tamanyo="sm"
    @cerrar="ayudaAbierta = false"
  >
    <div v-for="[grupo, lista] in gruposDeAtajos" :key="grupo" class="grupo-atajos">
      <p class="grupo-titulo">{{ grupo }}</p>
      <dl>
        <template v-for="a in lista" :key="a.combinacion">
          <dt><kbd>{{ a.combinacion }}</kbd></dt>
          <dd>{{ a.descripcion }}</dd>
        </template>
      </dl>
    </div>
    <p v-if="gruposDeAtajos.length === 0" class="sin-atajos">
      No hay atajos activos en esta pantalla.
    </p>
    <template #pie>
      <BotonBase variante="primaria" @click="ayudaAbierta = false">Entendido</BotonBase>
    </template>
  </ModalBase>
</template>

<style scoped>
.grupo-atajos + .grupo-atajos {
  margin-top: var(--sp-4);
}
.grupo-titulo {
  margin: 0 0 var(--sp-2);
  font-size: var(--t-sm);
  font-weight: 600;
  color: var(--c-text-2);
}
.grupo-atajos dl {
  display: grid;
  grid-template-columns: 6rem minmax(0, 1fr);
  gap: var(--sp-2) var(--sp-3);
  margin: 0;
  font-size: var(--t-sm);
}
.grupo-atajos dd {
  margin: 0;
}
kbd {
  padding: 1px 6px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  background-color: var(--c-surface-2);
  font-family: var(--font-mono);
  font-size: var(--t-micro);
}
.sin-atajos {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-3);
}
</style>
