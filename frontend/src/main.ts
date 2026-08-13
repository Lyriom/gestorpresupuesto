import { createApp } from 'vue'
import { createPinia } from 'pinia'

import './style.css'
import App from './App.vue'
import { router } from './router'
import { registrarPerdidaDeSesion } from './lib/api'
import { useSesion } from './stores/sesion'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

/**
 * Un 401 que ni el refresco puede salvar lleva al login **conservando la ruta de
 * destino**, para volver exactamente a donde estaba el usuario al reentrar. El
 * store se pasa explícitamente porque esto se ejecuta desde `lib/api`, fuera de
 * cualquier componente.
 */
registrarPerdidaDeSesion(() => {
  useSesion(pinia).olvidar()
  const actual = router.currentRoute.value
  if (actual.name === 'entrar') return
  void router.replace({ name: 'entrar', query: { destino: actual.fullPath } })
})

app.mount('#app')
