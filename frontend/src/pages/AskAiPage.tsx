import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  parseSchema,
  type AppSettings,
  type DataSource,
  type QueryRecord,
  type ResponseFormat,
} from '../api/client'
import { ResultChart } from '../components/ResultChart'
import { formatCell } from '../lib/format'
import { getSessionId, startNewSession, THREAD_KEY } from '../lib/session'
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
}

/**
 * The thread survives navigation and reloads. Only light metadata is stored —
 * result rows are re-fetched from the API by query id so the transcript can
 * never drift from what the server actually returned. `THREAD_KEY` lives in
 * lib/session so starting a new session clears it in one step.
 */
type StoredMessage = {
  id: string
  role: 'user' | 'assistant'
  text: string
  question?: string
  queryId?: number
  error?: string
  pinned?: boolean
  at: number
}

function saveThread(messages: ChatMessage[]) {
  try {
    const slim: StoredMessage[] = messages.map((m) =>
      m.role === 'user'
        ? { id: m.id, role: 'user', text: m.text, at: m.at }
        : {
            id: m.id,
            role: 'assistant',
            text: m.text,
            question: m.question,
            queryId: m.query?.id,
            error: m.error,
            pinned: m.pinned,
            at: m.at,
          },
    )
    sessionStorage.setItem(THREAD_KEY, JSON.stringify(slim))
  } catch {
    /* storage unavailable or full */
  }
}

