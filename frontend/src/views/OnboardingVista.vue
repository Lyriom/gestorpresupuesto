<script setup lang="ts">
/**
 * Asistente inicial en tres pasos (§2.2).
 *
 * Obligatorio y secuencial: no se salta a un paso sin completar el anterior, sí
 * se puede volver atrás. Nada se pierde por un fallo de red: lo tecleado se
 * queda en el formulario y solo aparece el error con «Reintentar».
 *
 * Qué llama cada paso:
 * 1. `POST /onboarding/seed` con las cuentas y el preset de temáticas.
 * 2. `PUT /budgets/{periodo}` con `planned_income`, que es el 100 % de la barra
 *    (F-01), más un recurrente de ingreso por cada línea marcada.
 * 3. `PUT /budgets/{periodo}/allocations` con el reparto y
 *    `POST /onboarding/complete`.
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Check, Plus, X } from 'lucide-vue-next'

import { apiCategorias } from '@/api/categorias'
import { apiCuentas, ETIQUETA_TIPO_CUENTA, TIPOS_CUENTA, type TipoCuenta } from '@/api/cuentas'
import { importeDeCentimos } from '@/api/comun'
import { apiPresupuestos, type AsignacionCrear } from '@/api/presupuestos'
import { apiRecurrentes } from '@/api/recurrentes'
import BotonBase from '@/components/ui/BotonBase.vue'
import CampoImporte from '@/components/ui/CampoImporte.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import EtiquetaCategoria from '@/components/ui/EtiquetaCategoria.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import AvisoFlotante from '@/components/ui/AvisoFlotante.vue'
import { useAvisos } from '@/composables/useAvisos'
import {
  dinero,
  etiquetaPeriodo,
  granularidadDe,
  periodoDe,
  rangoDePeriodo,
} from '@/lib/formato'
import { ranuraDeCategoria, useCategorias } from '@/stores/categorias'
import { mensajeDeError } from '@/stores/comun'
import { useSesion } from '@/stores/sesion'

const router = useRouter()
const sesion = useSesion()
const categorias = useCategorias()
const avisos = useAvisos()

const periodo = computed(() => sesion.periodoActual || periodoDe())
const porSemanas = computed(() => granularidadDe(periodo.value) === 'week')

/**
 * Cómo se nombra el periodo dentro de una frase.
 *
 * En un mes basta con la etiqueta —«ingresos de agosto de 2026»—, pero con el rango
 * de una semana la preposición no cuadra: «ingresos de 10 – 16 de ago» no se dice.
 * Va entre paréntesis, que es lo único que funciona igual de bien con las dos.
 */
const nombrePeriodo = computed(() =>
  porSemanas.value
    ? `la semana (${etiquetaPeriodo(periodo.value)})`
    : etiquetaPeriodo(periodo.value).toLowerCase(),
)

/** El primer día del periodo en ISO, que es cuando arranca el ingreso recurrente. */
const inicioDelPeriodo = computed(() => {
  const rango = rangoDePeriodo(periodo.value)
  const dia = rango ? rango[0] : new Date()
  const mes = String(dia.getMonth() + 1).padStart(2, '0')
  return `${dia.getFullYear()}-${mes}-${String(dia.getDate()).padStart(2, '0')}`
})

const paso = ref<1 | 2 | 3>(1)
const enviando = ref(false)
const error = ref<string | null>(null)
const preparando = ref(false)

/* --- Paso 1 · cuentas --------------------------------------------------- */

interface CuentaNueva {
  clave: number
  nombre: string
  tipo: TipoCuenta
  centimos: number | null
  fallida?: boolean
}

let contadorCuenta = 0
function cuentaEnBlanco(): CuentaNueva {
  contadorCuenta += 1
  return { clave: contadorCuenta, nombre: '', tipo: 'checking', centimos: null }
}

const cuentasNuevas = ref<CuentaNueva[]>([cuentaEnBlanco()])
const cuentasCreadas = ref<Array<{ id: string; nombre: string; saldo: string }>>([])

const opcionesTipo = TIPOS_CUENTA.map((t) => ({ valor: t, etiqueta: ETIQUETA_TIPO_CUENTA[t] }))

