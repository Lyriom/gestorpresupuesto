<script setup lang="ts">
/**
 * Recuperar contraseña.
 *
 * La API no publica ningún endpoint de restablecimiento por correo (§3.1 solo
 * tiene `change-password`, que exige sesión), y esta es una instalación
 * autoalojada sin servidor de correo garantizado. Así que la pantalla dice la
 * verdad en vez de fingir que ha enviado un enlace.
 */
import BotonBase from '@/components/ui/BotonBase.vue'
import LayoutAuth from '@/layouts/LayoutAuth.vue'
</script>

<template>
  <LayoutAuth
    titulo="Recuperar la contraseña"
    subtitulo="Esta instalación no envía correos de recuperación."
  >
    <div class="explicacion">
      <p>
        El gestor se instala en tu propio servidor y no depende de ningún servicio de correo,
        así que no hay enlace de restablecimiento que enviarte.
      </p>
      <p>
        Si tienes acceso al servidor, puedes cambiar la contraseña desde la consola de
        administración. Si no lo tienes, pídeselo a quien administre la instalación.
      </p>
      <p class="nota">
        Con la sesión abierta, la contraseña se cambia en <strong>Ajustes › Perfil y
        seguridad</strong>.
      </p>
    </div>

    <BotonBase variante="primaria" ancho-completo href="/entrar">Volver a entrar</BotonBase>
  </LayoutAuth>
</template>

<style scoped>
.explicacion {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.explicacion p {
  margin: 0;
  font-size: var(--t-sm);
  line-height: var(--t-sm-lh);
  color: var(--c-text-2);
}
.nota {
  padding: var(--sp-3);
  border-radius: var(--r-md);
  background-color: var(--c-info-wash);
  color: var(--c-info);
}
</style>
