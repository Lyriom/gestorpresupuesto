<script setup lang="ts">
/**
 * Cuentas.
 *
 * Reutiliza sin cambios el patrón de tabla con fila expandible de Movimientos,
 * como pide la nota de §1 de la especificación: Nombre · Tipo · Saldo actual ·
 * Última actividad, y el detalle con el saldo inicial dentro de la fila.
 */
import { computed, onMounted, ref } from 'vue'
import { Plus } from 'lucide-vue-next'

import {
  ETIQUETA_TIPO_CUENTA,
  TIPOS_CUENTA,
  type Cuenta,
  type TipoCuenta,
} from '@/api/cuentas'
import { importeDeCentimos } from '@/api/comun'
import BotonBase from '@/components/ui/BotonBase.vue'
import CampoImporte from '@/components/ui/CampoImporte.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import ModalBase from '@/components/ui/ModalBase.vue'
import SelectorBase from '@/components/ui/SelectorBase.vue'
import TablaDatos, { type ColumnaTabla } from '@/components/ui/TablaDatos.vue'
import { useAvisos } from '@/composables/useAvisos'
import { euros, fechaCorta } from '@/lib/formato'
import { useCuentas } from '@/stores/cuentas'

type Fila = Cuenta & Record<string, unknown>

const cuentas = useCuentas()
const avisos = useAvisos()

const modalAbierto = ref(false)
const enEdicion = ref<Cuenta | null>(null)
const nombre = ref('')
const tipo = ref<string | number | null>('checking')
const saldoCentimos = ref<number | null>(null)
const excluida = ref(false)
const errorNombre = ref<string | null>(null)

const opcionesTipo = TIPOS_CUENTA.map((t) => ({ valor: t, etiqueta: ETIQUETA_TIPO_CUENTA[t] }))

const COLUMNAS: ColumnaTabla<Fila>[] = [
  { clave: 'name', etiqueta: 'Nombre', ordenable: true },
  { clave: 'type', etiqueta: 'Tipo', ancho: '160px' },
  { clave: 'current_balance', etiqueta: 'Saldo actual', numerica: true, ancho: '150px' },
  { clave: 'last_transaction_on', etiqueta: 'Última actividad', ancho: '150px', soloEscritorio: true },
]

const filas = computed<Fila[]>(() => cuentas.items as Fila[])

function crear(): void {
  enEdicion.value = null
  nombre.value = ''
  tipo.value = 'checking'
  saldoCentimos.value = null
  excluida.value = false
  errorNombre.value = null
  modalAbierto.value = true
}

function editar(cuenta: Cuenta): void {
  enEdicion.value = cuenta
  nombre.value = cuenta.name
  tipo.value = cuenta.type
  saldoCentimos.value = Math.round(Number.parseFloat(cuenta.initial_balance) * 100)
  excluida.value = cuenta.is_excluded_from_net_worth
  errorNombre.value = null
  modalAbierto.value = true
}

async function guardar(): Promise<void> {
  errorNombre.value = null
  if (!nombre.value.trim()) {
    errorNombre.value = 'Este campo es obligatorio.'
    return
  }
  const ok = enEdicion.value
    ? await cuentas.actualizar(enEdicion.value.id, {
        name: nombre.value.trim(),
        is_excluded_from_net_worth: excluida.value,
      })
    : await cuentas.crear({
        name: nombre.value.trim(),
        type: (tipo.value ?? 'checking') as TipoCuenta,
        initial_balance: importeDeCentimos(saldoCentimos.value) ?? '0.00',
        is_excluded_from_net_worth: excluida.value,
      })
  if (!ok) return
  avisos.exito(enEdicion.value ? 'Cuenta guardada.' : 'Cuenta creada.')
  modalAbierto.value = false
}

onMounted(() => {
  void cuentas.cargar(true)
  void cuentas.cargarResumen()
})
</script>

