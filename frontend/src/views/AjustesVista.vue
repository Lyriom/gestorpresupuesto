<script setup lang="ts">
/**
 * Ajustes (§2.13): lista de secciones a la izquierda y panel a la derecha.
 *
 * «Guardar cambios» solo aparece cuando hay algo sin guardar, y la zona de
 * peligro va siempre al final y separada. La verificación en dos pasos no está:
 * la API no la publica, y un interruptor que no hace nada engaña.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Download, Upload } from 'lucide-vue-next'

import { apiAuth } from '@/api/auth'
import BotonBase from '@/components/ui/BotonBase.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import { useAvisos } from '@/composables/useAvisos'
import { useTema, type PreferenciaTema } from '@/composables/useTema'
import { configurarFormato, nombreMoneda, porcentaje, tiempoRelativo } from '@/lib/formato'
import { SECCIONES_AJUSTES, useAjustes, type SeccionAjustes } from '@/stores/ajustes'
import { mensajeDeError } from '@/stores/comun'
import { useSesion } from '@/stores/sesion'
import BloqueError from './componentes/BloqueError.vue'

const route = useRoute()
const router = useRouter()
const sesion = useSesion()
const ajustes = useAjustes()
const avisos = useAvisos()
const { preferencia, establecer, opciones: opcionesTema } = useTema()

const seccion = ref<SeccionAjustes>('perfil')

// --- Perfil ---
const nombre = ref('')
const correo = ref('')
const nombreOriginal = ref('')
const correoOriginal = ref('')

const hayCambiosPerfil = computed(
  () => nombre.value !== nombreOriginal.value || correo.value !== correoOriginal.value,
)

// --- Cambio de contraseña ---
const modalContrasenya = ref(false)
const actual = ref('')
const nueva = ref('')
const repetida = ref('')
const errorRepetida = ref<string | null>(null)

// --- Borrado de cuenta ---
const modalBorrado = ref(false)
const confirmacion = ref('')
const contrasenyaBorrado = ref('')

const borrando = ref(false)
const errorBorrado = ref<string | null>(null)

const puedeBorrar = computed(
  () => confirmacion.value === 'ELIMINAR' && contrasenyaBorrado.value.length > 0,
)

async function borrarCuenta(): Promise<void> {
  borrando.value = true
  errorBorrado.value = null
  try {
    await apiAuth.borrarCuenta(contrasenyaBorrado.value)
    sesion.olvidar()
    void router.replace({ name: 'entrar' })
  } catch (e) {
    errorBorrado.value = mensajeDeError(e, 'No se ha podido eliminar la cuenta.')
  } finally {
    borrando.value = false
  }
}

/**
 * Las monedas que sabe escribir el backend (`services/formato.py`). La etiqueta
 * la pone `Intl` con el nombre en el idioma en uso, para no escribir a mano
 * «dólar estadounidense» y que luego no cuadre con lo que pinta la interfaz.
 */
const opcionesMoneda = ['USD', 'EUR', 'GBP', 'MXN', 'COP', 'ARS', 'CLP', 'PEN'].map(
  (codigo) => ({ valor: codigo, etiqueta: `${codigo} — ${nombreMoneda(codigo)}` }),
)

/**
 * Cambiar la moneda tiene que verse **en el momento**, sin recargar: el símbolo
 * está en cada importe de cada pantalla. Se guarda y se reconfigura el formateo.
 */
async function cambiarMoneda(codigo: string): Promise<void> {
  if (!(await ajustes.guardar({ currency: codigo }))) return
  configurarFormato({ moneda: codigo })
  avisos.exito(`Moneda cambiada a ${nombreMoneda(codigo)}.`)
}

const opcionesArrastre = [
  { valor: 'carry', etiqueta: 'Arrastrarlo al mes siguiente' },
  { valor: 'reset', etiqueta: 'Dejarlo a cero' },
]

const opcionesDigest = [
  { valor: 'off', etiqueta: 'No enviar resumen' },
  { valor: 'weekly', etiqueta: 'Cada semana' },
  { valor: 'monthly', etiqueta: 'Cada mes' },
]

function volcarPerfil(): void {
  nombre.value = sesion.usuario?.name ?? ''
  correo.value = sesion.usuario?.email ?? ''
  nombreOriginal.value = nombre.value
  correoOriginal.value = correo.value
}

async function guardarPerfil(): Promise<void> {
  const ok = await sesion.guardarPerfil({ name: nombre.value.trim(), email: correo.value.trim() })
  if (!ok) return
  volcarPerfil()
  avisos.exito('Cambios guardados.')
}

