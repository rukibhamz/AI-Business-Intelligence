const API_BASE = import.meta.env.VITE_API_URL ?? '/api'

export interface HealthResponse {
  status: string
  version: string
  environment: string
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

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(detail || `Request failed: ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  health: () => request<HealthResponse>('/health'),
  listSources: () => request<DataSource[]>('/sources'),
}
