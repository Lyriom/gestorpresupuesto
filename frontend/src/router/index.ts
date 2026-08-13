/**
 * Rutas de la aplicación.
 *
 * Tres cosas viven aquí y en ningún otro sitio:
 *
 * 1. **Carga diferida** de todas las vistas: el panel no debe arrastrar Chart.js
 *    ni la pantalla de revisión de facturas.
 * 2. **Guardas** de autenticación y de puesta en marcha. El orden importa: sin
 *    sesión se va al login conservando el destino; con sesión pero sin el
 *    asistente terminado, al asistente, que es obligatorio y secuencial.
 * 3. **El estado de la lista de movimientos en la URL** (`aQuery` / `deQuery`):
 *    filtros, orden y página. Un enlace pegado en otro sitio reproduce la misma
 *    lista, que es lo que pide §2.4 de la especificación.
 */
import {
  createRouter,
  createWebHistory,
  type LocationQuery,
  type LocationQueryRaw,
  type RouteRecordRaw,
} from 'vue-router'

import type { EstadoMovimiento, TipoMovimiento } from '@/api/movimientos'
import {
  filtrosVacios,
  useMovimientos,
  type FiltrosVista,
} from '@/stores/movimientos'
import { useSesion } from '@/stores/sesion'

export type Layout = 'app' | 'auth' | 'desnudo'

declare module 'vue-router' {
  interface RouteMeta {
    /** Marco en el que se pinta la vista. */
    layout: Layout
    /** Texto que se pone antes del nombre de la aplicación en `document.title`. */
    titulo: string
    /** `false` en las rutas públicas. Por defecto se exige sesión. */
    publica?: boolean
    /** Solo accesible sin sesión: con sesión redirige al panel. */
    soloSinSesion?: boolean
    /** Se puede visitar con el asistente inicial sin terminar. */
    permiteSinOnboarding?: boolean
    /** Clave del destino de la barra lateral que queda activo. */
    nav?: string
  }
}

const rutas: RouteRecordRaw[] = [
  {
    path: '/entrar',
    name: 'entrar',
    component: () => import('@/views/LoginVista.vue'),
    meta: { layout: 'auth', titulo: 'Iniciar sesión', publica: true, soloSinSesion: true },
  },
  {
    path: '/registro',
    name: 'registro',
    component: () => import('@/views/RegistroVista.vue'),
    meta: { layout: 'auth', titulo: 'Crear cuenta', publica: true, soloSinSesion: true },
  },
  {
    path: '/recuperar',
    name: 'recuperar',
    component: () => import('@/views/RecuperarVista.vue'),
    meta: { layout: 'auth', titulo: 'Recuperar contraseña', publica: true, soloSinSesion: true },
  },
  {
    path: '/bienvenida',
    name: 'onboarding',
    component: () => import('@/views/OnboardingVista.vue'),
    meta: { layout: 'desnudo', titulo: 'Primeros pasos', permiteSinOnboarding: true },
  },
  {
    path: '/',
    name: 'panel',
    component: () => import('@/views/PanelVista.vue'),
    meta: { layout: 'app', titulo: 'Panel', nav: 'panel' },
  },
  {
    path: '/movimientos',
    name: 'movimientos',
    component: () => import('@/views/MovimientosVista.vue'),
    meta: { layout: 'app', titulo: 'Movimientos', nav: 'movimientos' },
  },
  {
    // `LayoutApp` trae cableado el atajo `g t` a `/transacciones`; el alias evita
    // que un atajo del propio marco acabe en un 404.
    path: '/transacciones',
    redirect: { name: 'movimientos' },
  },
  {
    path: '/tematicas',
    name: 'tematicas',
    component: () => import('@/views/TematicasVista.vue'),
    meta: { layout: 'app', titulo: 'Temáticas', nav: 'tematicas' },
  },
  {
    path: '/facturas',
    name: 'facturas',
    component: () => import('@/views/FacturasVista.vue'),
    meta: { layout: 'app', titulo: 'Facturas', nav: 'facturas' },
  },
  {
    path: '/facturas/:id/revisar',
    name: 'revisar-factura',
    component: () => import('@/views/RevisionFacturaVista.vue'),
    meta: { layout: 'app', titulo: 'Revisar factura', nav: 'facturas' },
  },
  {
    path: '/facturas/:id',
    name: 'factura',
    component: () => import('@/views/DetalleFacturaVista.vue'),
    meta: { layout: 'app', titulo: 'Factura', nav: 'facturas' },
  },
  {
    path: '/productos',
    name: 'productos',
    component: () => import('@/views/ProductosVista.vue'),
    meta: { layout: 'app', titulo: 'Productos', nav: 'productos' },
  },
  {
    path: '/productos/:id',
    name: 'producto',
    component: () => import('@/views/FichaProductoVista.vue'),
    meta: { layout: 'app', titulo: 'Producto', nav: 'productos' },
  },
  {
    path: '/informes',
    name: 'informes',
    component: () => import('@/views/InformesVista.vue'),
    meta: { layout: 'app', titulo: 'Informes', nav: 'informes' },
  },
  {
    path: '/cuentas',
    name: 'cuentas',
    component: () => import('@/views/CuentasVista.vue'),
    meta: { layout: 'app', titulo: 'Cuentas', nav: 'cuentas' },
  },
  {
    path: '/ajustes',
    name: 'ajustes',
    component: () => import('@/views/AjustesVista.vue'),
    meta: { layout: 'app', titulo: 'Ajustes', nav: 'ajustes' },
  },
  {
    // Ruta oculta: la galería de componentes sirve para revisar el diseño.
    path: '/galeria',
    name: 'galeria',
    component: () => import('@/views/GaleriaComponentes.vue'),
    meta: { layout: 'desnudo', titulo: 'Galería de componentes', publica: true },
  },
  {
    path: '/:ruta(.*)*',
    name: 'no-encontrada',
    component: () => import('@/views/NoEncontradaVista.vue'),
    meta: { layout: 'app', titulo: 'Página no encontrada', publica: true },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes: rutas,
  scrollBehavior: (_a, _b, guardada) => guardada ?? { top: 0 },
})