async function guardarContrasenya(): Promise<void> {
  errorRepetida.value = null
  if (nueva.value !== repetida.value) {
    errorRepetida.value = 'Las contraseñas no coinciden.'
    return
  }
  const ok = await sesion.cambiarContrasenya(actual.value, nueva.value)
  if (!ok) return
  actual.value = ''
  nueva.value = ''
  repetida.value = ''
  modalContrasenya.value = false
  avisos.exito('Contraseña cambiada. Se han cerrado las demás sesiones.')
}

async function cerrarOtraSesion(id: string, etiqueta: string): Promise<void> {
  try {
    await sesion.revocarSesion(id)
    avisos.exito(`Sesión cerrada en «${etiqueta}».`)
  } catch {
    avisos.error('No se ha podido cerrar la sesión en ese dispositivo.')
  }
}

function cambiarSeccion(nueva_: SeccionAjustes): void {
  seccion.value = nueva_
  void router.replace({ query: { ...route.query, seccion: nueva_ } })
  if (nueva_ === 'sesion') void sesion.cargarSesiones()
  if (nueva_ === 'datos') void ajustes.cargarAlmacenamiento()
}

onMounted(() => {
  const pedida = route.query.seccion
  if (typeof pedida === 'string' && SECCIONES_AJUSTES.some((s) => s.valor === pedida)) {
    seccion.value = pedida as SeccionAjustes
  }
  volcarPerfil()
  void ajustes.cargar()
  if (seccion.value === 'sesion') void sesion.cargarSesiones()
  if (seccion.value === 'datos') void ajustes.cargarAlmacenamiento()
})

watch(() => sesion.usuario?.id, volcarPerfil)
</script>

