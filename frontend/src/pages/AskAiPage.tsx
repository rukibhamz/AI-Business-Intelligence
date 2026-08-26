import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  describeNetworkFailure,
  isNetworkFailure,
  parseSchema,
  type AppSettings,
  type DataSource,
  type Diagnosis,
  type QueryRecord,
  type Recommendation,
  type ResponseFormat,
} from '../api/client'
import { ResultChart } from '../components/ResultChart'
import { formatCell, formatValue, humanizeColumn } from '../lib/format'
import { getSessionId, startNewSession } from '../lib/session'
import './AskAiPage.css'

/** Workspace-wide suggestion chips derived from the real schemas on file. */
function suggestionsForWorkspace(sources: DataSource[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  const push = (s: string) => {
    if (!seen.has(s)) {
      seen.add(s)
      out.push(s)
    }
  }

  for (const source of sources) {
    const mapping = source.field_mapping ?? {}
    const columnFor = (canonical: string) =>
      Object.entries(mapping).find(([, canon]) => canon === canonical)?.[0]

    const schema = parseSchema(source.schema_json)
    const columns = schema?.tables[0]?.columns.map((c) => c.name) ?? Object.keys(mapping)

    const measure = columnFor('Revenue') ?? columnFor('Profit') ?? columnFor('Quantity')
    const dimension =
      columnFor('Region') ?? columnFor('Category') ?? columnFor('Store ID') ?? columnFor('Product')
    const dateCol = columnFor('Date') ?? columnFor('Timestamp')

    if (measure && dimension) push(`Total ${measure} by ${dimension}`)
    if (measure) push(`Top 5 rows by ${measure}`)
    if (measure && dateCol) push(`${measure} over time`)
    if (dimension) push(`Count of records per ${dimension}`)
    if (out.length < 2 && columns.length > 0) {
      push(`Show the first 20 rows from ${source.name}`)
    }
    if (out.length >= 4) break
  }

  if (out.length === 0 && sources.length > 0) {
    push('How many records do we have?')
    push('Show a sample of the latest data')
  }
  return out.slice(0, 4)
}

type AssistantMessage = {
  id: string
  role: 'assistant'
  text: string
  /** The question that produced this answer, so it can be retried. */
  question: string
  query?: QueryRecord
  error?: string
  sqlOpen?: boolean
  pinned?: boolean
  at: number
}

type ChatMessage =
  | { id: string; role: 'user'; text: string; at: number }
  | AssistantMessage

type Props = {
  sources: DataSource[]
  branding?: AppSettings | null
  pendingQuestion?: string | null
  onPendingConsumed?: () => void
  onAnswered?: () => void
  /** Conversation to open, from `?c=` in the URL. Absent means the live one. */
  conversationId?: string | null
  /** Puts the active conversation in the URL so a reload reopens it. */
  onConversationChange?: (id: string | null) => void
}

/**
 * Transcripts live on the server: every question is already persisted as a
 * query row, so a conversation is rebuilt from the API rather than from
 * browser storage. That keeps history, reloads, and other devices consistent.
 */
function messagesFromRecords(records: QueryRecord[]): ChatMessage[] {
  const out: ChatMessage[] = []
  for (const record of records) {
    const at = new Date(record.created_at).getTime()
    out.push({ id: `u-${record.id}`, role: 'user', text: record.natural_language, at })
    out.push({
      id: `a-${record.id}`,
      role: 'assistant',
      text:
        record.answer ??
        record.explanation ??
        (record.result ? `Returned ${record.result.rows.length} row(s).` : 'Query completed.'),
      question: record.natural_language,
      query: record,
      error: record.status === 'failed' ? 'This question did not complete.' : undefined,
      sqlOpen: false,
      at,
    })
  }
  return out
}

const CHART_TITLE: Record<string, string> = {
  pie: 'Breakdown',
  line: 'Trend',
  bar: 'Comparison',
  hbar: 'Ranking',
}

/** What the card says under the title — "hbar chart" means nothing to a reader. */
const CHART_KIND: Record<string, string> = {
  pie: 'share of total',
  line: 'over time',
  bar: 'bar chart',
  hbar: 'ranked bars',
}

/**
 * What the server is doing, roughly. It no longer always writes SQL — a "why"
 * question is answered by comparing periods instead — so the label stays
 * truthful about the work rather than naming one implementation of it.
 */
const THINKING_STAGES: { after: number; label: string }[] = [
  { after: 0, label: 'Thinking…' },
  { after: 2500, label: 'Working through your data…' },
  { after: 7000, label: 'Crunching the numbers…' },
  { after: 15000, label: 'Still going — a large dataset takes a moment…' },
]

function useThinkingLabel(active: boolean): string {
  const [stage, setStage] = useState(0)

  useEffect(() => {
    if (!active) {
      setStage(0)
      return
    }
    const timers = THINKING_STAGES.slice(1).map((step, index) =>
      window.setTimeout(() => setStage(index + 1), step.after),
    )
    return () => timers.forEach(window.clearTimeout)
  }, [active])

  return THINKING_STAGES[stage].label
}

const PRIORITY_LABEL: Record<Recommendation['priority'], string> = {
  now: 'Do now',
  next: 'Do next',
  watch: 'Keep watching',
}

/** Money measures read as currency; counts read as plain numbers. */
const MONEY_MEASURES = new Set(['revenue', 'profit', 'cost', 'sales', 'marketing spend'])

function measureFormatter(measure: string) {
  const kind = MONEY_MEASURES.has(measure) ? 'currency' : 'number'
  return (value: number) => formatValue(value, kind)
}

/**
 * A "why" answer earns a follow-up. Offering it is how someone discovers they
 * can ask for the remedy as well as the cause.
 */
/** How close to the bottom still counts as "reading the newest message". */
const STICK_THRESHOLD_PX = 80

const FOLLOW_UPS = ['What should we do about it?', 'How do we prevent this happening again?']

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function timeLabel(at: number) {
  return new Date(at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

/**
 * Always returns a string. FastAPI sends `detail` as a plain string for
 * HTTPException but as an array of objects for 422 validation errors, and
 * rendering that array directly would crash React.
 */
function errorDetail(err: unknown): string {
  const message = err instanceof Error ? err.message : 'Query failed'
  if (isNetworkFailure(err)) {
    // Replaced by describeNetworkFailure() once the probe comes back.
    return 'Could not reach the server…'
  }
  try {
    const parsed = JSON.parse(message) as { detail?: unknown }
    const detail = parsed.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) => {
          if (typeof item === 'string') return item
          if (item && typeof item === 'object') {
            const entry = item as { msg?: unknown; loc?: unknown }
            const field = Array.isArray(entry.loc) ? entry.loc.join('.') : undefined
            const msg = typeof entry.msg === 'string' ? entry.msg : JSON.stringify(item)
            return field ? `${field}: ${msg}` : msg
          }
          return String(item)
        })
        .filter(Boolean)
      if (parts.length > 0) return parts.join(' · ')
    }
    if (detail != null) return JSON.stringify(detail)
  } catch {
    /* not a JSON error body */
  }
  return message
}

