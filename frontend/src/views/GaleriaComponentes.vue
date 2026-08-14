<script setup lang="ts">
/**
 * Galería de componentes, en la ruta oculta `/galeria`.
 *
 * No es una pantalla de producto: existe para revisar todos los componentes
 * base en sus estados y en los dos temas sin tener que navegar por la
 * aplicación. No está en la barra lateral a propósito.
 */
import { computed, ref } from 'vue'
import {
  ArrowDownRight,
  ArrowUpRight,
  Download,
  Ellipsis,
  Eye,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-vue-next'
import { dinero, fechaCorta, periodoDe } from '@/lib/formato'
import { useAvisos } from '@/composables/useAvisos'
import LayoutApp from '@/layouts/LayoutApp.vue'
import LayoutAuth from '@/layouts/LayoutAuth.vue'
import BarraBusqueda from '@/components/ui/BarraBusqueda.vue'
import BotonBase from '@/components/ui/BotonBase.vue'
import CajonLateral from '@/components/ui/CajonLateral.vue'
import CampoFecha from '@/components/ui/CampoFecha.vue'
import CampoImporte from '@/components/ui/CampoImporte.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import EsqueletoCarga from '@/components/ui/EsqueletoCarga.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import EtiquetaCategoria from '@/components/ui/EtiquetaCategoria.vue'
import IndicadorProgreso from '@/components/ui/IndicadorProgreso.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import MenuDesplegable from '@/components/ui/MenuDesplegable.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import PaginacionBase from '@/components/ui/PaginacionBase.vue'
import PestanyasBase from '@/components/ui/PestanyasBase.vue'
import PistaAyuda from '@/components/ui/PistaAyuda.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import TablaDatos from '@/components/ui/TablaDatos.vue'

type Vista = 'ui' | 'auth'
const vista = ref<Vista>('ui')

const avisos = useAvisos()

/* --- Estado de los ejemplos --------------------------------------------- */
const periodo = ref(periodoDe())
const ruta = ref('/')
const texto = ref('Mercadona')
const textoVacio = ref('')
const nif = ref('B12345678')
const importe = ref<number | null>(1570)
const importeGrande = ref<number | null>(24500)
const importeVacio = ref<number | null>(null)
const fecha = ref<string | null>('2026-08-13')
const tematica = ref<string | number | null>('vivienda')
const cuenta = ref<string | number | null>(null)
const pestanya = ref<string | number>('resumen')
const busqueda = ref('')
const recurrente = ref(true)
const sinFactura = ref(false)
const pagina = ref(3)
const tamanyoPagina = ref(50)
const modal = ref(false)
const modalError = ref(false)
const cajon = ref(false)
const seleccionadas = ref<Array<string | number>>([2])
const densidad = ref<'comoda' | 'compacta'>('comoda')
const orden = ref<{ clave: string; sentido: 'asc' | 'desc' } | null>({
  clave: 'importe',
  sentido: 'desc',
})

const TEMATICAS = [
  'Vivienda',
  'Alimentación',
  'Transporte',
  'Ocio',
  'Salud',
  'Suscripciones',
  'Ropa',
  'Educación',
  'Mascotas',
  'Regalos',
  'Cuidado personal',
  'Impuestos',
]

const OPCIONES_TEMATICA = TEMATICAS.map((t, i) => ({
  valor: t.toLowerCase().replace(/\s/g, '-'),
  etiqueta: t,
  ranura: i + 1,
  grupo: i < 6 ? 'Más usadas' : 'El resto',
}))

const OPCIONES_CUENTA = [
  { valor: 'corriente', etiqueta: 'Cuenta corriente' },
  { valor: 'ahorro', etiqueta: 'Cuenta de ahorro' },
  { valor: 'tarjeta', etiqueta: 'Tarjeta de crédito', deshabilitada: true },
]

type FilaDemo = {
  id: number
  concepto: string
  comercio: string
  fecha: string
  tematica: string
  ranura: number
  importe: number
  tipo: 'gasto' | 'ingreso'
}

const FILAS: FilaDemo[] = [
  {
    id: 1,
    concepto: 'Compra semanal',
    comercio: 'Mercadona',
    fecha: '2026-08-12',
    tematica: 'Alimentación',
    ranura: 2,
    importe: -8745,
    tipo: 'gasto',
  },
  {
    id: 2,
    concepto: 'Nómina de agosto',
    comercio: 'Acme S. L.',
    fecha: '2026-08-01',
    tematica: 'Ingresos',
    ranura: 5,
    importe: 245000,
    tipo: 'ingreso',
  },
  {
    id: 3,
    concepto: 'Alquiler',
    comercio: 'Inmobiliaria Sur',
    fecha: '2026-08-03',
    tematica: 'Vivienda',
    ranura: 1,
    importe: -85000,
    tipo: 'gasto',
  },
  {
    id: 4,
    concepto: 'Abono transporte',
    comercio: 'CRTM',
    fecha: '2026-08-02',
    tematica: 'Transporte',
    ranura: 3,
    importe: -5460,
    tipo: 'gasto',
  },
]

/** Se declara así, y no importando el tipo del SFC, para no acoplar la galería. */
const COLUMNAS = [
  { clave: 'concepto', etiqueta: 'Concepto', ordenable: true },
  { clave: 'comercio', etiqueta: 'Comercio', ordenable: true, soloEscritorio: true },
  {
    clave: 'fecha',
    etiqueta: 'Fecha',
    ordenable: true,
    ancho: '120px',
    valor: (f: FilaDemo) => fechaCorta(f.fecha),
  },
  { clave: 'tematica', etiqueta: 'Temática' },
  { clave: 'importe', etiqueta: 'Importe', numerica: true, ordenable: true, ancho: '140px' },
]

const filasOrdenadas = computed(() => {
  const o = orden.value
  if (!o) return FILAS
  const signo = o.sentido === 'asc' ? 1 : -1
  return [...FILAS].sort((a, b) => {
    const x = a[o.clave as keyof FilaDemo]
    const y = b[o.clave as keyof FilaDemo]
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * signo
    return String(x).localeCompare(String(y), 'es') * signo
  })
})

const chips = [
  { clave: 'mes', etiqueta: 'Agosto 2026' },
  { clave: 'ali', etiqueta: 'Alimentación', ranura: 2 },
]

const ITEMS_MENU = [
  { clave: 'ver', etiqueta: 'Ver movimientos', icono: Eye, atajo: 'V' },
  { clave: 'editar', etiqueta: 'Cambiar asignación', icono: Pencil },
  { clave: 'exportar', etiqueta: 'Exportar a CSV', icono: Download, deshabilitada: true },
  { clave: 'borrar', etiqueta: 'Eliminar', icono: Trash2, peligrosa: true, separadorAntes: true },
]

const TOKENS_SUPERFICIE = [
  '--c-app-bg',
  '--c-surface',
  '--c-surface-2',
  '--c-surface-3',
  '--c-surface-sunken',
  '--c-border',
  '--c-border-strong',
]
const TOKENS_SEMANTICOS = ['--c-accent', '--c-positive', '--c-negative', '--c-warning', '--c-info']
</script>

<template>
  <LayoutAuth
    v-if="vista === 'auth'"
    titulo="Entra en tu presupuesto"
    subtitulo="Usa el correo con el que te diste de alta."
  >
    <CampoTexto v-model="textoVacio" etiqueta="Correo electrónico" tipo="email" requerido />
    <CampoTexto v-model="nif" etiqueta="Contraseña" tipo="password" requerido />
    <BotonBase variante="primaria" ancho-completo>Entrar</BotonBase>
    <template #pie>
      <BotonBase variante="enlace" @click="vista = 'ui'">Volver a la galería</BotonBase>
    </template>
  </LayoutAuth>

  <LayoutApp
    v-else
    v-model:periodo="periodo"
    :ruta-activa="ruta"
    :usuario="{ nombre: 'Ana Ruiz', correo: 'ana.ruiz@ejemplo.es' }"
    :minutos-de-sesion="4"
    @navegar="(r) => (ruta = r)"
    @anyadir-gasto="modal = true"
    @cerrar-sesion="vista = 'auth'"
  >
    <header class="cabecera-galeria">
      <h1>Galería de componentes</h1>
      <p>
        Provisional: se sustituye por el router. Todos los estados de la
        especificación, en los dos temas.
      </p>
      <BotonBase variante="contorno" tamanyo="sm" @click="vista = 'auth'">
        Ver el layout de autenticación
      </BotonBase>
    </header>

    <!-- Paleta -->
    <section class="bloque">
      <h2>Tokens de color</h2>
      <div class="muestras">
        <div v-for="t in TOKENS_SUPERFICIE" :key="t" class="muestra">
          <span class="tono" :style="{ background: `var(${t})` }" />
          <code>{{ t }}</code>
        </div>
      </div>
      <div class="muestras">
        <div v-for="t in TOKENS_SEMANTICOS" :key="t" class="muestra">
          <span class="tono" :style="{ background: `var(${t})` }" />
          <code>{{ t }}</code>
        </div>
      </div>
      <div class="muestras">
        <div v-for="n in 12" :key="n" class="muestra">
          <span class="tono" :style="{ background: `var(--c-cat-${n})` }" />
          <code>cat-{{ n }}</code>
        </div>
        <div class="muestra">
          <span class="tono" :style="{ background: 'var(--c-cat-other)' }" />
          <code>otros</code>
        </div>
      </div>
      <p class="cifras">
        <span class="hero num num-grande">{{ dinero(245000 / 100) }}</span>
        <span class="positivo num">
          <ArrowUpRight :size="14" aria-hidden="true" />+{{ dinero(1250) }}
        </span>
        <span class="negativo num">
          <ArrowDownRight :size="14" aria-hidden="true" />-{{ dinero(874.5) }}
        </span>
      </p>
    </section>

    <!-- Botones -->
    <section class="bloque">
      <h2>BotonBase</h2>
      <div class="fila-demo">
        <BotonBase variante="primaria">Primaria</BotonBase>
        <BotonBase variante="secundaria">Secundaria</BotonBase>
        <BotonBase variante="fantasma">Fantasma</BotonBase>
        <BotonBase variante="contorno">Contorno</BotonBase>
        <BotonBase variante="peligro">Peligro</BotonBase>
        <BotonBase variante="peligro-fantasma">Peligro fantasma</BotonBase>
        <BotonBase variante="enlace">Enlace</BotonBase>
      </div>
      <div class="fila-demo">
        <BotonBase tamanyo="sm" :icono="Plus">Pequeña</BotonBase>
        <BotonBase tamanyo="md" :icono="Plus" :contador="12">Mediana</BotonBase>
        <BotonBase tamanyo="lg" variante="primaria" :icono="Plus">Grande</BotonBase>
        <BotonBase solo-icono :icono="Plus" etiqueta-accesible="Añadir gasto" />
        <BotonBase cargando variante="primaria">Guardando</BotonBase>
        <BotonBase deshabilitado>Deshabilitada</BotonBase>
      </div>
    </section>

    <!-- Campos -->
    <section class="bloque">
      <h2>Campos de formulario</h2>
      <div class="rejilla">
        <CampoTexto v-model="texto" etiqueta="Comercio" ayuda="Como aparece en el ticket." />
        <CampoTexto v-model="textoVacio" etiqueta="Concepto" placeholder="Compra semanal" requerido />
        <CampoTexto
          v-model="textoVacio"
          etiqueta="Correo"
          tipo="email"
          error="Introduce un correo válido."
        />
        <CampoTexto v-model="texto" etiqueta="Comercio validado" correcto />
        <CampoTexto v-model="texto" etiqueta="Validando IBAN" cargando />
        <CampoTexto v-model="nif" etiqueta="NIF" monoespaciado ayuda="Se compara carácter a carácter." />
        <CampoTexto v-model="texto" etiqueta="Deshabilitado" deshabilitado />
        <CampoTexto v-model="texto" etiqueta="Solo lectura" solo-lectura />
        <CampoTexto v-model="texto" etiqueta="Con contador" contador :max-longitud="40" />
        <CampoImporte v-model="importe" etiqueta="Importe" teclas-rapidas />
        <CampoImporte v-model="importeGrande" etiqueta="Importe destacado" tamanyo="display" />
        <CampoImporte
          v-model="importeVacio"
          etiqueta="Importe con error"
          error="Introduce un importe mayor que 0"
        />
        <CampoImporte v-model="importe" etiqueta="Importe en lectura" solo-lectura />
        <CampoFecha
          v-model="fecha"
          etiqueta="Fecha"
          :dias-con-datos="{ '2026-08-12': 3, '2026-08-03': 1 }"
        />
        <CampoFecha v-model="fecha" etiqueta="Fecha con error" error="Introduce una fecha con el formato 13/08/2026" />
        <SelectorBase v-model="tematica" etiqueta="Temática" :opciones="OPCIONES_TEMATICA" />
        <SelectorBase
          v-model="cuenta"
          etiqueta="Cuenta"
          :opciones="OPCIONES_CUENTA"
          placeholder="Elige una cuenta"
          ayuda="Se recuerda la última usada."
        />
        <SelectorBase
          v-model="cuenta"
          etiqueta="Cuenta con error"
          :opciones="OPCIONES_CUENTA"
          error="Elige una cuenta para continuar."
        />
      </div>
      <div class="fila-demo">
        <InterruptorBase
          v-model="recurrente"
          etiqueta="Solo recurrentes"
          descripcion="Filtra los movimientos que se repiten cada mes."
        />
        <InterruptorBase v-model="sinFactura" etiqueta="Solo sin factura" />
        <InterruptorBase v-model="sinFactura" etiqueta="Deshabilitado" deshabilitado />
      </div>
    </section>

    <!-- Búsqueda -->
    <section class="bloque">
      <h2>BarraBusqueda</h2>
      <BarraBusqueda
        v-model="busqueda"
        :resultados="42"
        :filtros-activos="2"
        :chips="chips"
      />
    </section>

    <!-- Pestañas -->
    <section class="bloque">
      <h2>PestanyasBase</h2>
      <PestanyasBase
        v-model="pestanya"
        etiqueta="Secciones de la temática"
        :pestanyas="[
          { valor: 'resumen', etiqueta: 'Resumen' },
          { valor: 'movimientos', etiqueta: 'Movimientos', contador: 42 },
          { valor: 'productos', etiqueta: 'Productos', contador: 7 },
          { valor: 'ajustes', etiqueta: 'Ajustes', deshabilitada: true },
        ]"
      >
        <p class="parrafo">Contenido de la pestaña «{{ pestanya }}».</p>
      </PestanyasBase>
    </section>

    <!-- Chips y pistas -->
    <section class="bloque">
      <h2>EtiquetaCategoria y PistaAyuda</h2>
      <div class="fila-demo">
        <EtiquetaCategoria
          v-for="(t, i) in TEMATICAS"
          :key="t"
          :nombre="t"
          :ranura="i + 1"
        />
        <EtiquetaCategoria nombre="Otros (7)" :ranura="0" />
      </div>
      <div class="fila-demo">
        <EtiquetaCategoria nombre="Fruta" madre="Alimentación" :ranura="2" :nivel="1" />
        <EtiquetaCategoria nombre="Alimentación" :ranura="2" eliminable />
        <EtiquetaCategoria nombre="Ocio" :ranura="4" seleccionable seleccionada />
        <EtiquetaCategoria nombre="Salud" :ranura="5" seleccionable />
        <EtiquetaCategoria nombre="Compacta" :ranura="8" tamanyo="sm" />
        <PistaAyuda texto="El porcentaje es del total del presupuesto, no del segmento.">
          <BotonBase variante="fantasma" tamanyo="sm">Pásame el puntero</BotonBase>
        </PistaAyuda>
        <MenuDesplegable etiqueta="Acciones de la temática" :items="ITEMS_MENU">
          <template #disparador="{ alternar, atributos }">
            <BotonBase
              v-bind="atributos"
              variante="secundaria"
              tamanyo="sm"
              :icono="Ellipsis"
              @click="alternar()"
            >
              Acciones
            </BotonBase>
          </template>
        </MenuDesplegable>
      </div>
    </section>

    <!-- Progreso y esqueletos -->
    <section class="bloque">
      <h2>IndicadorProgreso y EsqueletoCarga</h2>
      <div class="rejilla">
        <IndicadorProgreso etiqueta="Alimentación" :valor="74" mostrar-texto />
        <IndicadorProgreso etiqueta="Vivienda" :valor="112" tono="negative" mostrar-texto />
        <IndicadorProgreso etiqueta="Ahorro" :valor="38" tono="positive" mostrar-texto />
        <IndicadorProgreso
          etiqueta="Subiendo la factura"
          indeterminado
          estado="Analizando la página 2 de 5"
        />
      </div>
      <div class="rejilla">
        <EsqueletoCarga variante="texto" :lineas="3" />
        <EsqueletoCarga variante="importe" />
        <EsqueletoCarga variante="avatar" />
        <EsqueletoCarga variante="bloque" alto="44px" />
      </div>
    </section>

    <!-- Tabla -->
    <section class="bloque">
      <h2>TablaDatos</h2>
      <TablaDatos
        v-model:densidad="densidad"
        v-model:orden="orden"
        v-model:seleccionadas="seleccionadas"
        titulo="Movimientos de agosto de 2026"
        titulo-oculto
        :columnas="COLUMNAS"
        :filas="filasOrdenadas"
        :clave-fila="(f) => f.id"
        expandible
        seleccionables
        rotulo-totales="Total de 4 resultados filtrados"
      >
        <template #herramientas>
          <span class="rotulo">4 movimientos · filtro: agosto de 2026</span>
        </template>
        <template #celda-tematica="{ fila }">
          <EtiquetaCategoria :nombre="fila.tematica" :ranura="fila.ranura" tamanyo="sm" />
        </template>
        <template #celda-importe="{ fila }">
          <span :class="fila.tipo === 'ingreso' ? 'positivo' : 'negativo'">
            {{ dinero(fila.importe / 100, { signoSiempre: true }) }}
          </span>
        </template>
        <template #detalle="{ fila }">
          <p class="parrafo">
            {{ fila.concepto }} en {{ fila.comercio }}, {{ fechaCorta(fila.fecha) }}.
          </p>
        </template>
      </TablaDatos>

      <h3>Cargando · vacío por filtro · error</h3>
      <TablaDatos
        titulo="Movimientos cargando"
        titulo-oculto
        :columnas="COLUMNAS"
        :filas="[]"
        :clave-fila="(f) => f.id"
        cargando
      />
      <TablaDatos
        titulo="Movimientos sin resultados"
        titulo-oculto
        :columnas="COLUMNAS"
        :filas="[]"
        :clave-fila="(f) => f.id"
        vacio-por-filtro
      />
      <TablaDatos
        titulo="Movimientos con error"
        titulo-oculto
        :columnas="COLUMNAS"
        :filas="[]"
        :clave-fila="(f) => f.id"
        error="No se han podido cargar los movimientos."
      />

      <PaginacionBase
        v-model:pagina="pagina"
        v-model:tamanyo-pagina="tamanyoPagina"
        :total="1284"
        unidad="movimientos"
      />
    </section>

    <!-- Vacíos -->
    <section class="bloque">
      <h2>EstadoVacio</h2>
      <div class="rejilla">
        <div class="tarjeta caja">
          <EstadoVacio
            titulo="Aún no hay facturas"
            descripcion="Sube un PDF y se extraerán los productos y los precios."
          >
            <template #accion><BotonBase variante="primaria">Subir factura</BotonBase></template>
          </EstadoVacio>
        </div>
        <div class="tarjeta caja">
          <EstadoVacio
            tipo="sin-filtros"
            titulo="Ningún resultado con estos filtros"
            criterio="Agosto 2026 · Alimentación · más de 50,00 €"
          >
            <template #accion><BotonBase variante="contorno">Quitar filtros</BotonBase></template>
          </EstadoVacio>
        </div>
        <div class="tarjeta caja">
          <EstadoVacio tipo="sin-busqueda" titulo="Sin resultados" criterio="«mercadonna»" />
        </div>
        <div class="tarjeta caja">
          <EstadoVacio
            tipo="error"
            titulo="No se ha podido cargar"
            descripcion="El servidor ha tardado demasiado en responder."
          >
            <template #accion><BotonBase variante="contorno">Reintentar</BotonBase></template>
          </EstadoVacio>
        </div>
      </div>
    </section>

    <!-- Capas -->
    <section class="bloque">
      <h2>Capas flotantes y avisos</h2>
      <div class="fila-demo">
        <BotonBase variante="secundaria" @click="modal = true">Abrir modal</BotonBase>
        <BotonBase
          variante="secundaria"
          @click="
            () => {
              modalError = true
              modal = true
            }
          "
        >
          Modal con error
        </BotonBase>
        <BotonBase variante="secundaria" @click="cajon = true">Abrir cajón lateral</BotonBase>
        <BotonBase variante="secundaria" @click="avisos.exito('Gasto guardado.')">
          Aviso de éxito
        </BotonBase>
        <BotonBase
          variante="secundaria"
          @click="
            avisos.info('Presupuesto reasignado. 70,00 € de Vivienda a Ahorro.', {
              accion: { etiqueta: 'Deshacer', alPulsar: () => avisos.exito('Deshecho.') },
            })
          "
        >
          Aviso con acción
        </BotonBase>
        <BotonBase variante="secundaria" @click="avisos.aviso('Ya usas los 12 colores.')">
          Aviso
        </BotonBase>
        <BotonBase
          variante="secundaria"
          @click="avisos.error('No se ha podido guardar el gasto.')"
        >
          Error
        </BotonBase>
      </div>
    </section>

    <ModalBase
      v-model:abierto="modal"
      titulo="Añadir gasto"
      subtitulo="Agosto de 2026"
      :error="modalError ? 'Revisa el importe: no puede ser 0,00 €.' : undefined"
      @cerrar="modalError = false"
    >
      <div class="rejilla">
        <CampoImporte v-model="importeVacio" etiqueta="Importe" tamanyo="display" teclas-rapidas />
        <SelectorBase v-model="tematica" etiqueta="Temática" :opciones="OPCIONES_TEMATICA" />
        <CampoFecha v-model="fecha" etiqueta="Fecha" />
        <CampoTexto v-model="textoVacio" etiqueta="Concepto" />
      </div>
      <template #pie>
        <BotonBase variante="contorno" @click="modal = false">Cancelar</BotonBase>
        <BotonBase variante="primaria" @click="modal = false">Guardar</BotonBase>
      </template>
    </ModalBase>

    <CajonLateral
      v-model:abierto="cajon"
      titulo="Compra semanal"
      subtitulo="Mercadona · 12 ago 2026"
      con-navegacion
      hay-anterior
      hay-siguiente
    >
      <p class="parrafo">
        Detalle del movimiento. El panel no bloquea el fondo en escritorio y pasa a hoja
        inferior en móvil.
      </p>
      <template #pie>
        <BotonBase variante="peligro-fantasma" :icono="Trash2">Eliminar</BotonBase>
        <BotonBase variante="primaria">Guardar</BotonBase>
      </template>
    </CajonLateral>
  </LayoutApp>
