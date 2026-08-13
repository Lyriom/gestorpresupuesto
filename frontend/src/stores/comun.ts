/**
 * Utilidades compartidas por los stores.
 *
 * Ningún store recalcula lo que ya calcula el backend (estados de temática,
 * porcentajes de consumo, saldos, sumas de líneas): guardan la respuesta tal
 * cual y solo derivan lo que es puramente de presentación.
 */
import { ApiError, type DetalleValidacion } from '@/lib/api'

/**
 * Mensaje mostrable al usuario. `ApiError.mensaje` ya viene en español de España
 * desde `app/core/errors.py`, así que solo hay que cubrir lo que no es un error
 * de la API (una red caída, un `AbortError`).
 */
export function mensajeDeError(error: unknown, respaldo: string): string {
  if (error instanceof ApiError) return error.message || respaldo
  if (error instanceof DOMException && error.name === 'AbortError') return ''
  return respaldo
}

/** Código estable del error, para ramificar sin mirar el texto (§1.1). */
export function codigoDeError(error: unknown): string | null {
  return error instanceof ApiError ? error.codigo : null
}

/**
 * Errores por campo, con la ruta con puntos del cuerpo (`splits.0.amount`) que
 * usa el formulario para pintar el error en el control correcto.
 */
export function erroresPorCampo(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {}
  const mapa: Record<string, string> = {}
  for (const detalle of error.detalles as DetalleValidacion[]) {
    if (detalle.campo && !mapa[detalle.campo]) mapa[detalle.campo] = detalle.mensaje
  }
  return mapa
}

/** `true` cuando el fallo es solo que aún no hay backend contra el que hablar. */
export function esErrorDeRed(error: unknown): boolean {
  return error instanceof ApiError && (error.estado === 0 || error.estado >= 500)
}
