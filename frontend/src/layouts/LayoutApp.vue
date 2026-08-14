<script setup lang="ts">
import { computed, ref, watch, type Component } from 'vue'
import {
  ChartPie,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Package,
  PanelLeft,
  Plus,
  Settings,
  Sun,
  Tags,
  User,
  Wallet,
  X,
} from 'lucide-vue-next'
import { useMedia } from '@/composables/useMedia'
import { useTema, type PreferenciaTema } from '@/composables/useTema'
import { useAtajos } from '@/composables/useAtajos'
import { etiquetaPeriodo, desplazarPeriodo, periodoDe , simboloDe } from '@/lib/formato'
import AvisoFlotante from '@/components/ui/AvisoFlotante.vue'
import BotonBase from '@/components/ui/BotonBase.vue'
import MenuDesplegable from '@/components/ui/MenuDesplegable.vue'
import PistaAyuda from '@/components/ui/PistaAyuda.vue'

export interface DestinoNav {
  clave: string
  etiqueta: string
  icono: Component
  ruta: string
  contador?: number
  /** Aparece en la barra inferior de móvil (5 destinos como máximo). */
  enMovil?: boolean
}

const props = withDefaults(
  defineProps<{
    /** Ruta activa; se compara con `destino.ruta`. */
    rutaActiva?: string
    /** Periodo en `AAAA-MM`: el ámbito de casi toda la aplicación. */
    periodo?: string
    usuario?: { nombre: string; correo: string; iniciales?: string; avatar?: string }
    /** Minutos que quedan de sesión; por debajo de 5 sale el punto de aviso. */
    minutosDeSesion?: number
    destinos?: DestinoNav[]
  }>(),
  {
    rutaActiva: '/',
    periodo: () => periodoDe(),
    destinos: () => [
      { clave: 'resumen', etiqueta: 'Resumen', icono: LayoutDashboard, ruta: '/', enMovil: true },
      {
        clave: 'transacciones',
        etiqueta: 'Transacciones',
        icono: Wallet,
        ruta: '/transacciones',
        enMovil: true,
      },
      { clave: 'tematicas', etiqueta: 'Temáticas', icono: Tags, ruta: '/tematicas', enMovil: true },
      { clave: 'facturas', etiqueta: 'Facturas', icono: FileText, ruta: '/facturas', enMovil: true },
      { clave: 'productos', etiqueta: 'Productos', icono: Package, ruta: '/productos' },
      { clave: 'informes', etiqueta: 'Informes', icono: ChartPie, ruta: '/informes', enMovil: true },
    ],
  },
)

const emit = defineEmits<{
  navegar: [ruta: string]
  'update:periodo': [periodo: string]
  anyadirGasto: []
  cerrarSesion: []
  abrirAjustes: []
  abrirPerfil: []
  abrirAyuda: []
  renovarSesion: []
}>()

const { lg, xl, esMovil } = useMedia()
const { tema, preferencia, establecer, opciones } = useTema()

const colapsadaManual = ref(false)
const cajonMovil = ref(false)

/** ≥1280 expandida · 1024–1279 colapsada · <1024 oculta tras el botón de menú. */
const colapsada = computed(() => colapsadaManual.value || (lg.value && !xl.value))
const lateralVisible = computed(() => lg.value || cajonMovil.value)

const iniciales = computed(() => {
  if (props.usuario?.iniciales) return props.usuario.iniciales
  const partes = (props.usuario?.nombre ?? '').trim().split(/\s+/).slice(0, 2)
  return partes.map((p) => p.charAt(0).toUpperCase()).join('') || '?'
})

/** Color determinista del borde del avatar: nunca aleatorio por render. */
const ranuraAvatar = computed(() => {
  const semilla = props.usuario?.correo ?? props.usuario?.nombre ?? ''
  let suma = 0
  for (let i = 0; i < semilla.length; i++) suma = (suma + semilla.charCodeAt(i)) % 12
  return suma + 1
})

