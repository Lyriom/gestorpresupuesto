<script setup lang="ts">
/** Ruta que no existe. */
import { useRouter } from 'vue-router'

import BotonBase from '@/components/ui/BotonBase.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'

const router = useRouter()
</script>

<template>
  <div class="tarjeta caja">
    <EstadoVacio
      tipo="error"
      titulo="Esta página no existe."
      descripcion="Puede que el enlace esté mal o que la pantalla haya cambiado de sitio."
      :nivel="2"
    >
      <template #accion>
        <BotonBase variante="primaria" @click="router.push({ name: 'panel' })">
          Ir al panel
        </BotonBase>
      </template>
    </EstadoVacio>
  </div>
</template>

<style scoped>
.caja {
  padding: var(--sp-8) var(--sp-5);
}
</style>
