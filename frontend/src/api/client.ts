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
  field_mapping?: Record<string, string> | null
  mapping_status?: string | null
  row_count?: number | null
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

export interface QueryResult {
  columns: string[]
  rows: Record<string, unknown>[]
  sql: string | null
}

/** How the UI should present an answer — chosen server-side per question. */
export type ResponseFormat = 'metric' | 'narrative' | 'chart' | 'table' | 'empty'

export interface QueryRecord {
  id: number
  data_source_id: number
  natural_language: string
  generated_sql: string | null
  status: string
  created_at: string
  result: QueryResult | null
  explanation: string | null
  mode: string | null
  chart?: ChartRecommendation | null
  session_id?: string | null
  /** Plain-language answer grounded in the returned rows. */
  answer?: string | null
  response_format?: ResponseFormat | null
}

export interface ChartRecommendation {
  type: string
  label_key: string | null
  value_keys: string[]
  reason: string | null
}

export interface DashboardWidget {
  id: string
  query_id: number
  title: string
  chart_type: string
}

export interface Dashboard {
  id: number
  name: string
  layout_json: string | null
  widgets: DashboardWidget[]
  created_at: string
  updated_at: string
}

export interface SourceSummary {
  id: number
  name: string
  source_type: string
  mapping_status: string | null
  row_count: number | null
  analyzable: boolean
}

export interface OverviewSourceMeta {
  id: number
  name: string
  source_type: string
  rows_analyzed: number
  total_rows: number
  truncated: boolean
}

export type KpiFormat = 'currency' | 'percent' | 'number' | 'text'

export interface KpiCard {
  id: string
  label: string
  value: number | string
  format: KpiFormat
  delta_pct: number | null
  direction: 'up' | 'down' | null
  tone: 'positive' | 'negative' | null
  caption: string | null
}

export interface OverviewChart {
  id: string
  title: string
  type: 'line' | 'bar' | 'hbar' | 'pie'
  label_key: string
  value_keys: string[]
  data: Record<string, string | number>[]
  format: KpiFormat
}

export interface CoverageReport {
  mapped: string[]
  missing: string[]
  unmapped_columns: string[]
}

export interface PeriodMeta {
  granularity: string | null
  start: string | null
  end: string | null
  buckets: number
}

export interface OverviewResponse {
  generated_at: string
  source: OverviewSourceMeta | null
  available_sources: SourceSummary[]
  kpis: KpiCard[]
  charts: OverviewChart[]
  coverage: CoverageReport | null
  notices: string[]
  period: PeriodMeta | null
  error: string | null
}

export type FindingSeverity = 'critical' | 'warning' | 'opportunity' | 'info'

export interface Finding {
  id: string
  severity: FindingSeverity
  title: string
  body: string
  action: string
  context: string
  metric: string | null
  source_id: number | null
  source_name: string | null
}

export interface FindingsResponse {
  generated_at: string
  findings: Finding[]
  available_sources: SourceSummary[]
  errors: string[]
}

export interface ColorSchemeOption {
  id: string
  primary: string
  primary_container: string
  secondary: string
  secondary_container: string
  label: string
}

export interface AppSettings {
  llm_provider: string
  openai_model: string
  openai_base_url: string
  api_key_set: boolean
  api_key_masked: string | null
  platform_name: string
  platform_tagline: string
  logo_url: string | null
  color_scheme: string
  color_schemes: ColorSchemeOption[]
  providers: string[]
}

export interface AppSettingsUpdate {
  llm_provider?: string
  openai_model?: string
  openai_api_key?: string
  openai_base_url?: string
  platform_name?: string
  platform_tagline?: string
  color_scheme?: string
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
  updateSourceMapping: (id: number, field_mapping: Record<string, string>, confirm = true) =>
    requestJson<DataSource>(`/sources/${id}/mapping`, {
      method: 'PUT',
      body: JSON.stringify({ field_mapping, confirm }),
    }),
  recomputeSource: (id: number) =>
    requestJson<DataSource>(`/sources/${id}/recompute`, { method: 'POST' }),
  canonicalFields: () => requestJson<{ fields: string[] }>('/sources/canonical-fields'),
  previewSource: (id: number, table?: string, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (table) params.set('table', table)
    return requestJson<PreviewResponse>(`/sources/${id}/preview?${params}`)
  },
  runQuery: (
    natural_language: string,
    options?: { dataSourceId?: number; sessionId?: string; signal?: AbortSignal },
  ) =>
    requestJson<QueryRecord>('/queries/run', {
      method: 'POST',
      signal: options?.signal,
      body: JSON.stringify({
        natural_language,
        ...(options?.dataSourceId != null ? { data_source_id: options.dataSourceId } : {}),
        ...(options?.sessionId ? { session_id: options.sessionId } : {}),
      }),
    }),
  listQueries: (data_source_id?: number) => {
    const params = new URLSearchParams({ limit: '50' })
    if (data_source_id) params.set('data_source_id', String(data_source_id))
    return requestJson<QueryRecord[]>(`/queries?${params}`)
  },
  getQuery: (id: number) => requestJson<QueryRecord>(`/queries/${id}`),
  downloadQueryCsv: async (id: number) => {
    const headers = new Headers()
    const token = getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(`${API_BASE}/queries/${id}/export`, { headers })
    if (res.status === 401) {
      clearSession()
      throw new Error('UNAUTHORIZED')
    }
    if (!res.ok) throw new Error(await res.text())
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `query_${id}.csv`
    a.click()
    URL.revokeObjectURL(url)
  },
  listDashboards: () => requestJson<Dashboard[]>('/dashboards'),
  ensureDefaultDashboard: () =>
    requestJson<Dashboard>('/dashboards/ensure-default', { method: 'POST' }),
  createDashboard: (name: string) =>
    requestJson<Dashboard>('/dashboards', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  deleteDashboard: (id: number) =>
    request<void>(`/dashboards/${id}`, { method: 'DELETE' }),
  addDashboardWidget: (
    dashboardId: number,
    payload: { query_id: number; title?: string; chart_type?: string },
  ) =>
    requestJson<Dashboard>(`/dashboards/${dashboardId}/widgets`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  removeDashboardWidget: (dashboardId: number, widgetId: string) =>
    requestJson<Dashboard>(`/dashboards/${dashboardId}/widgets/${widgetId}`, {
      method: 'DELETE',
    }),
  getOverview: (sourceId?: number) => {
    const params = sourceId ? `?source_id=${sourceId}` : ''
    return requestJson<OverviewResponse>(`/insights/overview${params}`)
  },
  getFindings: (sourceId?: number) => {
    const params = sourceId ? `?source_id=${sourceId}` : ''
    return requestJson<FindingsResponse>(`/insights/findings${params}`)
  },
  getSettings: () => requestJson<AppSettings>('/settings'),
  updateSettings: (payload: AppSettingsUpdate) =>
    requestJson<AppSettings>('/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  testAiConnection: (payload: AppSettingsUpdate) =>
    requestJson<{ ok: boolean; message: string }>('/settings/test-connection', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  uploadLogo: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<AppSettings>('/settings/logo', { method: 'POST', body: form })
  },
  deleteLogo: () => requestJson<AppSettings>('/settings/logo', { method: 'DELETE' }),
}

export function parseSchema(raw: string | null): SourceSchema | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as SourceSchema
  } catch {
    return null
  }
}