const sesionCaduca = computed(
  () => props.minutosDeSesion !== undefined && props.minutosDeSesion <= 5,
)

const ICONO_TEMA: Record<PreferenciaTema, Component> = { dark: Moon, light: Sun, sistema: Monitor }

const destinosMovil = computed(() => props.destinos.filter((d) => d.enMovil).slice(0, 5))

function ir(ruta: string): void {
  emit('navegar', ruta)
  cajonMovil.value = false
}

function moverPeriodo(meses: number): void {
  emit('update:periodo', desplazarPeriodo(props.periodo, meses))
}

useAtajos([
  {
    combinacion: 'mod+b',
    descripcion: 'Plegar o desplegar la navegación',
    grupo: 'Navegación',
    accion: () => (colapsadaManual.value = !colapsadaManual.value),
  },
  {
    combinacion: 'g r',
    descripcion: 'Ir al resumen',
    grupo: 'Navegación',
    accion: () => ir('/'),
  },
  {
    combinacion: 'g t',
    descripcion: 'Ir a transacciones',
    grupo: 'Navegación',
    accion: () => ir('/transacciones'),
  },
  {
    combinacion: 'n',
    descripcion: 'Añadir gasto',
    grupo: 'Acciones',
    accion: () => emit('anyadirGasto'),
  },
])

watch(esMovil, (movil) => {
  if (movil) cajonMovil.value = false
})
</script>

