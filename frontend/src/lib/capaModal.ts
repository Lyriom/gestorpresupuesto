/**
 * Bloqueo del fondo compartido por el modal y el cajón lateral.
 *
 * Lleva cuenta de cuántas capas hay abiertas porque `inert` y el bloqueo de
 * scroll son globales: cerrar una capa interior quitaba el `inert` del resto de
 * la aplicación aunque siguiera abierta una exterior, y el fondo volvía a ser
 * navegable por detrás del diálogo que quedaba.
 */
let capas = 0

/** Suma una capa. Solo la primera toca el documento. */
export function bloquearFondo(): void {
  capas += 1
  if (capas > 1) return
  // Se compensa el ancho de la barra para que no haya salto de maquetación.
  const barra = window.innerWidth - document.documentElement.clientWidth
  document.body.style.overflow = 'hidden'
  if (barra > 0) document.body.style.paddingRight = `${barra}px`
  document.getElementById('app')?.setAttribute('inert', '')
}

/** Quita una capa. Solo la última restituye el documento. */
export function liberarFondo(): void {
  if (capas === 0) return
  capas -= 1
  if (capas > 0) return
  document.body.style.overflow = ''
  document.body.style.paddingRight = ''
  document.getElementById('app')?.removeAttribute('inert')
}
