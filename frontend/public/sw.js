/**
 * Service worker de la aplicación, escrito a mano y a propósito sin librerías.
 *
 * Reglas, de la más importante a la menos:
 *
 * 1. **Nunca se cachea nada de `/api`.** Son datos de dinero: servir un saldo
 *    viejo desde la caché es peor que decir que no hay conexión.
 * 2. Los ficheros de `/assets` llevan un hash en el nombre, así que su contenido
 *    no cambia nunca: se sirven de la caché y se guardan la primera vez.
 * 3. La navegación va a la red primero y cae a la copia de `index.html` guardada,
 *    para que la aplicación abra sin conexión (y avise de que no la hay).
 * 4. Al activarse una versión nueva se borran las cachés anteriores, para no
 *    acumular basura tras cada despliegue.
 */

const VERSION = 'v1'
const CACHE_APP = `presupuesto-app-${VERSION}`
const CACHE_ASSETS = `presupuesto-assets-${VERSION}`

// Lo mínimo para que la aplicación arranque sin conexión.
const BASE = ['/', '/index.html', '/manifest.webmanifest', '/favicon.svg']

self.addEventListener('install', (evento) => {
  evento.waitUntil(
    caches
      .open(CACHE_APP)
      // `reload` evita guardar en la caché algo que ya estaba caducado.
      .then((cache) => cache.addAll(BASE.map((url) => new Request(url, { cache: 'reload' }))))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (evento) => {
  evento.waitUntil(
    caches
      .keys()
      .then((nombres) =>
        Promise.all(
          nombres
            .filter((nombre) => nombre !== CACHE_APP && nombre !== CACHE_ASSETS)
            .map((nombre) => caches.delete(nombre)),
        ),
      )
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (evento) => {
  const peticion = evento.request
  if (peticion.method !== 'GET') return

  const url = new URL(peticion.url)
  if (url.origin !== self.location.origin) return

  // Regla 1: los datos nunca se cachean.
  if (url.pathname.startsWith('/api/')) return

  // Regla 3: navegación.
  if (peticion.mode === 'navigate') {
    evento.respondWith(
      fetch(peticion).catch(() =>
        caches.match('/index.html').then((r) => r || Response.error()),
      ),
    )
    return
  }

  // Regla 2: los assets con hash son inmutables.
  if (url.pathname.startsWith('/assets/')) {
    evento.respondWith(
      caches.match(peticion).then(
        (guardado) =>
          guardado ||
          fetch(peticion).then((respuesta) => {
            if (respuesta.ok) {
              const copia = respuesta.clone()
              caches.open(CACHE_ASSETS).then((cache) => cache.put(peticion, copia))
            }
            return respuesta
          }),
      ),
    )
    return
  }

  // El resto (iconos, manifiesto): la red manda, la caché salva.
  evento.respondWith(
    fetch(peticion)
      .then((respuesta) => {
        if (respuesta.ok) {
          const copia = respuesta.clone()
          caches.open(CACHE_APP).then((cache) => cache.put(peticion, copia))
        }
        return respuesta
      })
      .catch(() => caches.match(peticion).then((r) => r || Response.error())),
  )
})