<template>
  <div class="vista">
    <h1 class="titulo">Ajustes</h1>

    <div class="disposicion">
      <nav class="secciones" aria-label="Secciones de ajustes">
        <ul>
          <li v-for="s in SECCIONES_AJUSTES" :key="s.valor">
            <button
              type="button"
              class="seccion"
              :class="{ activa: seccion === s.valor }"
              :aria-current="seccion === s.valor ? 'true' : undefined"
              @click="cambiarSeccion(s.valor)"
            >
              {{ s.etiqueta }}
            </button>
          </li>
        </ul>
      </nav>

      <div class="panel tarjeta">
        <!-- Perfil y seguridad -->
        <section v-if="seccion === 'perfil'" aria-labelledby="t-perfil">
          <h2 id="t-perfil" class="titulo-seccion">Perfil y seguridad</h2>

          <div v-if="!sesion.usuario" class="caja">
            <EsqueletoCarga variante="texto" :lineas="4" anuncio="Cargando el perfil" />
          </div>

          <template v-else>
            <div class="campos">
              <CampoTexto v-model="nombre" etiqueta="Nombre" autocompletar="name" />
              <CampoTexto v-model="correo" etiqueta="Correo electrónico" tipo="email" />
              <div class="linea">
                <span class="rotulo">Contraseña</span>
                <span class="valor">••••••••</span>
                <BotonBase variante="enlace" tamanyo="sm" @click="modalContrasenya = true">
                  Cambiar contraseña
                </BotonBase>
              </div>
            </div>

            <p v-if="sesion.error" class="banda-error" role="alert">{{ sesion.error }}</p>

            <footer v-if="hayCambiosPerfil" class="pie">
              <BotonBase variante="primaria" :cargando="sesion.enviando" @click="guardarPerfil">
                Guardar cambios
              </BotonBase>
            </footer>
          </template>
        </section>

        <!-- Preferencias -->
        <section v-else-if="seccion === 'preferencias'" aria-labelledby="t-pref">
          <h2 id="t-pref" class="titulo-seccion">Preferencias</h2>

          <div class="campos">
            <SelectorBase
              :model-value="preferencia"
              etiqueta="Tema de la interfaz"
              :opciones="opcionesTema.map((o) => ({ valor: o.valor, etiqueta: o.etiqueta }))"
              @update:model-value="establecer(String($event) as PreferenciaTema)"
            />

            <template v-if="ajustes.ajustes">
              <SelectorBase
                :model-value="ajustes.ajustes.currency"
                etiqueta="Moneda"
                ayuda="Cambia el símbolo de toda la aplicación. No convierte los importes ya guardados."
                :opciones="opcionesMoneda"
                @update:model-value="cambiarMoneda(String($event))"
              />
              <SelectorBase
                :model-value="ajustes.ajustes.rollover_negative"
                etiqueta="Qué hacer con el sobregasto al cerrar el mes"
                :opciones="opcionesArrastre"
                @update:model-value="
                  ajustes.guardar({ rollover_negative: $event === 'reset' ? 'reset' : 'carry' })
                "
              />
              <InterruptorBase
                :model-value="ajustes.ajustes.rollover_default"
                etiqueta="Arrastrar por defecto lo que sobre en cada temática"
                @update:model-value="ajustes.guardar({ rollover_default: $event })"
              />
            </template>

            <div v-else-if="ajustes.cargando" class="caja">
              <EsqueletoCarga variante="texto" :lineas="3" anuncio="Cargando las preferencias" />
            </div>
            <BloqueError
              v-else-if="ajustes.error"
              titulo="No se han podido cargar los ajustes"
              @reintentar="ajustes.cargar(true)"
            />
          </div>
        </section>

        <!-- Notificaciones y avisos -->
        <section v-else-if="seccion === 'avisos'" aria-labelledby="t-avisos">
          <h2 id="t-avisos" class="titulo-seccion">Notificaciones y avisos</h2>

          <div v-if="ajustes.ajustes" class="campos">
            <SelectorBase
              :model-value="ajustes.ajustes.digest"
              etiqueta="Resumen por correo"
              :opciones="opcionesDigest"
              @update:model-value="
                ajustes.guardar({
                  digest: $event === 'weekly' ? 'weekly' : $event === 'monthly' ? 'monthly' : 'off',
                })
              "
            />
            <p class="ayuda num">
              Aviso de presupuesto al
              {{ porcentaje(ajustes.ajustes.budget_alert_pct, 0) }} consumido · aviso de subida
              de precio a partir de +{{ porcentaje(ajustes.ajustes.price_increase_pct / 100, 0) }} · duplicados en una
              ventana de {{ ajustes.ajustes.duplicate_window_days }} días.
            </p>
          </div>
          <div v-else-if="ajustes.cargando" class="caja">
            <EsqueletoCarga variante="texto" :lineas="3" anuncio="Cargando los avisos" />
          </div>
          <BloqueError
            v-else
            titulo="No se han podido cargar los avisos"
            @reintentar="ajustes.cargar(true)"
          />
        </section>

        <!-- Datos -->
        <section v-else-if="seccion === 'datos'" aria-labelledby="t-datos">
          <h2 id="t-datos" class="titulo-seccion">Datos</h2>

          <div class="campos">
            <div class="linea">
              <span class="rotulo">Exportar todos tus datos</span>
              <BotonBase
                variante="secundaria"
                tamanyo="sm"
                :icono="Download"
                href="/api/v1/exports/quick?entity=transactions&format=csv"
              >
                Exportar
              </BotonBase>
            </div>
            <div class="linea">
              <span class="rotulo">Importar movimientos desde un fichero</span>
              <BotonBase
                variante="secundaria"
                tamanyo="sm"
                :icono="Upload"
                @click="router.push({ name: 'importaciones' })"
              >
                Importar
              </BotonBase>
            </div>
            <p class="ayuda">
              La importación de extractos (CSV, OFX y QIF) tiene su propio flujo: se revisa fila a
              fila antes de crear nada y el lote se puede deshacer entero.
            </p>

            <p v-if="ajustes.almacenamiento" class="ayuda num">
              Facturas y adjuntos ocupan
              {{ Math.round(ajustes.almacenamiento.total_bytes / 1024 / 1024) }} MB en
              {{ ajustes.almacenamiento.files_count }} ficheros.
            </p>
          </div>

          <div class="peligro">
            <h3 class="titulo-peligro">Zona de peligro</h3>
            <p class="ayuda">
              Eliminar tu cuenta borra movimientos, facturas, temáticas y cuentas. No se puede
              deshacer.
            </p>
            <BotonBase variante="peligro" @click="modalBorrado = true">
              Eliminar mi cuenta
            </BotonBase>
          </div>
        </section>

        <!-- Sesión -->
        <section v-else aria-labelledby="t-sesion">
          <h2 id="t-sesion" class="titulo-seccion">Sesión</h2>

          <div v-if="sesion.cargando && sesion.sesiones.length === 0" class="caja">
            <EsqueletoCarga variante="texto" :lineas="3" anuncio="Cargando los dispositivos" />
          </div>

          <ul v-else class="dispositivos">
            <li v-for="s in sesion.sesiones" :key="s.id">
              <span class="rotulo">
                {{ s.is_current ? 'Este dispositivo' : (s.user_agent ?? 'Dispositivo desconocido') }}
              </span>
              <span class="ayuda">{{ tiempoRelativo(s.last_used_at) }}</span>
              <span v-if="s.is_current" class="ayuda">(Es este)</span>
              <BotonBase
                v-else
                variante="fantasma"
                tamanyo="sm"
                @click="cerrarOtraSesion(s.id, s.user_agent ?? 'ese dispositivo')"
              >
                Cerrar sesión
              </BotonBase>
            </li>
            <li v-if="sesion.sesiones.length === 0" class="ayuda">Este dispositivo</li>
          </ul>
        </section>
      </div>
    </div>

    <!-- Cambiar contraseña -->
    <ModalBase
      v-model:abierto="modalContrasenya"
      titulo="Cambiar contraseña"
      tamanyo="sm"
      :guardando="sesion.enviando"
      :error="sesion.error ?? undefined"
      @cerrar="modalContrasenya = false"
    >
      <div class="campos">
        <CampoTexto v-model="actual" etiqueta="Contraseña actual" tipo="password" requerido />
        <CampoTexto
          v-model="nueva"
          etiqueta="Nueva contraseña"
          tipo="password"
          ayuda="Mínimo 10 caracteres, con letras y números"
          requerido
        />
        <CampoTexto
          v-model="repetida"
          etiqueta="Repite la nueva contraseña"
          tipo="password"
          :error="errorRepetida ?? undefined"
          requerido
        />
      </div>
      <template #pie>
        <BotonBase variante="contorno" @click="modalContrasenya = false">Cancelar</BotonBase>
        <BotonBase variante="primaria" :cargando="sesion.enviando" @click="guardarContrasenya">
          Guardar
        </BotonBase>
      </template>
    </ModalBase>

    <!-- Eliminar cuenta -->
    <ModalBase
      v-model:abierto="modalBorrado"
      titulo="Eliminar mi cuenta"
      tamanyo="sm"
      :guardando="borrando"
      :error="errorBorrado ?? undefined"
      @cerrar="modalBorrado = false"
    >
      <p class="ayuda">
        Esto elimina todos tus datos: movimientos, facturas, temáticas y cuentas. No se puede
        deshacer. Escribe <strong>ELIMINAR</strong> para confirmar.
      </p>
      <div class="campos">
        <CampoTexto v-model="confirmacion" etiqueta="Escribe ELIMINAR" monoespaciado />
        <CampoTexto v-model="contrasenyaBorrado" etiqueta="Tu contraseña" tipo="password" />
      </div>
      <template #pie>
        <BotonBase variante="contorno" @click="modalBorrado = false">Cancelar</BotonBase>
        <BotonBase
          variante="peligro"
          :cargando="borrando"
          :deshabilitado="!puedeBorrar"
          @click="borrarCuenta"
        >
          Eliminar mi cuenta
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
.titulo {
  margin: 0;
  font-size: var(--t-h1);
  line-height: var(--t-h1-lh);
  font-weight: 600;
}
.disposicion {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: var(--sp-5);
  align-items: start;
}
@media (max-width: 767px) {
  .disposicion {
    grid-template-columns: minmax(0, 1fr);
  }
}

