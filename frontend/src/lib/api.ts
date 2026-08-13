/**
 * Cliente HTTP de la aplicación.
 *
 * La sesión viaja en cookies httpOnly, así que aquí no se guarda ningún token:
 * solo hay que reenviar la cookie CSRF en la cabecera y renovar la sesión
 * cuando el backend responde 401 por token de acceso caducado.
 */

const BASE = '/api/v1'
const CSRF_COOKIE = 'csrf_token'
const CSRF_HEADER = 'X-CSRF-Token'

export interface DetalleValidacion {
  campo: string
  mensaje: string
}

/** Error de la API ya interpretado, con el mensaje que se puede mostrar al usuario. */
export class ApiError extends Error {
  readonly estado: number
  readonly codigo: string
  readonly detalles: DetalleValidacion[]

  constructor(estado: number, codigo: string, mensaje: string, detalles: DetalleValidacion[] = []) {
    super(mensaje)
    this.name = 'ApiError'
    this.estado = estado
    this.codigo = codigo
    this.detalles = detalles
  }

  get esNoAutenticado(): boolean {
    return this.estado === 401
  }

  get esValidacion(): boolean {
    return this.estado === 422 || this.detalles.length > 0
  }
}

function leerCookie(nombre: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${nombre}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

/** Handler que la app registra para reaccionar a una sesión perdida. */
let alPerderSesion: (() => void) | null = null

export function registrarPerdidaDeSesion(handler: () => void): void {
  alPerderSesion = handler
}

const METODOS_SIN_CSRF = new Set(['GET', 'HEAD', 'OPTIONS'])

interface OpcionesPeticion {
  metodo?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  cuerpo?: unknown
  params?: Record<string, string | number | boolean | null | undefined>
  /** Uso interno: evita bucles infinitos de renovación de sesión. */
  sinReintento?: boolean
  señal?: AbortSignal
}

function construirUrl(ruta: string, params?: OpcionesPeticion['params']): string {
  const url = `${BASE}${ruta}`
  if (!params) return url
  const qs = new URLSearchParams()
  for (const [clave, valor] of Object.entries(params)) {
    if (valor !== null && valor !== undefined && valor !== '') {
      qs.append(clave, String(valor))
    }
  }
  const cadena = qs.toString()
  return cadena ? `${url}?${cadena}` : url
}

async function interpretarError(respuesta: Response): Promise<ApiError> {
  let codigo = 'error_desconocido'
  let mensaje = `Error ${respuesta.status}`
  let detalles: DetalleValidacion[] = []
  try {
    const datos = await respuesta.json()
    const error = datos?.error ?? datos
    codigo = error?.codigo ?? error?.code ?? codigo
    mensaje = error?.mensaje ?? error?.message ?? error?.detail ?? mensaje
    if (Array.isArray(error?.detalles)) {
      detalles = error.detalles
    }
  } catch {
    // Respuesta sin JSON (un 502 del proxy, por ejemplo): se queda el mensaje genérico.
    if (respuesta.status >= 500) {
      mensaje = 'El servidor no ha podido completar la operación. Inténtalo de nuevo.'
    }
  }
  return new ApiError(respuesta.status, codigo, mensaje, detalles)
}

let renovacionEnCurso: Promise<boolean> | null = null

/** Renueva la sesión con el token de refresco. Comparte una única llamada
 *  entre todas las peticiones que fallen a la vez. */
async function renovarSesion(): Promise<boolean> {
  renovacionEnCurso ??= (async () => {
    try {
      const csrf = leerCookie(CSRF_COOKIE)
      const respuesta = await fetch(`${BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: csrf ? { [CSRF_HEADER]: csrf } : {},
      })
      return respuesta.ok
    } catch {
      return false
    } finally {
      // Se libera en el siguiente tick para que las peticiones en cola vean el resultado.
      setTimeout(() => {
        renovacionEnCurso = null
      }, 0)
    }
  })()
  return renovacionEnCurso
}

async function peticion<T>(ruta: string, opciones: OpcionesPeticion = {}): Promise<T> {
  const { metodo = 'GET', cuerpo, params, sinReintento = false, señal } = opciones

  const cabeceras: Record<string, string> = { Accept: 'application/json' }
  const esFormData = cuerpo instanceof FormData
  if (cuerpo !== undefined && !esFormData) {
    cabeceras['Content-Type'] = 'application/json'
  }
  if (!METODOS_SIN_CSRF.has(metodo)) {
    const csrf = leerCookie(CSRF_COOKIE)
    if (csrf) cabeceras[CSRF_HEADER] = csrf
  }

  const respuesta = await fetch(construirUrl(ruta, params), {
    method: metodo,
    credentials: 'same-origin',
    headers: cabeceras,
    body: esFormData ? (cuerpo as FormData) : cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined,
    signal: señal,
  })

  if (respuesta.status === 401 && !sinReintento && !ruta.startsWith('/auth/')) {
    if (await renovarSesion()) {
      return peticion<T>(ruta, { ...opciones, sinReintento: true })
    }
    alPerderSesion?.()
    throw new ApiError(401, 'sesion_expirada', 'Tu sesión ha caducado. Vuelve a entrar.')
  }

  if (!respuesta.ok) {
    throw await interpretarError(respuesta)
  }

  if (respuesta.status === 204) {
    return undefined as T
  }
  const tipo = respuesta.headers.get('Content-Type') ?? ''
  if (!tipo.includes('application/json')) {
    return (await respuesta.blob()) as T
  }
  return (await respuesta.json()) as T
}

export const api = {
  get: <T>(ruta: string, params?: OpcionesPeticion['params'], señal?: AbortSignal) =>
    peticion<T>(ruta, { metodo: 'GET', params, señal }),
  post: <T>(ruta: string, cuerpo?: unknown) => peticion<T>(ruta, { metodo: 'POST', cuerpo }),
  patch: <T>(ruta: string, cuerpo?: unknown) => peticion<T>(ruta, { metodo: 'PATCH', cuerpo }),
  put: <T>(ruta: string, cuerpo?: unknown) => peticion<T>(ruta, { metodo: 'PUT', cuerpo }),
  delete: <T>(ruta: string, cuerpo?: unknown) => peticion<T>(ruta, { metodo: 'DELETE', cuerpo }),
  /** Sube un fichero con seguimiento del progreso (fetch no lo expone, así que usa XHR). */
  subir: <T>(
    ruta: string,
    fichero: File,
    campos: Record<string, string> = {},
    alProgresar?: (porcentaje: number) => void,
  ): Promise<T> =>
    new Promise<T>((resolver, rechazar) => {
      const datos = new FormData()
      datos.append('fichero', fichero)
      for (const [clave, valor] of Object.entries(campos)) datos.append(clave, valor)

      const xhr = new XMLHttpRequest()
      xhr.open('POST', construirUrl(ruta))
      xhr.withCredentials = true
      const csrf = leerCookie(CSRF_COOKIE)
      if (csrf) xhr.setRequestHeader(CSRF_HEADER, csrf)

      xhr.upload.addEventListener('progress', (evento) => {
        if (evento.lengthComputable && alProgresar) {
          alProgresar(Math.round((evento.loaded / evento.total) * 100))
        }
      })
      xhr.addEventListener('load', () => {
        let datosRespuesta: unknown = null
        try {
          datosRespuesta = JSON.parse(xhr.responseText)
        } catch {
          datosRespuesta = null
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolver(datosRespuesta as T)
          return
        }
        const error = (datosRespuesta as { error?: Record<string, unknown> })?.error ?? {}
        rechazar(
          new ApiError(
            xhr.status,
            (error.codigo as string) ?? 'error_subida',
            (error.mensaje as string) ?? 'No se ha podido subir el fichero.',
            (error.detalles as DetalleValidacion[]) ?? [],
          ),
        )
      })
      xhr.addEventListener('error', () =>
        rechazar(new ApiError(0, 'error_red', 'No hay conexión con el servidor.')),
      )
      xhr.addEventListener('abort', () =>
        rechazar(new ApiError(0, 'subida_cancelada', 'Subida cancelada.')),
      )
      xhr.send(datos)
    }),
}