/* ------------------------------------------------------------------ *
 * Estado de la lista en la URL (§2.4)
 * ------------------------------------------------------------------ */

function comoLista(valor: LocationQuery[string]): string[] {
  if (valor === null || valor === undefined) return []
  const bruto = Array.isArray(valor) ? valor : [valor]
  return bruto.flatMap((v) => (v ? String(v).split(',') : []))
}

function comoTexto(valor: LocationQuery[string]): string | null {
  const uno = Array.isArray(valor) ? valor[0] : valor
  return uno ? String(uno) : null
}

function comoBooleano(valor: LocationQuery[string]): boolean | null {
  const texto = comoTexto(valor)
  if (texto === null) return null
  return texto === 'true' || texto === '1'
}

const TIPOS: TipoMovimiento[] = ['expense', 'income', 'transfer']
const ESTADOS: EstadoMovimiento[] = ['pending', 'cleared', 'reconciled']

export interface EstadoLista {
  filtros: FiltrosVista
  pagina: number
  tamanyoPagina: number
  orden: { clave: string; sentido: 'asc' | 'desc' } | null
}

/** Lee el estado de la lista de una *query string*. Tolerante: nunca lanza. */
export function deQuery(query: LocationQuery): EstadoLista {
  const filtros = filtrosVacios()
  filtros.q = comoTexto(query.q) ?? ''
  filtros.desde = comoTexto(query.desde)
  filtros.hasta = comoTexto(query.hasta)
  filtros.tematicas = comoLista(query.tematica)
  filtros.cuentas = comoLista(query.cuenta)
  filtros.tipos = comoLista(query.tipo).filter((t): t is TipoMovimiento =>
    (TIPOS as string[]).includes(t),
  )
  filtros.estados = comoLista(query.estado).filter((e): e is EstadoMovimiento =>
    (ESTADOS as string[]).includes(e),
  )
  filtros.minimo = comoTexto(query.min)
  filtros.maximo = comoTexto(query.max)
  filtros.conFactura = comoBooleano(query.factura)
  filtros.soloRecurrentes = comoBooleano(query.recurrentes) === true
  filtros.soloSinCategorizar = comoBooleano(query.sinclasificar) === true
  filtros.incluirHijas = comoBooleano(query.hijas) !== false
  filtros.facturaId = comoTexto(query.factura_id)

  const pagina = Number.parseInt(comoTexto(query.pagina) ?? '1', 10)
  const tamanyo = Number.parseInt(comoTexto(query.tamanyo) ?? '25', 10)
  const orden = comoTexto(query.orden)

  return {
    filtros,
    pagina: Number.isFinite(pagina) && pagina >= 1 ? pagina : 1,
    tamanyoPagina: [25, 50, 100, 200].includes(tamanyo) ? tamanyo : 25,
    orden: orden
      ? { clave: orden.replace(/^-/, ''), sentido: orden.startsWith('-') ? 'desc' : 'asc' }
      : null,
  }
}

