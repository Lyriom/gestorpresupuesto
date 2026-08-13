<script setup lang="ts">
/**
 * Iniciar sesión (§2.1).
 *
 * Sin «Continuar con Google»: el contrato no publica ningún proveedor externo,
 * y un botón que no lleva a ninguna parte es peor que no tenerlo.
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BotonBase from '@/components/ui/BotonBase.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import PestanyasBase from '@/components/ui/PestanyasBase.vue'
import LayoutAuth from '@/layouts/LayoutAuth.vue'
import { useSesion } from '@/stores/sesion'

const route = useRoute()
const router = useRouter()
const sesion = useSesion()

const correo = ref('')
const contrasenya = ref('')
const errorCorreo = ref<string | null>(null)

const pestanya = ref<string | number>('entrar')

const puedeEnviar = computed(() => correo.value.length > 3 && contrasenya.value.length > 0)

const destino = computed(() => {
  const bruto = route.query.destino
  const ruta = Array.isArray(bruto) ? bruto[0] : bruto
  // Solo se acepta una ruta interna: un `destino` absoluto sería un redirector abierto.
  return typeof ruta === 'string' && ruta.startsWith('/') && !ruta.startsWith('//') ? ruta : '/'
})

async function enviar(): Promise<void> {
  errorCorreo.value = null
  if (!correo.value.includes('@')) {
    errorCorreo.value = 'Introduce un correo electrónico válido.'
    return
  }
  const dentro = await sesion.entrar({ email: correo.value.trim(), password: contrasenya.value })
  if (dentro) void router.replace(destino.value)
}

function cambiarPestanya(valor: string | number): void {
  pestanya.value = valor
  if (valor === 'registro') void router.push({ name: 'registro' })
}
</script>

<template>
  <LayoutAuth
    titulo="Entra en tu presupuesto"
    subtitulo="Usa el correo con el que te diste de alta."
  >
    <PestanyasBase
      v-if="sesion.registroAbierto"
      :model-value="pestanya"
      etiqueta="Entrar o crear cuenta"
      :pestanyas="[
        { valor: 'entrar', etiqueta: 'Iniciar sesión' },
        { valor: 'registro', etiqueta: 'Crear cuenta' },
      ]"
      @update:model-value="cambiarPestanya"
    />

    <p v-if="sesion.error" class="banda-error" role="alert">{{ sesion.error }}</p>

    <form class="formulario" novalidate @submit.prevent="enviar">
      <CampoTexto
        v-model="correo"
        etiqueta="Correo electrónico"
        tipo="email"
        placeholder="tu@correo.com"
        autocompletar="username"
        :error="errorCorreo ?? undefined"
        :deshabilitado="sesion.enviando"
        requerido
      />
      <CampoTexto
        v-model="contrasenya"
        etiqueta="Contraseña"
        tipo="password"
        autocompletar="current-password"
        :deshabilitado="sesion.enviando"
        requerido
        @enter="enviar"
      />
      <div class="olvidada">
        <BotonBase variante="enlace" tamanyo="sm" href="/recuperar">¿Olvidada?</BotonBase>
      </div>
      <BotonBase
        variante="primaria"
        tipo="submit"
        ancho-completo
        :cargando="sesion.enviando"
        :deshabilitado="!puedeEnviar"
      >
        Entrar
      </BotonBase>
    </form>

    <template #pie>
      <template v-if="sesion.registroAbierto">
        ¿No tienes cuenta?
        <BotonBase variante="enlace" tamanyo="sm" href="/registro">Crear una</BotonBase>
      </template>
      <template v-else>
        El registro está cerrado en esta instalación. Pide una cuenta a quien la administre.
      </template>
    </template>
  </LayoutAuth>
</template>

<style scoped>
.formulario {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.olvidada {
  display: flex;
  justify-content: flex-end;
  margin-top: calc(-1 * var(--sp-3));
}
.banda-error {
  margin: 0;
  padding: var(--sp-3);
  border-radius: var(--r-md);
  background-color: var(--c-negative-wash);
  color: var(--c-negative);
  font-size: var(--t-sm);
}
</style>
