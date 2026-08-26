/**
 * Where the API lives.
 *
 * Vite inlines this at build time, so a deployment whose build did not have
 * VITE_API_URL set silently calls /api on its own origin. Exported so the UI
 * can say which address it tried when a request never arrives.
 */
export const API_BASE = import.meta.env.VITE_API_URL ?? '/api'
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
  /** "admin" or "member" — admin unlocks Settings and nothing else. */
  role?: string
  is_admin?: boolean
}

/** How this deployment expects people to sign in. */
export interface AuthConfig {
  provider: 'supabase' | 'local'
  supabase_url: string
  supabase_anon_key: string
  allow_signup: boolean
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
  /** Every table the source exposes; analytics reads `primary_table`. */
  tables?: string[]
  primary_table?: string | null
  /** "ai" when the model mapped these columns, "heuristic" for name matching. */
  mapping_source?: string | null
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
export type ResponseFormat = 'metric' | 'narrative' | 'chart' | 'table' | 'empty' | 'diagnostic' | 'meta'

/** One segment's share of a measured change. */
export interface DriverContribution {
  dimension: string
  label: string
  current: number
  previous: number
  change: number
  change_pct: number | null
  /** Percent of the total movement across all segments, always positive. */
  share: number
  direction: 'up' | 'down'
}

/** An action the evidence supports, with the figure that justifies it. */
export interface Recommendation {
  title: string
  detail: string
  basis: string
  priority: 'now' | 'next' | 'watch'
  kind: string
}

/** Why a measure moved: the comparison, the drivers, the supporting factors. */
export interface Diagnosis {
  measure: string
  measure_label: string
  direction: 'up' | 'down' | 'flat'
  current: number
  previous: number
  change: number
  change_pct: number | null
  period_label: string
  previous_label: string
  granularity: string
  dimension: string | null
  concentration: number | null
  drivers: DriverContribution[]
  factors: { kind: string; detail: string }[]
  series: { period: string; value: number }[]
  rows_analyzed: number
  truncated: boolean
}

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
  /** Present only for "why" questions: the measured explanation of the move. */
  diagnosis?: Diagnosis | null
  /** Actions derived from that evidence. Empty for ordinary questions. */
  recommendations?: Recommendation[]
}

export interface ChartRecommendation {
  type: string
  label_key: string | null
  /** Columns that together identify a bar — both halves of a store/product pair. */
  label_keys?: string[]
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

export interface ConversationSummary {
  id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
  last_question: string | null
  last_answer: string | null
  /** True for questions asked before conversations existed. */
  is_legacy: boolean
}

export interface ConversationDetail {
  id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
  messages: QueryRecord[]
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

export interface LlmProviderProfile {
  id: string
  label: string
  provider: string
  model: string
  base_url: string
  priority: number
  enabled: boolean
  api_key_set: boolean
  api_key_masked: string | null
}

export interface LlmProviderUpdate {
  id?: string
  label?: string
  provider?: string
  model?: string
  base_url?: string
  api_key?: string
  priority?: number
  enabled?: boolean
}

export interface AppSettings {
  llm_provider: string
  openai_model: string
  openai_base_url: string
  api_key_set: boolean
  api_key_masked: string | null
  llm_providers: LlmProviderProfile[]
  active_provider_id: string | null
  platform_name: string
  platform_tagline: string
  logo_url: string | null
  color_scheme: string
  color_schemes: ColorSchemeOption[]
  providers: string[]
  currency: string
  currencies: CurrencyOption[]
}

export interface CurrencyOption {
  code: string
  label: string
  symbol: string
}

export interface AppSettingsUpdate {
  llm_provider?: string
  openai_model?: string
  openai_api_key?: string
  openai_base_url?: string
  llm_providers?: LlmProviderUpdate[]
  active_provider_id?: string
  platform_name?: string
  platform_tagline?: string
  color_scheme?: string
  currency?: string
}

export interface ConnectionTestPayload {
  provider_id?: string
  llm_provider?: string
  openai_model?: string
  openai_api_key?: string
  openai_base_url?: string
}

export function formatApiError(raw: string, fallback = 'Request failed'): string {
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown }
    const detail = parsed.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === 'string') return item
          if (item && typeof item === 'object' && 'msg' in item) {
            return String((item as { msg: string }).msg)
          }
          return JSON.stringify(item)
        })
        .join('; ')
    }
  } catch {
    /* not JSON */
  }
  return raw.trim() || fallback
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

/**
 * Where the bearer token comes from.
 *
 * Local sign-in stores one token and keeps it; Supabase rotates them, so the
 * auth layer swaps this for a getter that returns the current one rather than
 * whatever was in storage an hour ago.
 */
type TokenSource = () => Promise<string | null>

let tokenSource: TokenSource = async () => getToken()
let onUnauthorized: () => void = clearSession

export function setTokenSource(source: TokenSource, unauthorized?: () => void) {
  tokenSource = source
  if (unauthorized) onUnauthorized = unauthorized
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  const token = await tokenSource()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })

  if (res.status === 401) {
    onUnauthorized()
    throw new Error('UNAUTHORIZED')
  }

  if (!res.ok) {
    const detail = await res.text()
    throw new Error(formatApiError(detail, `Request failed: ${res.status}`))
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  headers.set('Content-Type', 'application/json')
  return request<T>(path, { ...options, headers })
}