</template>

<style scoped>
.cabecera-galeria {
  margin-bottom: var(--sp-8);
}
.cabecera-galeria h1 {
  margin: 0;
  font-size: var(--t-h1);
  line-height: var(--t-h1-lh);
  font-weight: 600;
}
.cabecera-galeria p {
  margin: var(--sp-2) 0 var(--sp-3);
  max-width: 68ch;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}

.bloque {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  margin-bottom: var(--sp-12);
  padding-top: var(--sp-5);
  border-top: 1px solid var(--c-border);
}
.bloque h2 {
  margin: 0;
  font-size: var(--t-h2);
  line-height: var(--t-h2-lh);
  font-weight: 600;
}
.bloque h3 {
  margin: var(--sp-4) 0 0;
  font-size: var(--t-h3);
  font-weight: 600;
  color: var(--c-text-2);
}

.fila-demo {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-3);
}
.rejilla {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--sp-4);
  align-items: start;
}
.caja {
  padding: var(--sp-4);
}
.parrafo {
  margin: 0;
  max-width: 68ch;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.rotulo {
  font-size: var(--t-caption);
  color: var(--c-text-3);
}

.muestras {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
}
.muestra {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.tono {
  display: block;
  width: 72px;
  height: 32px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
}
code {
  font-family: var(--font-mono);
  font-size: var(--t-micro);
  color: var(--c-text-3);
}

.cifras {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--sp-4);
  margin: 0;
}
.hero {
  font-size: var(--t-hero);
  line-height: var(--t-hero-lh);
  font-weight: 600;
}
.positivo {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  color: var(--c-positive);
  font-weight: 600;
}
.negativo {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  color: var(--c-negative);
  font-weight: 600;
}
</style>