function cambiarTipo(cuenta: CuentaNueva, valor: string | number | null): void {
  if (typeof valor === 'string') cuenta.tipo = valor as TipoCuenta
}

function retroceder(): void {
  if (paso.value === 3) paso.value = 2
  else if (paso.value === 2) paso.value = 1
}

const cuentasValidas = computed(() => cuentasNuevas.value.filter((c) => c.nombre.trim().length > 0))
const puedeSalirDelPaso1 = computed(
  () => cuentasValidas.value.length > 0 || cuentasCreadas.value.length > 0,
)

/* --- Paso 2 · ingresos --------------------------------------------------- */

interface IngresoNuevo {
  clave: number
  concepto: string
  centimos: number | null
  recurrente: boolean
}

let contadorIngreso = 0
function ingresoEnBlanco(): IngresoNuevo {
  contadorIngreso += 1
  return { clave: contadorIngreso, concepto: '', centimos: null, recurrente: true }
}

const ingresos = ref<IngresoNuevo[]>([ingresoEnBlanco()])
const totalIngresosCentimos = computed(() =>
  ingresos.value.reduce((suma, i) => suma + (i.centimos ?? 0), 0),
)
const puedeSalirDelPaso2 = computed(() => totalIngresosCentimos.value > 0)

/* --- Paso 3 · temáticas y reparto --------------------------------------- */

const elegidas = ref<Set<string>>(new Set())
const asignado = ref<Record<string, number | null>>({})

const sugeridas = computed(() =>
  categorias.arbol.filter((c) => c.kind === 'expense' && !c.is_archived).slice(0, 12),
)

const repartidoCentimos = computed(() =>
  [...elegidas.value].reduce((suma, id) => suma + (asignado.value[id] ?? 0), 0),
)
const sinAsignarCentimos = computed(() => totalIngresosCentimos.value - repartidoCentimos.value)

function alternarTematica(id: string): void {
  const copia = new Set(elegidas.value)
  if (copia.has(id)) copia.delete(id)
  else copia.add(id)
  elegidas.value = copia
}

const elegidasEnOrden = computed(() => sugeridas.value.filter((c) => elegidas.value.has(c.id)))

/* --- Navegación --------------------------------------------------------- */

async function irAlPaso2(): Promise<void> {
  enviando.value = true
  error.value = null
  try {
    // La siembra crea el juego inicial de temáticas y las cuentas de golpe.
    if (cuentasCreadas.value.length === 0) {
      await sesion.sembrar({
        preset: 'es_basico',
        accounts: cuentasValidas.value.map((c) => ({
          name: c.nombre.trim(),
          type: c.tipo,
          // Sin `currency`: el backend la pone del hogar. Estaba fija en 'EUR' y
          // creaba las cuentas en euros aunque la instalación fuese en dólares.
          initial_balance: importeDeCentimos(c.centimos) ?? '0.00',
        })),
      })
    } else {
      // Vuelta al paso 1 tras haber sembrado: las nuevas se crean una a una.
      for (const c of cuentasValidas.value) {
        await apiCuentas.crear({
          name: c.nombre.trim(),
          type: c.tipo,
          initial_balance: importeDeCentimos(c.centimos) ?? '0.00',
        })
      }
    }
    const pagina = await apiCuentas.listar({ size: 50 })
    cuentasCreadas.value = pagina.items.map((c) => ({
      id: c.id,
      nombre: c.name,
      saldo: c.current_balance,
    }))
    cuentasNuevas.value = [cuentaEnBlanco()]
    paso.value = 2
  } catch (e) {
    error.value = mensajeDeError(
      e,
      `No se ha podido guardar «${cuentasValidas.value[0]?.nombre ?? 'la cuenta'}». Inténtalo otra vez.`,
    )
  } finally {
    enviando.value = false
  }
}