<template>
  <div class="app" :class="{ 'con-barra-inferior': esMovil }">
    <a href="#contenido" class="salto">Saltar al contenido principal</a>
    <!-- Solo cuando la barra lateral existe: por debajo de 1024 px vive dentro
         del cajón y el enlace no llevaba a ninguna parte. -->
    <a v-if="lateralVisible" href="#navegacion" class="salto">Saltar a la navegación</a>

    <div v-if="cajonMovil && !lg" class="scrim-nav" @click="cajonMovil = false" />

    <nav
      v-if="lateralVisible"
      id="navegacion"
      class="lateral"
      :class="{ colapsada, flotante: !lg }"
      aria-label="Navegación principal"
    >
      <div class="marca">
        <span class="logo" aria-hidden="true">{{ simboloDe() }}</span>
        <span v-if="!colapsada" class="nombre-app">Gestor de presupuesto</span>
        <button
          v-if="!lg"
          type="button"
          class="icono-boton toque-44"
          aria-label="Cerrar la navegación"
          @click="cajonMovil = false"
        >
          <X :size="18" aria-hidden="true" />
        </button>
        <button
          v-else
          type="button"
          class="icono-boton toque-44"
          :aria-label="colapsada ? 'Desplegar la navegación' : 'Plegar la navegación'"
          @click="colapsadaManual = !colapsadaManual"
        >
          <PanelLeft :size="18" aria-hidden="true" />
        </button>
      </div>

      <!-- El selector de mes va arriba porque es el ámbito de casi todo. -->
      <div class="periodo" :class="{ compacto: colapsada }">
        <button type="button" class="toque-44" aria-label="Mes anterior" @click="moverPeriodo(-1)">
          <ChevronLeft :size="16" aria-hidden="true" />
        </button>
        <span v-if="!colapsada" class="etiqueta-periodo">{{ etiquetaPeriodo(periodo) }}</span>
        <button type="button" class="toque-44" aria-label="Mes siguiente" @click="moverPeriodo(1)">
          <ChevronRight :size="16" aria-hidden="true" />
        </button>
      </div>

      <div class="destacado">
        <BotonBase
          variante="primaria"
          :icono="Plus"
          :ancho-completo="!colapsada"
          :solo-icono="colapsada"
          etiqueta-accesible="Añadir gasto"
          @click="emit('anyadirGasto')"
        >
          Añadir gasto
        </BotonBase>
      </div>

      <ul class="destinos">
        <li v-for="d in destinos" :key="d.clave">
          <PistaAyuda v-if="colapsada" :texto="d.etiqueta" posicion="derecha" :retardo="0">
            <a
              :href="d.ruta"
              class="destino"
              :class="{ activo: d.ruta === rutaActiva }"
              :aria-current="d.ruta === rutaActiva ? 'page' : undefined"
              @click.prevent="ir(d.ruta)"
            >
              <component :is="d.icono" :size="18" aria-hidden="true" />
              <span class="oculto-visualmente">{{ d.etiqueta }}</span>
            </a>
          </PistaAyuda>
          <a
            v-else
            :href="d.ruta"
            class="destino"
            :class="{ activo: d.ruta === rutaActiva }"
            :aria-current="d.ruta === rutaActiva ? 'page' : undefined"
            @click.prevent="ir(d.ruta)"
          >
            <component :is="d.icono" :size="18" aria-hidden="true" />
            <span class="texto">{{ d.etiqueta }}</span>
            <span v-if="d.contador" class="contador num">{{ d.contador }}</span>
          </a>
        </li>
      </ul>

      <div class="pie-lateral">
        <MenuDesplegable
          etiqueta="Menú de usuario"
          hacia-arriba
          :items="[
            { clave: 'perfil', etiqueta: 'Mi perfil', icono: User },
            { clave: 'ajustes', etiqueta: 'Ajustes', icono: Settings },
            { clave: 'ayuda', etiqueta: 'Ayuda', icono: CircleHelp },
            { clave: 'salir', etiqueta: 'Cerrar sesión', icono: LogOut, peligrosa: true, separadorAntes: true },
          ]"
          @seleccionar="
            (clave) => {
              if (clave === 'perfil') emit('abrirPerfil')
              else if (clave === 'ajustes') emit('abrirAjustes')
              else if (clave === 'ayuda') emit('abrirAyuda')
              else if (clave === 'salir') emit('cerrarSesion')
            }
          "
        >
          <template #disparador="{ alternar, atributos }">
            <button type="button" class="usuario" v-bind="atributos" @click="alternar()">
              <span class="avatar" :style="{ '--hue': `var(--c-cat-${ranuraAvatar})` }">
                <img v-if="usuario?.avatar" :src="usuario.avatar" alt="" />
                <template v-else>{{ iniciales }}</template>
                <span v-if="sesionCaduca" class="punto-aviso" aria-hidden="true" />
              </span>
              <span v-if="!colapsada" class="datos-usuario">
                <span class="nombre">{{ usuario?.nombre ?? 'Sin sesión' }}</span>
                <span class="correo">{{ usuario?.correo ?? '' }}</span>
              </span>
              <ChevronDown v-if="!colapsada" :size="16" aria-hidden="true" />
            </button>
          </template>

          <template #cabecera>
            <div class="cabecera-menu">
              <p class="nombre">{{ usuario?.nombre ?? 'Sin sesión' }}</p>
              <p class="correo" :title="usuario?.correo">{{ usuario?.correo ?? '' }}</p>
            </div>
            <fieldset class="tema" role="radiogroup" aria-label="Tema de la interfaz">
              <label v-for="o in opciones" :key="o.valor">
                <input
                  type="radio"
                  name="tema"
                  :value="o.valor"
                  :checked="preferencia === o.valor"
                  @change="establecer(o.valor)"
                />
                <component :is="ICONO_TEMA[o.valor]" :size="14" aria-hidden="true" />
                {{ o.etiqueta }}
              </label>
            </fieldset>
            <button
              v-if="sesionCaduca"
              type="button"
              class="renovar"
              @click="emit('renovarSesion')"
            >
              Tu sesión caduca en {{ minutosDeSesion }} min. Renovar
            </button>
            <hr class="separador" />
          </template>
        </MenuDesplegable>
      </div>
    </nav>

    <div class="principal">
      <header v-if="!lg" class="cabecera-movil">
        <button
          type="button"
          class="icono-boton toque-44"
          aria-label="Abrir la navegación"
          :aria-expanded="cajonMovil"
          @click="cajonMovil = true"
        >
          <Menu :size="20" aria-hidden="true" />
        </button>
        <span class="titulo-movil">{{ etiquetaPeriodo(periodo) }}</span>
        <button
          type="button"
          class="icono-boton toque-44"
          :aria-label="tema === 'dark' ? 'Usar el tema claro' : 'Usar el tema oscuro'"
          @click="establecer(tema === 'dark' ? 'light' : 'dark')"
        >
          <component :is="tema === 'dark' ? Sun : Moon" :size="18" aria-hidden="true" />
        </button>
      </header>

      <main id="contenido" class="contenido" tabindex="-1">
        <slot />
      </main>
    </div>

    <!-- Móvil: barra inferior de 5 destinos y botón flotante. -->
    <nav v-if="esMovil" class="barra-inferior" aria-label="Navegación principal">
      <a
        v-for="d in destinosMovil"
        :key="d.clave"
        :href="d.ruta"
        :class="{ activo: d.ruta === rutaActiva }"
        :aria-current="d.ruta === rutaActiva ? 'page' : undefined"
        @click.prevent="ir(d.ruta)"
      >
        <component :is="d.icono" :size="20" aria-hidden="true" />
        <span>{{ d.etiqueta }}</span>
      </a>
    </nav>
    <button
      v-if="esMovil"
      type="button"
      class="flotante"
      aria-label="Añadir gasto"
      @click="emit('anyadirGasto')"
    >
      <Plus :size="24" aria-hidden="true" />
    </button>

    <AvisoFlotante />
  </div>
