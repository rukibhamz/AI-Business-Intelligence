const API_BASE = import.meta.env.VITE_API_URL ?? '/api'
const TOKEN_KEY = 'ai_bi_token'
const USER_KEY = 'ai_bi_user'

export interface HealthResponse {
  status: string
  version: string
  environment: string
}

export interface User {
  id: number
  email: string
  full_name: string | null
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: User
}

export interface DataSource {
  id: number
  name: string
  source_type: string
  connection_config: string | null
  schema_json: string | null
  created_at: string
  updated_at: string
}

export interface ColumnSchema {
  name: string
  type: string
}

export interface SourceSchema {
  tables: { name: string; columns: ColumnSchema[] }[]
}

export interface PreviewResponse {
  table: string | null
  columns: string[]
  rows: Record<string, unknown>[]
  limit: number
  offset: number
  total: number
}

export interface MySQLConnectionConfig {
  host: string
  port: number
  user: string
  password: string
  database: string
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getStoredUser(): User | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as User
  } catch {
    return null
  }
}

export function setSession(token: string, user: User) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })

  if (res.status === 401) {
    clearSession()
    throw new Error('UNAUTHORIZED')
  }

  if (!res.ok) {
    const detail = await res.text()
    throw new Error(detail || `Request failed: ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  headers.set('Content-Type', 'application/json')
  return request<T>(path, { ...options, headers })
}

export const api = {
  health: () => requestJson<HealthResponse>('/health'),
  login: (email: string, password: string) =>
    requestJson<TokenResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  me: () => requestJson<User>('/auth/me'),
  listSources: () => requestJson<DataSource[]>('/sources'),
  uploadSource: (name: string, file: File) => {
    const form = new FormData()
    form.append('name', name)
    form.append('file', file)
    return request<DataSource>('/sources/upload', { method: 'POST', body: form })
  },
  createMysqlSource: (name: string, connection_config: MySQLConnectionConfig) =>
    requestJson<DataSource>('/sources/mysql', {
      method: 'POST',
      body: JSON.stringify({ name, connection_config }),
    }),
  deleteSource: (id: number) =>
    request<void>(`/sources/${id}`, { method: 'DELETE' }),
  previewSource: (id: number, table?: string, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (table) params.set('table', table)
    return requestJson<PreviewResponse>(`/sources/${id}/preview?${params}`)
  },
}

export function parseSchema(raw: string | null): SourceSchema | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as SourceSchema
  } catch {
    return null
  }
}
