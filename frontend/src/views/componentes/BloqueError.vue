<script setup lang="ts">
/**
 * Tarjeta de error de un módulo, con su «Reintentar».
 *
 * Existe porque casi todas las pantallas cargan varios bloques que fallan por
 * separado (§2.3, §2.11, §2.12): que el gráfico no llegue no debe tumbar las
 * cifras que sí llegaron.
 */
import BotonBase from '@/components/ui/BotonBase.vue'
import EstadoVacio from '@/components/ui/EstadoVacio.vue'

withDefaults(
  defineProps<{
    titulo: string
    descripcion?: string
    nivel?: 2 | 3 | 4
  }>(),
  { nivel: 3 },
)

const emit = defineEmits<{ reintentar: [] }>()
</script>

<template>
  <div class="tarjeta caja">
    <EstadoVacio tipo="error" :titulo="titulo" :descripcion="descripcion" :nivel="nivel">
      <template #accion>
        <BotonBase variante="contorno" @click="emit('reintentar')">Reintentar</BotonBase>
      </template>
    </EstadoVacio>
  </div>
</template>

<style scoped>
.caja {
  padding: var(--sp-5);
}
</style>