function readStoredThread(): StoredMessage[] {
  try {
    const raw = sessionStorage.getItem(THREAD_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? (parsed as StoredMessage[]) : []
  } catch {
    return []
  }
}

const CHART_TITLE: Record<string, string> = {
  pie: 'Breakdown',
  line: 'Trend',
  bar: 'Comparison',
}

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
}: Props) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [restoring, setRestoring] = useState(() => readStoredThread().length > 0)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  /** Answers that lead with prose or a chart keep their rows collapsed. */
  const [tableOpen, setTableOpen] = useState<Set<string>>(() => new Set())

  const threadRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const hasSources = sources.length > 0
  const suggestions = useMemo(() => suggestionsForWorkspace(sources), [sources])
  const assistantName = branding?.platform_name || 'Cognitive Logic'
  const isEmpty = messages.length === 0 && !busy && !restoring

  // --- restore the thread ------------------------------------------------
  useEffect(() => {
    const stored = readStoredThread()
    if (stored.length === 0) return
    let cancelled = false

    void (async () => {
      const ids = [...new Set(stored.map((m) => m.queryId).filter((id): id is number => !!id))]
      const records = new Map<number, QueryRecord>()
      await Promise.all(
        ids.map(async (id) => {
          try {
            records.set(id, await api.getQuery(id))
          } catch {
            /* the query was deleted with its data source */
          }
        }),
      )
      if (cancelled) return
      setMessages(
        stored.map((m) =>
          m.role === 'user'
            ? { id: m.id, role: 'user', text: m.text, at: m.at }
            : {
                id: m.id,
                role: 'assistant',
                text: (m.queryId ? records.get(m.queryId)?.answer : null) ?? m.text,
                question: m.question ?? '',
                query: m.queryId ? records.get(m.queryId) : undefined,
                error: m.error,
                pinned: m.pinned,
                sqlOpen: false,
                at: m.at,
              },
        ),
      )
      setRestoring(false)
    })()

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!restoring) saveThread(messages)
  }, [messages, restoring])

  // Scroll the thread container only — never the whole document.
  useEffect(() => {
    const el = threadRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: messages.length > 1 ? 'smooth' : 'auto' })
  }, [messages, busy])

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
          sessionId: getSessionId(),
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
          setMessages((prev) => [
            ...prev,
            {
              id: uid(),
              role: 'assistant',
              text: 'I could not answer that question.',
              question,
              error: errorDetail(err),
              at: Date.now(),
            },
          ])
        }
      } finally {
        abortRef.current = null
        setBusy(false)
      }
    },
    [busy, hasSources, onAnswered],
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

  function newSession() {
    abortRef.current?.abort()
    setMessages([])
    setDraft('')
    startNewSession()
    textareaRef.current?.focus()
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
    const parts = [msg.question, msg.text, msg.query?.generated_sql ?? '']
    try {
      await navigator.clipboard.writeText(parts.filter(Boolean).join('\n\n'))
      setCopiedId(msg.id)
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

    // Only a table answer leads with the grid. A number, a chart, or prose is
    // the answer; the rows behind it stay one click away.
    const tableLeads = format === 'table' || (format === 'metric' && !metricValue)
    const showTable = rows.length > 0 && (tableLeads || tableOpen.has(msg.id))

    return (
      <div key={msg.id} className="ask-msg ask-msg--ai">
        <div className="ask-ai-avatar" aria-hidden="true">
          <span className="material-symbols-outlined filled">auto_awesome</span>
        </div>

        <div className="ask-ai-stack">
          <div className="ask-msg-head">
            <span className="ask-msg-author">{assistantName}</span>
            <span className="ask-msg-time">{timeLabel(msg.at)}</span>
            {completed && (
              <span className="ask-badge is-ok">
                <span className="material-symbols-outlined" aria-hidden="true">
                  check_circle
                </span>
                Ran on your data
              </span>
            )}
            {sourceName && <span className="ask-msg-source">{sourceName}</span>}
          </div>

          <p className="ask-answer">{msg.text}</p>

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
                  {format === 'narrative' ? 'supporting view' : `${chart?.type} chart`}
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
                        <th key={col}>{col}</th>
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
            <div className="ask-actions">
              {!tableLeads && rows.length > 0 && (
                <button
                  type="button"
                  className="ask-action"
                  onClick={() =>
                    setTableOpen((prev) => {
                      const next = new Set(prev)
                      if (next.has(msg.id)) next.delete(msg.id)
                      else next.add(msg.id)
                      return next
                    })
                  }
                >
                  <span className="material-symbols-outlined" aria-hidden="true">
                    table_rows
                  </span>
                  {tableOpen.has(msg.id)
                    ? 'Hide rows'
                    : `Show ${rows.length} row${rows.length === 1 ? '' : 's'}`}
                </button>
              )}
              {msg.query?.generated_sql && (
                <button type="button" className="ask-action" onClick={() => toggleSql(msg.id)}>
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
                    className="ask-action"
                    onClick={() => void api.downloadQueryCsv(msg.query!.id)}
                  >
                    <span className="material-symbols-outlined" aria-hidden="true">
                      download
                    </span>
                    CSV
                  </button>
                  <button
                    type="button"
                    className="ask-action"
                    disabled={msg.pinned}
                    onClick={() => void pinQuery(msg.id, msg.query!)}
                  >
                    <span className="material-symbols-outlined" aria-hidden="true">
                      push_pin
                    </span>
                    {msg.pinned ? 'Pinned' : 'Pin to dashboard'}
                  </button>
                </>
              )}
              <button type="button" className="ask-action" onClick={() => void copyAnswer(msg)}>
                <span className="material-symbols-outlined" aria-hidden="true">
                  {copiedId === msg.id ? 'check' : 'content_copy'}
                </span>
                {copiedId === msg.id ? 'Copied' : 'Copy'}
              </button>
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
          <span className="ask-toolbar-label">
            {messages.filter((m) => m.role === 'user').length} question
            {messages.filter((m) => m.role === 'user').length === 1 ? '' : 's'} in this session
          </span>
          <button type="button" className="ask-toolbar-btn" onClick={newSession}>
            <span className="material-symbols-outlined" aria-hidden="true">
              add_comment
            </span>
            New session
          </button>
        </div>
      )}

      <div className="ask-ai-thread" ref={threadRef}>
        {restoring && (
          <div className="ask-restoring">
            <span className="cl-spinner" aria-hidden="true" />
            Restoring your analysis…
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
                  } connected dataset${sources.length === 1 ? '' : 's'}, and shows you the rows.`
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
                    Writing SQL and querying your data…
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