async function irAlPaso3(): Promise<void> {
  enviando.value = true
  error.value = null
  try {
    await apiPresupuestos.guardarAjustes(periodo.value, {
      planned_income: importeDeCentimos(totalIngresosCentimos.value),
    })
    const cuentaPrincipal = cuentasCreadas.value[0]?.id
    if (cuentaPrincipal) {
      for (const ingreso of ingresos.value) {
        if (!ingreso.recurrente || !ingreso.centimos) continue
        await apiRecurrentes.crear({
          name: ingreso.concepto.trim() || 'Ingreso',
          kind: 'income',
          account_id: cuentaPrincipal,
          amount: importeDeCentimos(ingreso.centimos) as string,
          // Quien presupuesta por semanas cobra por semanas: crear la regla en
          // mensual metería la paga una vez al mes y el reparto no cuadraría nunca.
          frequency: porSemanas.value ? 'weekly' : 'monthly',
          starts_on: inicioDelPeriodo.value,
        })
      }
    }
    await categorias.cargar(undefined, true)
    paso.value = 3
  } catch (e) {
    error.value = mensajeDeError(e, 'No se han podido guardar los ingresos. Inténtalo otra vez.')
  } finally {
    enviando.value = false
  }
}

async function terminar(omitiendo = false): Promise<void> {
  enviando.value = true
  error.value = null
  try {
    if (!omitiendo && elegidas.value.size > 0) {
      const allocations: AsignacionCrear[] = elegidasEnOrden.value
        .filter((c) => (asignado.value[c.id] ?? 0) > 0)
        .map((c) => ({
          category_id: c.id,
          amount: importeDeCentimos(asignado.value[c.id]) as string,
        }))
      if (allocations.length > 0) {
        await apiPresupuestos.sustituirAsignaciones(periodo.value, allocations)
      }
      // Lo que no se ha elegido se archiva para no ensuciar la barra el primer día.
      for (const c of sugeridas.value) {
        if (!elegidas.value.has(c.id) && c.children_count === 0) {
          await apiCategorias.archivar(c.id).catch(() => undefined)
        }
      }
    }
    preparando.value = true
    await sesion.completarOnboarding()
    void router.replace({ name: 'panel' })
  } catch (e) {
    preparando.value = false
    error.value = mensajeDeError(e, 'No se ha podido guardar el reparto.')
    avisos.error('No se ha podido guardar el reparto.', {
      accion: { etiqueta: 'Reintentar', alPulsar: () => void terminar(omitiendo) },
    })
  } finally {
    enviando.value = false
  }
}

onMounted(() => {
  void sesion.cargarOnboarding()
  void categorias.cargar()
})
</script>