/** Upload progress 0–100 for the bytes on the wire. */
export type UploadProgressHandler = (percent: number) => void

/**
 * POST multipart/form-data with upload progress.
 * fetch() cannot report upload progress; XHR can.
 */
async function uploadForm<T>(
  path: string,
  form: FormData,
  onProgress?: UploadProgressHandler,
): Promise<T> {
  const token = await tokenSource()
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}${path}`)
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    xhr.upload.onprogress = (event) => {
      if (!onProgress || !event.lengthComputable || event.total <= 0) return
      const pct = Math.min(100, Math.round((event.loaded / event.total) * 100))
      onProgress(pct)
    }
    xhr.upload.onload = () => {
      // Bytes are on the server; profiling / mapping may still be running.
      onProgress?.(100)
    }

    xhr.onload = () => {
      if (xhr.status === 401) {
        onUnauthorized()
        reject(new Error('UNAUTHORIZED'))
        return
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(
          new Error(
            formatApiError(xhr.responseText || '', `Request failed: ${xhr.status}`),
          ),
        )
        return
      }
      try {
        resolve(JSON.parse(xhr.responseText) as T)
      } catch {
        reject(new Error('Invalid response from server'))
      }
    }
    xhr.onerror = () => reject(new Error('Network error during upload'))
    xhr.onabort = () => reject(new Error('Upload cancelled'))
    xhr.send(form)
  })
}

export const api = {
  health: () => requestJson<HealthResponse>('/health'),
  authConfig: () => requestJson<AuthConfig>('/auth/config'),
  login: (email: string, password: string) =>
    requestJson<TokenResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  me: () => requestJson<User>('/auth/me'),
  listSources: () => requestJson<DataSource[]>('/sources'),
  uploadSource: (name: string, file: File, onProgress?: UploadProgressHandler) => {
    const form = new FormData()
    form.append('name', name)
    form.append('file', file)
    return uploadForm<DataSource>('/sources/upload', form, onProgress)
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
  setPrimaryTable: (id: number, table: string) =>
    requestJson<DataSource>(`/sources/${id}/primary-table`, {
      method: 'POST',
      body: JSON.stringify({ table }),
    }),
  automapSource: (id: number) =>
    requestJson<DataSource>(`/sources/${id}/automap`, { method: 'POST' }),
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
    const token = await tokenSource()
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
  listConversations: () => requestJson<ConversationSummary[]>('/conversations'),
  getConversation: (id: string) =>
    requestJson<ConversationDetail>(`/conversations/${encodeURIComponent(id)}`),
  renameConversation: (id: string, title: string) =>
    requestJson<ConversationSummary>(`/conversations/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (id: string) =>
    request<void>(`/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getSettings: () => requestJson<AppSettings>('/settings'),
  updateSettings: (payload: AppSettingsUpdate) =>
    requestJson<AppSettings>('/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  testAiConnection: (payload: ConnectionTestPayload) =>
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


/** Why a request never reached the API. */
export type ReachabilityFailure =
  | { kind: 'ok' }
  | { kind: 'unreachable'; apiBase: string }
  | { kind: 'blocked'; apiBase: string; origin: string }

/**
 * Work out why fetch failed.
 *
 * The browser reports a blocked origin and an unreachable host identically —
 * both are a TypeError with no detail, on purpose, so a page cannot probe the
 * network. A `no-cors` request gets round it for diagnosis only: it returns an
 * opaque response the page cannot read, but *reaching* the server at all
 * separates "the server said no" from "there was no server".
 */
export async function diagnoseReachability(): Promise<ReachabilityFailure> {
  const base = API_BASE.startsWith('http') ? API_BASE : `${location.origin}${API_BASE}`
  try {
    await fetch(`${base}/health`, { mode: 'no-cors', cache: 'no-store' })
    return { kind: 'blocked', apiBase: base, origin: location.origin }
  } catch {
    return { kind: 'unreachable', apiBase: base }
  }
}

const NETWORK_FAILURE_HINTS = [
  'failed to fetch',
  'networkerror',
  'load failed',
  'network request failed',
]

export function isNetworkFailure(err: unknown): boolean {
  const message = err instanceof Error ? err.message : String(err ?? '')
  return NETWORK_FAILURE_HINTS.some((hint) => message.toLowerCase().includes(hint))
}

/** A sentence naming the actual problem, for a failure isNetworkFailure() matched. */
export async function describeNetworkFailure(): Promise<string> {
  const result = await diagnoseReachability()
  if (result.kind === 'blocked') {
    return (
      `The API at ${result.apiBase} is running but refused a request from ${result.origin}. ` +
      `Add ${result.origin} to CORS_ORIGINS on the API and redeploy it.`
    )
  }
  if (result.kind === 'unreachable') {
    return (
      `Could not reach the API at ${result.apiBase}. Check that it is deployed and awake, ` +
      'and that VITE_API_URL was set when this app was built.'
    )
  }
  return 'Could not reach the server. Check that the backend is running, then try again.'
}