</template>

<style scoped>
.app {
  display: flex;
  min-height: 100dvh;
  background-color: var(--c-app-bg);
}

.salto {
  position: absolute;
  left: var(--sp-2);
  top: var(--sp-2);
  z-index: 200;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-md);
  background-color: var(--c-surface-2);
  color: var(--c-text-1);
  font-size: var(--t-sm);
  translate: 0 -200%;
}
.salto:focus-visible {
  translate: 0 0;
}

.scrim-nav {
  position: fixed;
  inset: 0;
  z-index: 79;
  background-color: var(--c-overlay);
}

/* --- Lateral ------------------------------------------------------------- */
.lateral {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  flex: none;
  width: var(--lateral-ancho);
  padding: var(--sp-3);
  border-right: 1px solid var(--c-border);
  background-color: var(--c-app-bg);
  transition: width var(--dur-base) var(--ease-in-out);
}
.lateral.colapsada {
  width: var(--lateral-ancho-min);
  align-items: center;
}
.lateral.flotante {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 80;
  background-color: var(--c-surface);
}

.marca {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  height: 56px;
  padding-inline: var(--sp-2);
}
.logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--r-sm);
  background-color: var(--c-accent);
  color: var(--c-text-on-fill);
  font-weight: 700;
}
.nombre-app {
  flex: 1 1 auto;
  font-size: var(--t-h3);
  font-weight: 600;
}
.icono-boton {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--r-md);
  background: none;
  color: var(--c-text-2);
  cursor: pointer;
}
.icono-boton:hover {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}

.periodo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-1);
  height: 36px;
  padding-inline: var(--sp-1);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background-color: var(--c-surface);
}
.periodo.compacto {
  flex-direction: column;
  height: auto;
  padding-block: var(--sp-1);
}
.periodo button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: var(--r-sm);
  background: none;
  color: var(--c-text-2);
  cursor: pointer;
}
.periodo button:hover {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}
.etiqueta-periodo {
  flex: 1 1 auto;
  font-size: var(--t-caption);
  font-weight: 600;
  text-align: center;
  white-space: nowrap;
}

.destinos {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1 1 auto;
  margin: 0;
  padding: 0;
  list-style: none;
}
.destino {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  height: 40px;
  padding-inline: var(--sp-3);
  border-left: 3px solid transparent;
  border-radius: var(--r-md);
  color: var(--c-text-2);
  text-decoration: none;
  font-size: var(--t-body);
}
.colapsada .destino {
  justify-content: center;
  width: 40px;
  padding-inline: 0;
}
.destino:hover {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}
.destino.activo {
  background-color: var(--c-surface-3);
  border-left-color: var(--c-accent);
  color: var(--c-text-1);
  font-weight: 600;
}
.destino.activo svg {
  color: var(--c-accent);
}
.destino .texto {
  flex: 1 1 auto;
}
.contador {
  font-size: var(--t-micro);
  color: var(--c-text-3);
}

