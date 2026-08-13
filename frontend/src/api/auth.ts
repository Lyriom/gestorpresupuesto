/**
 * Sesión, perfil, metadatos públicos y asistente inicial.
 *
 * §3.1 y §3.2 del contrato. Aquí no se guarda ningún token: la sesión viaja en
 * cookies `httpOnly` y de eso ya se encarga `@/lib/api`.
 */
import { api } from '@/lib/api'
import { conQuery, type InstanteISO, type Pagina, type Periodo, type UUID } from './comun'

export type Tema = 'dark' | 'light' | 'system'

export interface Usuario {
  id: UUID
  created_at: InstanteISO
  updated_at: InstanteISO
  email: string
  name: string
  locale: string
  timezone: string
  currency: string
  theme: Tema
  onboarding_completed: boolean
}

/** `YoRespuesta`: lo que la SPA necesita al arrancar, en una sola llamada. */
export interface Yo extends Usuario {
  accounts_count: number
  categories_count: number
  unread_alerts: number
  current_period: Periodo
  session_expires_at: InstanteISO
}

/** Público: lo que se puede saber sin sesión, para pintar el login. */
export interface Meta {
  app_name: string
  allow_registration: boolean
  first_run: boolean
  default_currency: string
  default_locale: string
  max_upload_mb: number
  max_pdf_pages: number
  ocr_enabled: boolean
}

export interface Sesion {
  id: UUID
  created_at: InstanteISO
  last_used_at: InstanteISO
  expires_at: InstanteISO
  user_agent: string | null
  /** IP truncada: `192.168.1.x`. Nunca la IP completa. */
  ip_hint: string | null
  is_current: boolean
}

export interface RegistroCrear {
  email: string
  password: string
  name: string
}

export interface LoginCrear {
  email: string
  password: string
}

export interface CambioContrasenyaCrear {
  current_password: string
  new_password: string
}

export interface UsuarioActualizar {
  name?: string
  email?: string
  locale?: string
  timezone?: string
  currency?: string
  theme?: Tema
}

export type ClavePasoOnboarding =
  | 'account'
  | 'categories'
  | 'income'
  | 'budget'
  | 'first_expense'

export interface PasoOnboarding {
  key: ClavePasoOnboarding
  label: string
  done: boolean
  optional: boolean
}

export interface Onboarding {
  completed: boolean
  seeded: boolean
  steps: PasoOnboarding[]
  next_step: string | null
}

export type PresetOnboarding = 'es_basico' | 'es_completo' | 'minimo'

export interface OnboardingSembrarCrear {
  preset: PresetOnboarding
  accounts: Array<{
    name: string
    type: string
    currency?: string
    initial_balance?: string
  }>
}

export const apiAuth = {
  meta: () => api.get<Meta>('/meta'),
  /** Emite la cookie `csrf_token` antes del primer POST. */
  csrf: () => api.get<{ csrf_token: string }>('/auth/csrf'),

  registrar: (cuerpo: RegistroCrear) => api.post<Usuario>('/auth/register', cuerpo),
  entrar: (cuerpo: LoginCrear) => api.post<Usuario>('/auth/login', cuerpo),
  salir: () => api.post<void>('/auth/logout'),
  salirDeTodo: () => api.post<void>('/auth/logout-all'),
  cambiarContrasenya: (cuerpo: CambioContrasenyaCrear) =>
    api.post<void>('/auth/change-password', cuerpo),

  yo: () => api.get<Yo>(conQuery('/auth/me', { include: 'stats' })),
  actualizarPerfil: (cuerpo: UsuarioActualizar) => api.patch<Usuario>('/users/me', cuerpo),
  borrarCuenta: (password: string) => api.delete<void>('/users/me', { password }),

  sesiones: () => api.get<Pagina<Sesion>>('/auth/sessions'),
  revocarSesion: (id: UUID) => api.delete<void>(`/auth/sessions/${id}`),

  onboarding: () => api.get<Onboarding>('/onboarding/status'),
  sembrarOnboarding: (cuerpo: OnboardingSembrarCrear) =>
    api.post<Onboarding>('/onboarding/seed', cuerpo),
  completarOnboarding: () => api.post<Onboarding>('/onboarding/complete'),
}
