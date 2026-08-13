import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // En desarrollo el backend corre aparte; en producción es el mismo origen,
    // así que el código de la app siempre llama a rutas relativas /api/...
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        // Separa el vendor de gráficos: es la dependencia más pesada y no hace
        // falta en la primera pintura del dashboard.
        // Vite 8 empaqueta con Rolldown, donde el `manualChunks` en forma de
        // objeto ya no existe: su equivalente es un grupo de codeSplitting.
        codeSplitting: {
          groups: [{ name: 'charts', test: /[\\/]node_modules[\\/](chart\.js|vue-chartjs)[\\/]/ }],
        },
      },
    },
  },
})