export function AskAiPage({
  sources,
  branding,
  pendingQuestion,
  onPendingConsumed,
  onAnswered,
  conversationId,
  onConversationChange,
}: Props) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [restoring, setRestoring] = useState(true)
  const [title, setTitle] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  /** Answers that lead with prose or a chart keep their rows collapsed. */
  const [tableOpen, setTableOpen] = useState<Set<string>>(() => new Set())
  /** Quiet overflow menu id for export / SQL / pin. */
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null)

  const threadRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  /** False once the reader scrolls up, so the thread stops chasing the bottom. */
  const stickToBottom = useRef(true)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const hasSources = sources.length > 0
  const suggestions = useMemo(() => suggestionsForWorkspace(sources), [sources])
  const thinkingLabel = useThinkingLabel(busy)
  const assistantName = branding?.platform_name || 'Cognitive Logic'
  const isEmpty = messages.length === 0 && !busy && !restoring

  useEffect(() => {
    if (!menuOpenId) return
    const onPointer = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('.ask-tool-menu')) return
      setMenuOpenId(null)
    }
    document.addEventListener('mousedown', onPointer)
    return () => document.removeEventListener('mousedown', onPointer)
  }, [menuOpenId])

  // The chat being viewed: an explicit conversation from the URL, or the one
  // this browser session started.
  const activeId = conversationId ?? getSessionId()

  // --- load the conversation from the server ------------------------------
  useEffect(() => {
    let cancelled = false
    setRestoring(true)
    void api
      .getConversation(activeId)
      .then((conversation) => {
        if (cancelled) return
        setMessages(messagesFromRecords(conversation.messages))
        setTitle(conversation.title)
      })
      .catch(() => {
        // A brand-new chat has no rows yet; that is not an error.
        if (cancelled) return
        setMessages([])
        setTitle(null)
      })
      .finally(() => {
        if (!cancelled) setRestoring(false)
      })
    return () => {
      cancelled = true
    }
  }, [activeId])

  // Scroll the thread container only — never the whole document.
  useEffect(() => {
    const el = threadRef.current
    if (!el) return
    stickToBottom.current = true
    el.scrollTo({ top: el.scrollHeight, behavior: messages.length > 1 ? 'smooth' : 'auto' })
  }, [messages, busy])

  /**
   * Hold the thread at the newest message while it keeps growing.
   *
   * An answer arrives before its chart and table have laid out, so scrolling
   * once on arrival leaves the reader stranded halfway up the reply. This
   * re-pins on every size change — until the reader scrolls up, which hands
   * control back to them until they return to the bottom.
   */
  useEffect(() => {
    const el = threadRef.current
    if (!el) return

    const distanceFromBottom = () => el.scrollHeight - el.scrollTop - el.clientHeight
    const onScroll = () => {
      stickToBottom.current = distanceFromBottom() <= STICK_THRESHOLD_PX
    }
    el.addEventListener('scroll', onScroll, { passive: true })

    const observer = new ResizeObserver(() => {
      if (stickToBottom.current) el.scrollTop = el.scrollHeight
    })
    observer.observe(el)
    for (const child of Array.from(el.children)) observer.observe(child)

    // The list is replaced when a conversation loads, so watch for new children.
    const mutations = new MutationObserver(() => {
      for (const child of Array.from(el.children)) observer.observe(child)
      if (stickToBottom.current) el.scrollTop = el.scrollHeight
    })
    mutations.observe(el, { childList: true, subtree: true })

    return () => {
      el.removeEventListener('scroll', onScroll)
      observer.disconnect()
      mutations.disconnect()
    }
  }, [])

  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [])

  function resizeTextarea() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = ''
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }

  const sendQuestion = useCallback(
    async (text: string) => {
      const question = text.trim()
      if (!question || !hasSources || busy) return

      setDraft('')
      if (textareaRef.current) textareaRef.current.style.height = ''

      const now = Date.now()
      setMessages((prev) => [...prev, { id: uid(), role: 'user', text: question, at: now }])
      setBusy(true)

      const controller = new AbortController()
      abortRef.current = controller

      try {
        const result = await api.runQuery(question, {
          sessionId: activeId,
          signal: controller.signal,
        })
        const summary =
          result.answer ??
          result.explanation ??
          (result.result ? `Returned ${result.result.rows.length} row(s).` : 'Query completed.')
        setMessages((prev) => [
          ...prev,
          {
            id: uid(),
            role: 'assistant',
            text: summary,
            question,
            query: result,
            sqlOpen: false,
            at: Date.now(),
          },
        ])
        onAnswered?.()

        // First answer in a new chat: publish it to the URL and pick up the
        // server-derived title so the toolbar and History agree.
        if (!title) {
          void api
            .getConversation(activeId)
            .then((conversation) => setTitle(conversation.title))
            .catch(() => undefined)
          onConversationChange?.(activeId)
        }
      } catch (err) {
        if (controller.signal.aborted) {
          setMessages((prev) => [
            ...prev,
            {
              id: uid(),
              role: 'assistant',
              text: 'Stopped before the query finished.',
              question,
              at: Date.now(),
            },
          ])
        } else {
          const id = uid()
          setMessages((prev) => [
            ...prev,
            {
              id,
              role: 'assistant',
              text: 'I could not answer that question.',
              question,
              error: errorDetail(err),
              at: Date.now(),
            },
          ])
          // A network failure hides which of two very different problems it is.
          if (isNetworkFailure(err)) {
            const detail = await describeNetworkFailure()
            setMessages((prev) =>
              prev.map((m) => (m.id === id ? { ...m, error: detail } : m)),
            )
          }
        }
      } finally {
        abortRef.current = null
        setBusy(false)
      }
    },
    [busy, hasSources, onAnswered, activeId, title, onConversationChange],
  )

  // A question handed over from the command palette runs once data is ready.
  useEffect(() => {
    if (!pendingQuestion || !hasSources || busy || restoring) return
    void sendQuestion(pendingQuestion)
    onPendingConsumed?.()
  }, [pendingQuestion, hasSources, busy, restoring, sendQuestion, onPendingConsumed])

  function stopQuery() {
    abortRef.current?.abort()
  }

  function newChat() {
    abortRef.current?.abort()
    setMessages([])
    setTitle(null)
    setDraft('')
    startNewSession()
    onConversationChange?.(null)
    textareaRef.current?.focus()
  }

  async function renameChat() {
    const next = window.prompt('Rename this chat', title ?? '')
    if (next == null) return
    const trimmed = next.trim()
    if (!trimmed || trimmed === title) return
    try {
      const updated = await api.renameConversation(activeId, trimmed)
      setTitle(updated.title)
      onAnswered?.()
    } catch {
      /* the chat has no saved questions yet */
    }
  }

  function retry(msg: AssistantMessage) {
    if (!msg.question) return
    // Drop the failed answer so the retry replaces it rather than stacking up.
    setMessages((prev) => prev.filter((m) => m.id !== msg.id))
    void sendQuestion(msg.question)
  }

  function toggleSql(id: string) {
    setMessages((prev) =>
      prev.map((m) => (m.role === 'assistant' && m.id === id ? { ...m, sqlOpen: !m.sqlOpen } : m)),
    )
  }

  async function copyAnswer(msg: AssistantMessage) {
    const parts = [msg.text]
    try {
      await navigator.clipboard.writeText(parts.filter(Boolean).join('\n\n'))
      setCopiedId(msg.id)
      setMenuOpenId(null)
      window.setTimeout(() => setCopiedId(null), 1600)
    } catch {
      /* clipboard blocked */
    }
  }

  async function pinQuery(msgId: string, query: QueryRecord) {
    try {
      const dash = await api.ensureDefaultDashboard()
      await api.addDashboardWidget(dash.id, {
        query_id: query.id,
        title: query.natural_language.slice(0, 80),
        chart_type: query.chart?.type,
      })
      setMessages((prev) =>
        prev.map((m) => (m.role === 'assistant' && m.id === msgId ? { ...m, pinned: true } : m)),
      )
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.role === 'assistant' && m.id === msgId
            ? { ...m, error: `Could not pin to dashboard: ${errorDetail(err)}` }
            : m,
        ),
      )
    }
  }

  /** Where the change happened: the segments that moved, and by how much. */
  function renderDiagnosis(diagnosis: Diagnosis) {
    const fmt = measureFormatter(diagnosis.measure_label)
    const signed = (value: number) => `${value >= 0 ? '+' : '−'}${fmt(Math.abs(value))}`
    const drivers = diagnosis.drivers ?? []
    const factors = (diagnosis.factors ?? []).filter((f) => f.kind !== 'baseline')

    return (
      <section className="ask-card ask-diagnosis">
        <header className="ask-card-head">
          <h4>What moved</h4>
          <span className="ask-card-meta">
            {diagnosis.period_label} vs {diagnosis.previous_label}
          </span>
        </header>

        <div className={`ask-diag-move is-${diagnosis.direction}`}>
          <span className="ask-diag-delta">{signed(diagnosis.change)}</span>
          <span className="ask-diag-detail">
            {diagnosis.measure_label} went {fmt(diagnosis.previous)} → {fmt(diagnosis.current)}
            {diagnosis.change_pct != null && ` (${diagnosis.change_pct > 0 ? '+' : ''}${Math.round(
              diagnosis.change_pct,
            )}%)`}
          </span>
        </div>

        {drivers.length > 0 && (
          <ul className="ask-driver-list">
            {drivers.map((driver) => (
              <li key={`${driver.dimension}-${driver.label}`} className={`is-${driver.direction}`}>
                <div className="ask-driver-head">
                  <span className="ask-driver-label">{driver.label}</span>
                  <span className="ask-driver-change">{signed(driver.change)}</span>
                </div>
                <div className="ask-driver-track">
                  <span style={{ width: `${Math.min(100, Math.max(2, driver.share))}%` }} />
                </div>
                <span className="ask-driver-share">
                  {Math.round(driver.share)}% of the movement
                  {driver.change_pct != null &&
                    ` · ${driver.change_pct > 0 ? '+' : ''}${Math.round(driver.change_pct)}% on ${
                      diagnosis.previous_label
                    }`}
                </span>
              </li>
            ))}
          </ul>
        )}

        {factors.length > 0 && (
          <ul className="ask-factor-list">
            {factors.map((factor) => (
              <li key={factor.kind}>{factor.detail}</li>
            ))}
          </ul>
        )}

        <p className="ask-diag-note">
          Measured across {diagnosis.rows_analyzed.toLocaleString()} row
          {diagnosis.rows_analyzed === 1 ? '' : 's'}
          {diagnosis.dimension ? ` by ${diagnosis.dimension.toLowerCase()}` : ''}. This shows where
          the change happened, not why — check the segments above before acting.
        </p>
      </section>
    )
  }

  function renderAssistant(msg: AssistantMessage) {
    const result = msg.query?.result
    const rows = result?.rows ?? []
    const cols = result?.columns ?? []
    const shownRows = rows.slice(0, 20)
    const completed = msg.query?.status === 'completed' && !msg.error
    const sourceName = sources.find((s) => s.id === msg.query?.data_source_id)?.name

    // The server decides how the answer should read: a bare number, prose, a
    // chart, or a table. The UI does not second-guess it.
    const format: ResponseFormat = msg.query?.response_format ?? (rows.length ? 'table' : 'empty')
    const chart = msg.query?.chart
    const showChart = Boolean(result && chart && chart.type !== 'table')
    const isMeta = format === 'meta'
    const isDataAnswer = Boolean(
      completed && !isMeta && (rows.length > 0 || msg.query?.generated_sql),
    )

    // A "why" answer ships with the evidence behind it and, when the question
    // asked for them, the actions it supports.
    const diagnosis = msg.query?.diagnosis ?? null
    const recommendations = msg.query?.recommendations ?? []

    const metricValue = (() => {
      if (format !== 'metric' || rows.length === 0) return null
      const numericCol = cols.find((c) => {
        const v = rows[0][c]
        return v !== null && v !== '' && !Number.isNaN(Number(String(v).replace(/,/g, '')))
      })
      if (!numericCol) return null
      const raw = Number(String(rows[0][numericCol]).replace(/,/g, ''))
      if (!Number.isFinite(raw)) return null
      return { label: numericCol.replace(/_/g, ' '), value: raw.toLocaleString() }
    })()

    // Only an explicit table answer leads with the grid. Metric / chart /
    // narrative answers stay prose-first; rows are optional under ⋯.
    const tableLeads = format === 'table'
    const showTable = !isMeta && rows.length > 0 && (tableLeads || tableOpen.has(msg.id))
    const menuOpen = menuOpenId === msg.id

    return (
      <div key={msg.id} className="ask-msg ask-msg--ai">
        <div className="ask-ai-avatar" aria-hidden="true">
          <span className="material-symbols-outlined filled">auto_awesome</span>
        </div>

        <div className="ask-ai-stack">
          <div className="ask-msg-head">
            <span className="ask-msg-author">{assistantName}</span>
            <span className="ask-msg-time">{timeLabel(msg.at)}</span>
            {completed && isDataAnswer && (
              <span className="ask-badge is-ok">
                <span className="material-symbols-outlined" aria-hidden="true">
                  check_circle
                </span>
                Grounded in your data
              </span>
            )}
            {sourceName && isDataAnswer && <span className="ask-msg-source">{sourceName}</span>}
          </div>

          <p className="ask-answer">{msg.text}</p>

          {diagnosis && renderDiagnosis(diagnosis)}

          {recommendations.length > 0 && (
            <section className="ask-card ask-actions">
              <header className="ask-card-head">
                <h4>Recommended actions</h4>
                <span className="ask-card-meta">
                  {recommendations.length} suggested from the evidence above
                </span>
              </header>
              <ol className="ask-action-list">
                {recommendations.map((action, index) => (
                  <li key={`${action.title}-${index}`} className={`ask-action is-${action.priority}`}>
                    <span className="ask-action-priority">{PRIORITY_LABEL[action.priority]}</span>
                    <div className="ask-action-body">
                      <h5>{action.title}</h5>
                      <p>{action.detail}</p>
                      {action.basis && <p className="ask-action-basis">{action.basis}</p>}
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          )}

          {diagnosis && recommendations.length === 0 && (
            <div className="ask-followups">
              {FOLLOW_UPS.map((question) => (
                <button
                  key={question}
                  type="button"
                  className="ask-suggest ask-suggest--inline"
                  onClick={() => void sendQuestion(question)}
                  disabled={busy}
                >
                  <span className="material-symbols-outlined" aria-hidden="true">
                    lightbulb
                  </span>
                  <span>{question}</span>
                </button>
              ))}
            </div>
          )}

          {metricValue && (
            <div className="ask-metric">
              <span className="ask-metric-value">{metricValue.value}</span>
              <span className="ask-metric-label">{metricValue.label}</span>
            </div>
          )}

          {msg.error && (
            <div className="ask-error" role="alert">
              <span className="material-symbols-outlined" aria-hidden="true">
                error
              </span>
              <div>
                <p>{msg.error}</p>
                {msg.question && (
                  <button type="button" className="ask-retry" onClick={() => retry(msg)}>
                    <span className="material-symbols-outlined" aria-hidden="true">
                      refresh
                    </span>
                    Try again
                  </button>
                )}
              </div>
            </div>
          )}

          {showChart && result && (
            <section className="ask-card">
              <header className="ask-card-head">
                <h4>{CHART_TITLE[chart?.type ?? 'bar'] ?? 'Visualization'}</h4>
                <span className="ask-card-meta">
                  {format === 'narrative'
                    ? 'supporting view'
                    : (CHART_KIND[chart?.type ?? 'bar'] ?? 'chart')}
                </span>
              </header>
              <ResultChart result={result} chart={msg.query?.chart} height={240} />
            </section>
          )}

          {showTable && (
            <section className="ask-card">
              <header className="ask-card-head">
                <h4>{tableLeads ? 'Result' : 'Underlying rows'}</h4>
                <span className="ask-card-meta">
                  {shownRows.length < rows.length
                    ? `showing ${shownRows.length} of ${rows.length} rows`
                    : `${rows.length} row${rows.length === 1 ? '' : 's'} · ${cols.length} column${
                        cols.length === 1 ? '' : 's'
                      }`}
                </span>
              </header>
              <div className="ask-table-wrap">
                <table>
                  <thead>
                    <tr>
                      {cols.map((col) => (
                        // The header is read by a person; the column name is
                        // how the query happens to spell it.
                        <th key={col} title={col}>{humanizeColumn(col)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {shownRows.map((row, i) => (
                      <tr key={i}>
                        {cols.map((col) => (
                          <td key={col}>{formatCell(row[col])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {msg.sqlOpen && msg.query?.generated_sql && (
            <section className="ask-card ask-card--sql">
              <header className="ask-card-head">
                <h4>Generated SQL</h4>
                {msg.query.mode && <span className="ask-card-meta">via {msg.query.mode}</span>}
              </header>
              <pre>
                <code>{msg.query.generated_sql}</code>
              </pre>
            </section>
          )}

          {(msg.query || msg.error) && (
            <div className="ask-msg-tools">
              <button
                type="button"
                className="ask-tool-icon"
                onClick={() => void copyAnswer(msg)}
                title={copiedId === msg.id ? 'Copied' : 'Copy answer'}
                aria-label={copiedId === msg.id ? 'Copied' : 'Copy answer'}
              >
                <span className="material-symbols-outlined" aria-hidden="true">
                  {copiedId === msg.id ? 'check' : 'content_copy'}
                </span>
              </button>

              {isDataAnswer && (
                <div className={`ask-tool-menu${menuOpen ? ' is-open' : ''}`}>
                  <button
                    type="button"
                    className="ask-tool-icon"
                    aria-expanded={menuOpen}
                    aria-haspopup="menu"
                    title="More actions"
                    aria-label="More actions"
                    onClick={() => setMenuOpenId(menuOpen ? null : msg.id)}
                  >
                    <span className="material-symbols-outlined" aria-hidden="true">
                      more_horiz
                    </span>
                  </button>
                  {menuOpen && (
                    <div className="ask-tool-dropdown" role="menu">
                      {!tableLeads && rows.length > 0 && (
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setTableOpen((prev) => {
                              const next = new Set(prev)
                              if (next.has(msg.id)) next.delete(msg.id)
                              else next.add(msg.id)
                              return next
                            })
                            setMenuOpenId(null)
                          }}
                        >
                          <span className="material-symbols-outlined" aria-hidden="true">
                            table_rows
                          </span>
                          {tableOpen.has(msg.id) ? 'Hide underlying rows' : 'Show underlying rows'}
                        </button>
                      )}
                      {msg.query?.generated_sql && (
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            toggleSql(msg.id)
                            setMenuOpenId(null)
                          }}
                        >
                          <span className="material-symbols-outlined" aria-hidden="true">
                            code
                          </span>
                          {msg.sqlOpen ? 'Hide SQL' : 'View SQL'}
                        </button>
                      )}
                      {completed && (
                        <>
                          <button
                            type="button"
                            role="menuitem"
                            onClick={() => {
                              void api.downloadQueryCsv(msg.query!.id)
                              setMenuOpenId(null)
                            }}
                          >
                            <span className="material-symbols-outlined" aria-hidden="true">
                              download
                            </span>
                            Export CSV
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            disabled={msg.pinned}
                            onClick={() => {
                              void pinQuery(msg.id, msg.query!)
                              setMenuOpenId(null)
                            }}
                          >
                            <span className="material-symbols-outlined" aria-hidden="true">
                              push_pin
                            </span>
                            {msg.pinned ? 'Pinned to dashboard' : 'Pin to dashboard'}
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className={`ask-ai${isEmpty ? ' ask-ai--empty' : ''}`}>
      {!isEmpty && (
        <div className="ask-toolbar">
          <div className="ask-toolbar-copy">
            <button
              type="button"
              className="ask-toolbar-title"
              onClick={() => void renameChat()}
              title="Rename this chat"
            >
              <span className="ask-toolbar-title-text">{title ?? 'New chat'}</span>
              <span className="material-symbols-outlined" aria-hidden="true">
                edit
              </span>
            </button>
            <span className="ask-toolbar-label">
              {messages.filter((m) => m.role === 'user').length} message
              {messages.filter((m) => m.role === 'user').length === 1 ? '' : 's'}
            </span>
          </div>
          <button type="button" className="ask-toolbar-btn" onClick={newChat}>
            <span className="material-symbols-outlined" aria-hidden="true">
              add_comment
            </span>
            New chat
          </button>
        </div>
      )}

      <div className="ask-ai-thread" ref={threadRef}>
        {restoring && (
          <div className="ask-restoring">
            <span className="cl-spinner" aria-hidden="true" />
            Loading this chat…
          </div>
        )}

        {isEmpty ? (
          <div className="ask-ai-hero">
            <div className="ask-ai-hero-mark" aria-hidden="true">
              <span className="material-symbols-outlined filled">auto_awesome</span>
            </div>
            <h1 className="ask-ai-hero-title">
              {hasSources ? 'What do you want to know?' : 'Connect data to get started'}
            </h1>
            <p className="ask-ai-hero-sub">
              {hasSources
                ? `Ask in plain English. ${assistantName} writes the SQL, runs it across your ${
                    sources.length
                  } connected dataset${sources.length === 1 ? '' : 's'}, and answers in plain language.`
                : 'Upload a CSV or connect a database under Data Sources, then come back and ask a question.'}
            </p>

            {suggestions.length > 0 && (
              <div className="ask-suggest-list">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="ask-suggest"
                    onClick={() => void sendQuestion(s)}
                    disabled={busy}
                  >
                    <span className="material-symbols-outlined" aria-hidden="true">
                      arrow_outward
                    </span>
                    <span>{s}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="ask-ai-list">
            {messages.map((msg) =>
              msg.role === 'user' ? (
                <div key={msg.id} className="ask-msg ask-msg--user">
                  <div className="ask-bubble--user">
                    <p>{msg.text}</p>
                  </div>
                  <span className="ask-msg-time ask-msg-time--user">{timeLabel(msg.at)}</span>
                </div>
              ) : (
                renderAssistant(msg)
              ),
            )}

            {busy && (
              <div className="ask-msg ask-msg--ai">
                <div className="ask-ai-avatar" aria-hidden="true">
                  <span className="material-symbols-outlined filled">auto_awesome</span>
                </div>
                <div className="ask-ai-stack">
                  <div className="ask-thinking">
                    <span className="ask-typing-dots" aria-hidden="true">
                      <i />
                      <i />
                      <i />
                    </span>
                    {thinkingLabel}
                  </div>
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <div className="ask-composer">
        <div className="ask-composer-inner">
          {!hasSources && (
            <p className="ask-composer-warning">
              <span className="material-symbols-outlined" aria-hidden="true">
                info
              </span>
              No data sources connected yet — questions have nothing to run against.
            </p>
          )}

          <form
            className="ask-input-pill"
            onSubmit={(e) => {
              e.preventDefault()
              void sendQuestion(draft)
            }}
          >
            <textarea
              ref={textareaRef}
              rows={1}
              value={draft}
              placeholder={
                hasSources ? 'Ask a question about your data…' : 'Add a data source first…'
              }
              aria-label="Ask a question about your data"
              onChange={(e) => {
                setDraft(e.target.value)
                resizeTextarea()
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void sendQuestion(draft)
                }
              }}
              disabled={!hasSources}
            />

            {busy ? (
              <button
                type="button"
                className="ask-send-round is-stop"
                onClick={stopQuery}
                aria-label="Stop generating"
                title="Stop"
              >
                <span className="material-symbols-outlined filled" aria-hidden="true">
                  stop_circle
                </span>
              </button>
            ) : (
              <button
                type="submit"
                className={`ask-send-round${draft.trim() ? ' is-ready' : ''}`}
                disabled={!hasSources || !draft.trim()}
                aria-label="Send question"
              >
                <span className="material-symbols-outlined" aria-hidden="true">
                  arrow_upward
                </span>
              </button>
            )}
          </form>

          <p className="ask-disclaimer">
            <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line ·{' '}
            {assistantName} can make mistakes, so check the generated SQL.
          </p>
        </div>
      </div>
    </div>
  )
}