<template>
  <div class="vista">
    <header class="cabecera">
      <h1 class="titulo">Cuentas</h1>
      <BotonBase variante="primaria" :icono="Plus" @click="crear">Nueva cuenta</BotonBase>
    </header>

    <div v-if="cuentas.resumen" class="cifras tarjeta caja">
      <div>
        <p class="rotulo">Activos</p>
        <p class="valor num">{{ euros(cuentas.resumen.assets) }}</p>
      </div>
      <div>
        <p class="rotulo">Pasivos</p>
        <p class="valor num">{{ euros(cuentas.resumen.liabilities) }}</p>
      </div>
      <div>
        <p class="rotulo">Patrimonio neto</p>
        <p class="valor num destacado">{{ euros(cuentas.resumen.net_worth) }}</p>
      </div>
    </div>

    <TablaDatos
      :columnas="COLUMNAS"
      :filas="filas"
      :clave-fila="(f) => f.id"
      titulo="Tus cuentas"
      titulo-oculto
      expandible
      :cargando="cuentas.cargando"
      :error="cuentas.error ?? undefined"
      @reintentar="cuentas.cargar(true)"
    >
      <template #celda-type="{ fila }">{{ ETIQUETA_TIPO_CUENTA[fila.type] }}</template>

      <template #celda-current_balance="{ fila }">
        <span :class="{ negativo: Number.parseFloat(fila.current_balance) < 0 }">
          {{ euros(fila.current_balance) }}
        </span>
      </template>

      <template #celda-last_transaction_on="{ fila }">
        {{ fechaCorta(fila.last_transaction_on) }}
      </template>

      <template #detalle="{ fila }">
        <dl class="detalle num">
          <dt>Saldo inicial</dt>
          <dd>{{ euros(fila.initial_balance) }}</dd>
          <dt>Movimientos</dt>
          <dd>{{ fila.transactions_count }}</dd>
          <dt>Conciliada hasta</dt>
          <dd>{{ fechaCorta(fila.reconciled_through) }}</dd>
          <dt v-if="fila.credit_limit">Límite de crédito</dt>
          <dd v-if="fila.credit_limit">{{ euros(fila.credit_limit) }}</dd>
          <dt>En el patrimonio neto</dt>
          <dd>{{ fila.is_excluded_from_net_worth ? 'Excluida' : 'Incluida' }}</dd>
        </dl>
        <div class="acciones-detalle">
          <BotonBase variante="secundaria" tamanyo="sm" @click="editar(fila)">Editar</BotonBase>
          <BotonBase variante="fantasma" tamanyo="sm" @click="cuentas.archivar(fila.id)">
            Archivar
          </BotonBase>
        </div>
      </template>

      <template #vacio>
        <EstadoVacio
          titulo="Todavía no has añadido ninguna cuenta."
          descripcion="Sin cuentas no se puede apuntar dónde entra y sale el dinero."
          :nivel="2"
        >
          <template #accion>
            <BotonBase variante="primaria" @click="crear">Añadir la primera</BotonBase>
          </template>
        </EstadoVacio>
      </template>
    </TablaDatos>

    <ModalBase
      v-model:abierto="modalAbierto"
      :titulo="enEdicion ? 'Editar cuenta' : 'Nueva cuenta'"
      tamanyo="md"
      :guardando="cuentas.guardando"
      :error="cuentas.error ?? undefined"
      @cerrar="modalAbierto = false"
    >
      <div class="formulario">
        <CampoTexto
          v-model="nombre"
          etiqueta="Nombre de la cuenta"
          placeholder="Cuenta corriente"
          :error="errorNombre ?? undefined"
          requerido
        />
        <SelectorBase
          v-model="tipo"
          etiqueta="Tipo"
          :opciones="opcionesTipo"
          :deshabilitado="enEdicion !== null"
          :ayuda="enEdicion ? 'El tipo no se cambia: alteraría el patrimonio histórico.' : undefined"
        />
        <CampoImporte
          v-if="!enEdicion"
          v-model="saldoCentimos"
          etiqueta="Saldo inicial"
          ayuda="El saldo actual se calcula solo a partir de los movimientos."
        />
        <InterruptorBase
          v-model="excluida"
          etiqueta="Excluir del patrimonio neto"
          descripcion="Para cuentas que no son tuyas del todo, como una compartida."
        />
      </div>

      <template #pie>
        <BotonBase variante="contorno" @click="modalAbierto = false">Cancelar</BotonBase>
        <BotonBase variante="primaria" :cargando="cuentas.guardando" @click="guardar">
          Guardar
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
.caja {
  padding: var(--sp-5);
}
.cifras {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--sp-4);
}
.rotulo {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-text-3);
}
.valor {
  margin: var(--sp-1) 0 0;
  font-size: var(--t-h2);
  font-weight: 600;
}
.destacado {
  font-size: var(--t-display);
}
.negativo {
  color: var(--c-negative);
}

.detalle {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--sp-2) var(--sp-4);
  margin: 0 0 var(--sp-3);
  font-size: var(--t-sm);
}
.detalle dt {
  color: var(--c-text-3);
}
.detalle dd {
  margin: 0;
}
.acciones-detalle {
  display: flex;
  gap: var(--sp-2);
}

.formulario {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
</style>