.pie-lateral {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding-top: var(--sp-2);
  border-top: 1px solid var(--c-border);
}
.usuario {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  min-height: 44px;
  padding: var(--sp-1) var(--sp-2);
  border: 0;
  border-radius: var(--r-md);
  background: none;
  color: var(--c-text-1);
  font-family: inherit;
  cursor: pointer;
  text-align: left;
}
.usuario:hover {
  background-color: var(--c-surface-3);
}
.avatar {
  position: relative;
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  overflow: hidden;
  border: 1px solid var(--hue);
  border-radius: var(--r-full);
  background-color: var(--c-surface-3);
  font-size: var(--t-caption);
  font-weight: 600;
}
.avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.punto-aviso {
  position: absolute;
  top: 0;
  right: 0;
  width: 6px;
  height: 6px;
  border-radius: var(--r-full);
  background-color: var(--c-warning);
}
.datos-usuario {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.nombre {
  font-size: var(--t-sm);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.correo {
  font-size: var(--t-caption);
  color: var(--c-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cabecera-menu {
  padding: var(--sp-2);
}
.cabecera-menu p {
  margin: 0;
}
.tema {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: var(--sp-1) 0;
  border: 0;
  border-top: 1px solid var(--c-border);
}
.tema label {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-height: 32px;
  padding-inline: var(--sp-2);
  border-radius: var(--r-sm);
  font-size: var(--t-sm);
  color: var(--c-text-2);
  cursor: pointer;
}
.tema label:hover {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}
.tema input {
  accent-color: var(--c-accent);
}
.renovar {
  width: 100%;
  min-height: 32px;
  border: 0;
  border-radius: var(--r-sm);
  background-color: var(--c-warning-wash);
  color: var(--c-warning);
  font-family: inherit;
  font-size: var(--t-caption);
  font-weight: 600;
  cursor: pointer;
}
.separador {
  margin: var(--sp-1) 0;
  border: 0;
  border-top: 1px solid var(--c-border);
}

/* --- Contenido ----------------------------------------------------------- */
.principal {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-width: 0;
}
.cabecera-movil {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  height: 56px;
  padding-inline: var(--sp-2);
  border-bottom: 1px solid var(--c-border);
  background-color: var(--c-app-bg);
}
.titulo-movil {
  font-size: var(--t-h3);
  font-weight: 600;
}
.contenido {
  flex: 1 1 auto;
  width: 100%;
  max-width: 1440px;
  margin-inline: auto;
  padding: var(--sp-6);
}
@media (max-width: 767px) {
  .contenido {
    padding: var(--sp-4);
  }
}
.con-barra-inferior .contenido {
  padding-bottom: calc(var(--barra-inferior-alto) + var(--sp-8));
}

/* --- Barra inferior ------------------------------------------------------ */
.barra-inferior {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 40;
  display: flex;
  height: var(--barra-inferior-alto);
  padding-bottom: env(safe-area-inset-bottom);
  border-top: 1px solid var(--c-border);
  background-color: var(--c-surface);
}
.barra-inferior a {
  flex: 1 1 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: var(--c-text-3);
  text-decoration: none;
  font-size: 11px;
}
.barra-inferior a.activo {
  color: var(--c-accent-text);
}
.flotante {
  position: fixed;
  right: var(--sp-4);
  bottom: calc(var(--barra-inferior-alto) + var(--sp-4) + env(safe-area-inset-bottom));
  z-index: 45;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border: 0;
  border-radius: var(--r-full);
  background-color: var(--c-accent);
  color: var(--c-text-on-fill);
  box-shadow: var(--elev-3);
  cursor: pointer;
}

.oculto-visualmente {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>