/** Serializa el estado de la lista. Omite todo lo que esté en su valor por defecto. */
export function aQuery(estado: EstadoLista): LocationQueryRaw {
  const { filtros: f, pagina, tamanyoPagina, orden } = estado
  const query: LocationQueryRaw = {}
  if (f.q) query.q = f.q
  if (f.desde) query.desde = f.desde
  if (f.hasta) query.hasta = f.hasta
  if (f.tematicas.length > 0) query.tematica = f.tematicas
  if (f.cuentas.length > 0) query.cuenta = f.cuentas
  if (f.tipos.length > 0) query.tipo = f.tipos
  if (f.estados.length > 0) query.estado = f.estados
  if (f.minimo) query.min = f.minimo
  if (f.maximo) query.max = f.maximo
  if (f.conFactura !== null) query.factura = String(f.conFactura)
  if (f.soloRecurrentes) query.recurrentes = 'true'
  if (f.soloSinCategorizar) query.sinclasificar = 'true'
  if (!f.incluirHijas) query.hijas = 'false'
  if (f.facturaId) query.factura_id = f.facturaId
  if (pagina > 1) query.pagina = String(pagina)
  if (tamanyoPagina !== 25) query.tamanyo = String(tamanyoPagina)
  if (orden && !(orden.clave === 'date' && orden.sentido === 'desc')) {
    query.orden = `${orden.sentido === 'desc' ? '-' : ''}${orden.clave}`
  }
  return query
}

/** Vuelca en el store lo que dice la URL. Lo llama la vista al montarse. */
export function aplicarQueryAlStore(query: LocationQuery): void {
  const lista = useMovimientos()
  const estado = deQuery(query)
  lista.filtros = estado.filtros
  lista.pagina = estado.pagina
  lista.tamanyoPagina = estado.tamanyoPagina
  lista.orden = estado.orden ?? { clave: 'date', sentido: 'desc' }
}

/* ------------------------------------------------------------------ *
 * Guardas
 * ------------------------------------------------------------------ */

router.beforeEach(async (a) => {
  const sesion = useSesion()
  await sesion.cargarMeta()

  // Una sola comprobación por carga de página: después el store ya lo sabe.
  if (!sesion.comprobada) await sesion.comprobarSesion()

  const publica = a.meta.publica === true

  if (!publica && !sesion.autenticado) {
    return { name: 'entrar', query: { destino: a.fullPath }, replace: true }
  }

  if (a.meta.soloSinSesion && sesion.autenticado) {
    return { name: 'panel', replace: true }
  }

  // El asistente inicial es obligatorio y secuencial: no se salta.
  if (
    sesion.autenticado &&
    sesion.necesitaOnboarding &&
    !a.meta.permiteSinOnboarding &&
    !publica
  ) {
    return { name: 'onboarding', replace: true }
  }

  if (a.name === 'onboarding' && sesion.autenticado && !sesion.necesitaOnboarding) {
    return { name: 'panel', replace: true }
  }

  return true
})

router.afterEach((a) => {
  const sesion = useSesion()
  const titulo = a.meta.titulo
  document.title = titulo ? `${titulo} · ${sesion.nombreApp}` : sesion.nombreApp
})