<template>
  <div class="escena">
    <main class="panel tarjeta">
      <header class="cabecera">
        <ol class="progreso" aria-label="Progreso del asistente">
          <li v-for="n in 3" :key="n" :class="{ hecho: n < paso, activo: n === paso }">
            <span class="punto" aria-hidden="true">
              <Check v-if="n < paso" :size="12" />
            </span>
            <span class="oculto">
              Paso {{ n }}{{ n < paso ? ', completado' : n === paso ? ', en curso' : ', pendiente' }}
            </span>
          </li>
        </ol>
        <h1 class="titulo">
          <template v-if="paso === 1">Paso 1 de 3 · Crear tus cuentas</template>
          <template v-else-if="paso === 2">Paso 2 de 3 · Ingresos de {{ nombrePeriodo }}</template>
          <template v-else>Paso 3 de 3 · Tus primeras temáticas</template>
        </h1>
      </header>

      <p v-if="error" class="banda-error" role="alert">{{ error }}</p>

      <!-- Paso 1 -->
      <section v-if="paso === 1" class="contenido">
        <p class="intro">
          Añade al menos una cuenta. Puedes tener varias: corriente, ahorro, efectivo…
        </p>

        <ul class="filas">
          <li v-for="c in cuentasNuevas" :key="c.clave" class="fila-cuenta">
            <CampoTexto
              v-model="c.nombre"
              etiqueta="Nombre de la cuenta"
              placeholder="Cuenta corriente"
              :error="c.fallida ? 'No se ha podido guardar esta cuenta.' : undefined"
            />
            <SelectorBase
              :model-value="c.tipo"
              etiqueta="Tipo"
              :opciones="opcionesTipo"
              @update:model-value="cambiarTipo(c, $event)"
            />
            <CampoImporte v-model="c.centimos" etiqueta="Saldo inicial" />
            <BotonBase
              v-if="cuentasNuevas.length > 1"
              variante="fantasma"
              solo-icono
              :icono="X"
              etiqueta-accesible="Quitar esta cuenta"
              @click="cuentasNuevas = cuentasNuevas.filter((x) => x.clave !== c.clave)"
            />
          </li>
        </ul>

        <BotonBase
          variante="fantasma"
          :icono="Plus"
          @click="cuentasNuevas = [...cuentasNuevas, cuentaEnBlanco()]"
        >
          Añadir otra cuenta
        </BotonBase>

        <div v-if="cuentasCreadas.length > 0" class="anyadidas">
          <p class="rotulo">Cuentas añadidas</p>
          <ul class="chips">
            <li v-for="c in cuentasCreadas" :key="c.id" class="chip num">
              {{ c.nombre }} · {{ dinero(c.saldo) }}
            </li>
          </ul>
        </div>

        <p v-if="!puedeSalirDelPaso1" class="ayuda">Añade al menos una cuenta para seguir.</p>
      </section>

      <!-- Paso 2 -->
      <section v-else-if="paso === 2" class="contenido">
        <p class="intro">
          {{
            porSemanas
              ? '¿Cuánto esperas ingresar esta semana? Podrás cambiarlo cualquier semana desde el Panel.'
              : '¿Cuánto esperas ingresar este mes? Podrás cambiarlo cualquier mes desde el Panel.'
          }}
        </p>

        <ul class="filas">
          <li v-for="i in ingresos" :key="i.clave" class="fila-ingreso">
            <CampoTexto v-model="i.concepto" etiqueta="Concepto" placeholder="Nómina" />
            <CampoImporte v-model="i.centimos" etiqueta="Importe" />
            <InterruptorBase
              v-model="i.recurrente"
              :etiqueta="porSemanas ? 'Repetir cada semana' : 'Repetir cada mes'"
              tamanyo="sm"
            />
            <BotonBase
              v-if="ingresos.length > 1"
              variante="fantasma"
              solo-icono
              :icono="X"
              etiqueta-accesible="Quitar este ingreso"
              @click="ingresos = ingresos.filter((x) => x.clave !== i.clave)"
            />
          </li>
        </ul>

        <BotonBase
          variante="fantasma"
          :icono="Plus"
          @click="ingresos = [...ingresos, ingresoEnBlanco()]"
        >
          Añadir otro ingreso
        </BotonBase>

        <p class="total num">
          Total de ingresos de {{ nombrePeriodo }}
          <strong>{{ dinero(totalIngresosCentimos / 100) }}</strong>
        </p>
        <p v-if="!puedeSalirDelPaso2" class="ayuda">Sin ingresos no hay nada que repartir.</p>
      </section>

      <!-- Paso 3 -->
      <section v-else class="contenido">
        <p class="intro">
          Elige de la lista o crea las tuyas. Luego decides cuánto asignar a cada una.
        </p>

        <div class="chips">
          <EtiquetaCategoria
            v-for="c in sugeridas"
            :key="c.id"
            :nombre="c.name"
            :ranura="ranuraDeCategoria(c.color, c.id)"
            seleccionable
            :seleccionada="elegidas.has(c.id)"
            @alternar="alternarTematica(c.id)"
          />
        </div>

        <template v-if="elegidasEnOrden.length > 0">
          <p class="rotulo">
            Reparte {{ dinero(totalIngresosCentimos / 100) }} entre las temáticas elegidas
          </p>
          <ul class="filas">
            <li v-for="c in elegidasEnOrden" :key="c.id" class="fila-reparto">
              <EtiquetaCategoria
                :nombre="c.name"
                :ranura="ranuraDeCategoria(c.color, c.id)"
                tamanyo="sm"
              />
              <CampoImporte
                :model-value="asignado[c.id] ?? null"
                etiqueta="Asignado"
                etiqueta-oculta
                @update:model-value="asignado[c.id] = $event"
              />
            </li>
          </ul>
          <p class="total num">
            Sin asignar <strong>{{ dinero(sinAsignarCentimos / 100) }}</strong>
            <span class="ayuda"> · no pasa nada si no lo repartes todo hoy</span>
          </p>
        </template>
        <p v-else class="ayuda">
          Elige al menos una para empezar a repartir, o pulsa «Omitir por ahora».
        </p>
      </section>

      <footer class="pie">
        <BotonBase
          variante="contorno"
          :deshabilitado="paso === 1 || enviando"
          @click="retroceder"
        >
          Volver
        </BotonBase>

        <div class="acciones-derecha">
          <BotonBase v-if="paso === 3" variante="fantasma" :deshabilitado="enviando" @click="terminar(true)">
            Omitir por ahora
          </BotonBase>

          <BotonBase
            v-if="paso === 1"
            variante="primaria"
            :cargando="enviando"
            :deshabilitado="!puedeSalirDelPaso1"
            @click="irAlPaso2"
          >
            Continuar
          </BotonBase>
          <BotonBase
            v-else-if="paso === 2"
            variante="primaria"
            :cargando="enviando"
            :deshabilitado="!puedeSalirDelPaso2"
            @click="irAlPaso3"
          >
            Continuar
          </BotonBase>
          <BotonBase v-else variante="primaria" :cargando="enviando" @click="terminar(false)">
            Terminar y ver el panel
          </BotonBase>
        </div>
      </footer>

      <p v-if="preparando" class="preparando" role="status">Preparando tu panel…</p>
    </main>

    <AvisoFlotante />
  </div>