.secciones ul {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.seccion {
  width: 100%;
  min-height: 44px;
  padding-inline: var(--sp-3);
  border: 0;
  border-left: 3px solid transparent;
  border-radius: var(--r-md);
  background: none;
  color: var(--c-text-2);
  font: inherit;
  font-size: var(--t-sm);
  text-align: left;
  cursor: pointer;
}
.seccion:hover {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}
.seccion.activa {
  background-color: var(--c-surface-3);
  border-left-color: var(--c-accent);
  color: var(--c-text-1);
  font-weight: 600;
}

.panel {
  padding: var(--sp-5);
}
.titulo-seccion {
  margin: 0 0 var(--sp-4);
  padding-bottom: var(--sp-3);
  border-bottom: 1px solid var(--c-border);
  font-size: var(--t-h2);
  font-weight: 600;
}
.campos {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.linea {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3);
  min-height: 44px;
}
.rotulo {
  flex: 1 1 auto;
  font-size: var(--t-sm);
  font-weight: 500;
}
.valor {
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.ayuda {
  margin: 0;
  font-size: var(--t-caption);
  color: var(--c-text-3);
}
.caja {
  padding: var(--sp-3) 0;
}
.pie {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--sp-5);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--c-border);
}
.banda-error {
  margin: var(--sp-3) 0 0;
  padding: var(--sp-3);
  border-radius: var(--r-md);
  background-color: var(--c-negative-wash);
  color: var(--c-negative);
  font-size: var(--t-sm);
}

.peligro {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-2);
  margin-top: var(--sp-8);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--c-negative);
}
.titulo-peligro {
  margin: 0;
  font-size: var(--t-h3);
  font-weight: 600;
  color: var(--c-negative);
}

.dispositivos {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.dispositivos li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3);
  min-height: 44px;
  font-size: var(--t-sm);
}
.dispositivos li + li {
  border-top: 1px solid var(--c-border-soft);
}
</style>
