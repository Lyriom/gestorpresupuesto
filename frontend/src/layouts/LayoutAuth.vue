<script setup lang="ts">
import { simboloDe } from '@/lib/formato'
import { Monitor, Moon, Sun } from 'lucide-vue-next'
import { useTema } from '@/composables/useTema'
import AvisoFlotante from '@/components/ui/AvisoFlotante.vue'

defineProps<{
  titulo: string
  subtitulo?: string
}>()

const { preferencia, establecer, opciones } = useTema()
const ICONOS = { dark: Moon, light: Sun, sistema: Monitor } as const
</script>

<template>
  <div class="escena">
    <main class="tarjeta panel">
      <div class="marca">
        <span class="logo" aria-hidden="true">{{ simboloDe() }}</span>
        <span class="nombre">Gestor de presupuesto</span>
      </div>

      <header class="titulos">
        <h1>{{ titulo }}</h1>
        <p v-if="subtitulo">{{ subtitulo }}</p>
      </header>

      <div class="cuerpo"><slot /></div>

      <footer v-if="$slots.pie" class="pie"><slot name="pie" /></footer>
    </main>

    <div class="tema" role="radiogroup" aria-label="Tema de la interfaz">
      <label v-for="o in opciones" :key="o.valor" :title="o.etiqueta">
        <input
          type="radio"
          name="tema-auth"
          :value="o.valor"
          :checked="preferencia === o.valor"
          @change="establecer(o.valor)"
        />
        <component :is="ICONOS[o.valor]" :size="14" aria-hidden="true" />
        <span class="oculto-visualmente">{{ o.etiqueta }}</span>
      </label>
    </div>

    <AvisoFlotante />
  </div>
</template>

<style scoped>
.escena {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-5);
  min-height: 100dvh;
  padding: var(--sp-6) var(--sp-4);
  background-color: var(--c-app-bg);
}
.panel {
  width: 100%;
  max-width: 420px;
  padding: var(--sp-6);
}
.marca {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-6);
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
.nombre {
  font-size: var(--t-caption);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--c-text-3);
}

.titulos h1 {
  margin: 0;
  font-size: var(--t-h1);
  line-height: var(--t-h1-lh);
  font-weight: 600;
}
.titulos p {
  margin: var(--sp-2) 0 0;
  font-size: var(--t-sm);
  line-height: var(--t-sm-lh);
  color: var(--c-text-2);
}
.cuerpo {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  margin-top: var(--sp-6);
}
.pie {
  margin-top: var(--sp-5);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--c-border);
  font-size: var(--t-sm);
  color: var(--c-text-2);
}

.tema {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-full);
  background-color: var(--c-surface);
}
.tema label {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 28px;
  border-radius: var(--r-full);
  color: var(--c-text-3);
  cursor: pointer;
}
.tema label:has(input:checked) {
  background-color: var(--c-surface-3);
  color: var(--c-text-1);
}
.tema label:has(input:focus-visible) {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}
.tema input {
  position: absolute;
  opacity: 0;
  width: 1px;
  height: 1px;
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
