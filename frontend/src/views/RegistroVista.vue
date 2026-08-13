<script setup lang="ts">
/**
 * Crear cuenta (§2.1, variante «Crear cuenta»).
 *
 * La política de contraseña es la del backend (RN-05): diez caracteres y mezcla
 * de letras y números. Se valida aquí también para no gastar una ida y vuelta,
 * pero la que manda sigue siendo la del servidor.
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import BotonBase from '@/components/ui/BotonBase.vue'
import CampoTexto from '@/components/ui/CampoTexto.vue'
import InterruptorBase from '@/components/ui/InterruptorBase.vue'
import PestanyasBase from '@/components/ui/PestanyasBase.vue'
import LayoutAuth from '@/layouts/LayoutAuth.vue'
import { useSesion } from '@/stores/sesion'

const LONGITUD_MINIMA = 10

const router = useRouter()
const sesion = useSesion()

const nombre = ref('')
const correo = ref('')
const contrasenya = ref('')
const repetida = ref('')
const acepta = ref(false)

const errorNombre = ref<string | null>(null)
const errorCorreo = ref<string | null>(null)
const errorContrasenya = ref<string | null>(null)
const errorRepetida = ref<string | null>(null)

const pestanya = ref<string | number>('registro')

const puedeEnviar = computed(
  () =>
    nombre.value.trim().length > 0 &&
    correo.value.includes('@') &&
    contrasenya.value.length >= LONGITUD_MINIMA &&
    repetida.value === contrasenya.value &&
    acepta.value,
)

function validar(): boolean {
  errorNombre.value = nombre.value.trim() ? null : 'Este campo es obligatorio.'
  errorCorreo.value = correo.value.includes('@')
    ? null
    : 'Introduce un correo electrónico válido.'
  errorContrasenya.value =
    contrasenya.value.length >= LONGITUD_MINIMA
      ? /^\d+$/.test(contrasenya.value) || /^[a-zA-Z]+$/.test(contrasenya.value)
        ? 'La contraseña debe combinar letras y números.'
        : null
      : `La contraseña debe tener al menos ${LONGITUD_MINIMA} caracteres.`
  errorRepetida.value =
    repetida.value === contrasenya.value ? null : 'Las contraseñas no coinciden.'
  return (
    !errorNombre.value && !errorCorreo.value && !errorContrasenya.value && !errorRepetida.value
  )
}

async function enviar(): Promise<void> {
  if (!validar()) return
  const dentro = await sesion.registrar({
    name: nombre.value.trim(),
    email: correo.value.trim(),
    password: contrasenya.value,
  })
  if (dentro) void router.replace({ name: 'onboarding' })
}

function cambiarPestanya(valor: string | number): void {
  pestanya.value = valor
  if (valor === 'entrar') void router.push({ name: 'entrar' })
}
</script>

<template>
  <LayoutAuth titulo="Crea tu cuenta" subtitulo="Un correo, una contraseña y ya estás dentro.">
    <PestanyasBase
      :model-value="pestanya"
      etiqueta="Entrar o crear cuenta"
      :pestanyas="[
        { valor: 'entrar', etiqueta: 'Iniciar sesión' },
        { valor: 'registro', etiqueta: 'Crear cuenta' },
      ]"
      @update:model-value="cambiarPestanya"
    />

    <p v-if="!sesion.registroAbierto" class="banda-aviso" role="alert">
      El registro está cerrado en esta instalación.
    </p>
    <p v-if="sesion.error" class="banda-error" role="alert">{{ sesion.error }}</p>

    <form class="formulario" novalidate @submit.prevent="enviar">
      <CampoTexto
        v-model="nombre"
        etiqueta="Nombre"
        placeholder="Cómo te llamamos"
        autocompletar="name"
        :error="errorNombre ?? undefined"
        :deshabilitado="sesion.enviando"
        requerido
      />
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
        autocompletar="new-password"
        :ayuda="`Mínimo ${LONGITUD_MINIMA} caracteres, con letras y números`"
        :error="errorContrasenya ?? undefined"
        :deshabilitado="sesion.enviando"
        requerido
      />
      <CampoTexto
        v-model="repetida"
        etiqueta="Repite la contraseña"
        tipo="password"
        autocompletar="new-password"
        :error="errorRepetida ?? undefined"
        :deshabilitado="sesion.enviando"
        requerido
        @enter="enviar"
      />
      <InterruptorBase
        v-model="acepta"
        etiqueta="Acepto los términos y la política de datos"
      />
      <BotonBase
        variante="primaria"
        tipo="submit"
        ancho-completo
        :cargando="sesion.enviando"
        :deshabilitado="!puedeEnviar || !sesion.registroAbierto"
      >
        Crear cuenta
      </BotonBase>
    </form>

    <template #pie>
      ¿Ya tienes cuenta?
      <BotonBase variante="enlace" tamanyo="sm" href="/entrar">Iniciar sesión</BotonBase>
    </template>
  </LayoutAuth>
</template>

<style scoped>
.formulario {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.banda-error,
.banda-aviso {
  margin: 0;
  padding: var(--sp-3);
  border-radius: var(--r-md);
  font-size: var(--t-sm);
}
.banda-error {
  background-color: var(--c-negative-wash);
  color: var(--c-negative);
}
.banda-aviso {
  background-color: var(--c-warning-wash);
  color: var(--c-warning);
}
</style>