</template>

<style scoped>
.escena {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100dvh;
  padding: var(--sp-6) var(--sp-4);
  background-color: var(--c-app-bg);
}
.panel {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
  width: 100%;
  max-width: 760px;
  padding: var(--sp-6);
}

.cabecera {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.progreso {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.progreso li {
  display: flex;
  align-items: center;
}
.progreso li + li::before {
  content: '';
  width: 48px;
  height: 2px;
  margin-inline: var(--sp-1);
  background-color: var(--c-border);
}
.punto {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: 2px solid var(--c-border-strong);
  border-radius: var(--r-full);
  color: var(--c-text-on-fill);
}
.progreso .activo .punto {
  border-color: var(--c-accent);
  background-color: var(--c-accent);
}
.progreso .hecho .punto {
  border-color: var(--c-positive);
  background-color: var(--c-positive);
}

.titulo {
  margin: 0;
  font-size: var(--t-h1);
  line-height: var(--t-h1-lh);
  font-weight: 600;
}

.contenido {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.intro {
  margin: 0;
  max-width: 68ch;
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.rotulo {
  margin: 0;
  font-size: var(--t-sm);
  font-weight: 600;
  color: var(--c-text-2);
}
.ayuda {
  margin: 0;
  font-size: var(--t-caption);
  color: var(--c-text-3);
}

.filas {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin: 0;
  padding: 0;
  list-style: none;
}
.fila-cuenta,
.fila-ingreso {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1.2fr) minmax(0, 1fr) auto;
  align-items: end;
  gap: var(--sp-3);
}
.fila-reparto {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 200px;
  align-items: center;
  gap: var(--sp-3);
}
@media (max-width: 767px) {
  .fila-cuenta,
  .fila-ingreso,
  .fila-reparto {
    grid-template-columns: minmax(0, 1fr);
  }
}

.anyadidas {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.chip {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding-inline: var(--sp-3);
  border: 1px solid var(--c-border);
  border-radius: var(--r-full);
  background-color: var(--c-surface-2);
  font-size: var(--t-caption);
}

.total {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
  margin: 0;
  padding-top: var(--sp-3);
  border-top: 1px solid var(--c-border);
  font-size: var(--t-sm);
  color: var(--c-text-2);
}
.total strong {
  font-size: var(--t-h2);
  color: var(--c-text-1);
}

.pie {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--c-border);
}
.acciones-derecha {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.banda-error {
  margin: 0;
  padding: var(--sp-3);
  border-radius: var(--r-md);
  background-color: var(--c-negative-wash);
  color: var(--c-negative);
  font-size: var(--t-sm);
}
.preparando {
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
