import { useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  parseSchema,
  type AppSettings,
  type DataSource,
  type QueryRecord,
} from '../api/client'
import { ResultChart } from '../components/ResultChart'
import { formatCell } from '../lib/format'
import './AskAiPage.css'

/**
 * Suggestions are derived from the selected source's real schema and field
 * mapping, so every chip is a question this dataset can actually answer.
 */
function suggestionsFor(source: DataSource | undefined): string[] {
  if (!source) return []
  const mapping = source.field_mapping ?? {}
  const columnFor = (canonical: string) =>
    Object.entries(mapping).find(([, canon]) => canon === canonical)?.[0]

  const schema = parseSchema(source.schema_json)
  const columns = schema?.tables[0]?.columns.map((c) => c.name) ?? Object.keys(mapping)

  const measure = columnFor('Revenue') ?? columnFor('Profit') ?? columnFor('Quantity')
  const dimension =
    columnFor('Region') ?? columnFor('Category') ?? columnFor('Store ID') ?? columnFor('Product')
  const dateCol = columnFor('Date') ?? columnFor('Timestamp')

  const out: string[] = []
  if (measure && dimension) out.push(`Total ${measure} by ${dimension}`)
  if (measure) out.push(`Top 5 rows by ${measure}`)
  if (measure && dateCol) out.push(`${measure} over time by ${dateCol}`)
  if (dimension) out.push(`Count of records per ${dimension}`)
  if (out.length === 0 && columns.length > 0) {
    out.push(`Show the first 20 rows`, `How many records are there?`)
    if (columns[0]) out.push(`Group by ${columns[0]}`)
  }
  return out.slice(0, 4)
}

type ChatMessage =
  | { id: string; role: 'user'; text: string }
  | {
      id: string
      role: 'assistant'
      text: string
      query?: QueryRecord
      error?: string
      sqlOpen?: boolean
      pinned?: boolean
    }

type Props = {
  sources: DataSource[]
  branding?: AppSettings | null
  pendingQuestion?: string | null
  onPendingConsumed?: () => void
  onAnswered?: () => void
}

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export function AskAiPage({
  sources,
  branding,
  pendingQuestion,
  onPendingConsumed,
  onAnswered,
}: Props) {
  const [sourceId, setSourceId] = useState<number | ''>('')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (sources.length === 0) {
      setSourceId('')
      return
    }
    if (sourceId === '' || !sources.some((s) => s.id === sourceId)) {
      setSourceId(sources[0].id)
    }
  }, [sources, sourceId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  const selectedSource = useMemo(
    () => sources.find((s) => s.id === sourceId),
    [sources, sourceId],
  )
  const suggestions = useMemo(() => suggestionsFor(selectedSource), [selectedSource])
  const assistantName = branding?.platform_name || 'Cognitive Logic'

  // A question handed over from the command palette runs once the source is ready.
  useEffect(() => {
    if (!pendingQuestion || sourceId === '' || busy) return
    void sendQuestion(pendingQuestion)
    onPendingConsumed?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuestion, sourceId])

  function resizeTextarea() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = ''
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`
  }

  async function sendQuestion(text: string) {
    const question = text.trim()
    if (!question || sourceId === '' || busy) return

    setDraft('')
    if (textareaRef.current) {
      textareaRef.current.style.height = ''
    }

    const userMsg: ChatMessage = { id: uid(), role: 'user', text: question }
    setMessages((prev) => [...prev, userMsg])
    setBusy(true)

    try {
      const result = await api.runQuery(sourceId, question)
      const summary =
        result.explanation ??
        (result.result
          ? `Returned ${result.result.rows.length} row(s).`
          : 'Query completed.')
      setMessages((prev) => [
        ...prev,
        {
          id: uid(),
          role: 'assistant',
          text: summary,
          query: result,
          sqlOpen: false,
        },
      ])
      onAnswered?.()
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Query failed'
      let detail = message
      try {
        const parsed = JSON.parse(message) as { detail?: string }
        if (parsed.detail) detail = parsed.detail
      } catch {
        /* keep message */
      }
      setMessages((prev) => [
        ...prev,
        {
          id: uid(),
          role: 'assistant',
          text: 'I could not complete that question.',
          error: detail,
        },
      ])
    } finally {
      setBusy(false)
    }
  }

  function toggleSql(id: string) {
    setMessages((prev) =>
      prev.map((m) =>
        m.role === 'assistant' && m.id === id ? { ...m, sqlOpen: !m.sqlOpen } : m,
      ),
    )
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
        prev.map((m) =>
          m.role === 'assistant' && m.id === msgId ? { ...m, pinned: true } : m,
        ),
      )
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Pin failed'
      setMessages((prev) => [
        ...prev,
        { id: uid(), role: 'assistant', text: 'Could not pin to dashboard.', error: message },
      ])
    }
  }

  return (
    <div className="ask-ai">
      <div className="ask-ai-thread">
        <div className="ask-ai-day">
          {new Date().toLocaleDateString(undefined, {
            weekday: 'long',
            month: 'short',
            day: 'numeric',
          })}
        </div>

        {messages.length === 0 && (
          <div className="ask-ai-empty">
            <span className="material-symbols-outlined filled" aria-hidden="true">auto_awesome</span>
            <p>
              {selectedSource
                ? `Ask a question about “${selectedSource.name}”.`
                : 'Connect a data source to start asking questions.'}
            </p>
            <p className="ask-ai-empty-hint">
              Every answer is generated as SQL and run against your own data. Without an AI
              provider key the built-in heuristic planner handles simple questions; add a key
              in Settings for full natural-language querying.
            </p>
          </div>
        )}

        {messages.map((msg) => {
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="ask-msg ask-msg--user">
                <div className="ask-bubble ask-bubble--user">
                  <p>{msg.text}</p>
                </div>
              </div>
            )
          }

          const rows = msg.query?.result?.rows ?? []
          const cols = msg.query?.result?.columns ?? []
          const verified = msg.query?.status === 'completed' && !msg.error
          const showChart =
            msg.query?.result &&
            msg.query.chart &&
            msg.query.chart.type !== 'table'

          return (
            <div key={msg.id} className="ask-msg ask-msg--ai">
              <div className="ask-ai-avatar" aria-hidden>
                <span className="material-symbols-outlined" aria-hidden="true">psychology</span>
              </div>
              <div className="ask-ai-stack">
                <div className="ask-bubble ask-bubble--ai">
                  <p>{msg.text}</p>
                  {msg.error && <p className="ask-error">{msg.error}</p>}

                  {showChart && msg.query?.result && (
                    <div className="ask-chart">
                      <h4 className="text-label-caps">
                        {msg.query.chart?.type?.toUpperCase()} · recommended
                      </h4>
                      <ResultChart result={msg.query.result} chart={msg.query.chart} />
                    </div>
                  )}

                  {rows.length > 0 && (
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
                          {rows.slice(0, 20).map((row, i) => (
                            <tr key={i}>
                              {cols.map((col) => (
                                <td key={col}>{formatCell(row[col])}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {(msg.query?.generated_sql || msg.error) && (
                    <div className="ask-meta">
                      <div className={`ask-badge${verified ? ' is-ok' : ' is-warn'}`}>
                        <span className="material-symbols-outlined" aria-hidden="true">
                          {verified ? 'check_circle' : 'warning'}
                        </span>
                        <span>{verified ? 'Verified' : 'Needs review'}</span>
                      </div>
                      <div className="ask-meta-actions">
                        {msg.query?.status === 'completed' && (
                          <>
                            <button
                              type="button"
                              className="ask-sql-toggle"
                              onClick={() => void api.downloadQueryCsv(msg.query!.id)}
                            >
                              <span className="material-symbols-outlined" aria-hidden="true">download</span>
                              CSV
                            </button>
                            <button
                              type="button"
                              className="ask-sql-toggle"
                              disabled={msg.pinned}
                              onClick={() => void pinQuery(msg.id, msg.query!)}
                            >
                              <span className="material-symbols-outlined" aria-hidden="true">push_pin</span>
                              {msg.pinned ? 'Pinned' : 'Pin'}
                            </button>
                          </>
                        )}
                        {msg.query?.generated_sql && (
                          <button type="button" className="ask-sql-toggle" onClick={() => toggleSql(msg.id)}>
                            <span className="material-symbols-outlined" aria-hidden="true">code</span>
                            View query
                          </button>
                        )}
                      </div>
                    </div>
                  )}

                  {msg.sqlOpen && msg.query?.generated_sql && (
                    <div className="ask-sql">
                      <pre>
                        <code>{msg.query.generated_sql}</code>
                      </pre>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}

        {busy && (
          <div className="ask-msg ask-msg--ai">
            <div className="ask-ai-avatar" aria-hidden>
              <span className="material-symbols-outlined" aria-hidden="true">psychology</span>
            </div>
            <div className="ask-bubble ask-bubble--ai ask-typing">
              <span className="ask-typing-dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              Working through your data…
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="ask-composer">
        <div className="ask-composer-inner">
          <div className="ask-source-row">
            <label>
              Data source
              <select
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value ? Number(e.target.value) : '')}
                disabled={sources.length === 0}
              >
                {sources.length === 0 && <option value="">No sources — add one first</option>}
                {sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} · {s.source_type}
                    {s.row_count != null ? ` · ${s.row_count.toLocaleString()} rows` : ''}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {suggestions.length > 0 && (
            <div className="ask-chips">
              <span className="ask-chips-label">Try</span>
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="ask-chip"
                  onClick={() => void sendQuestion(s)}
                  disabled={busy || sourceId === ''}
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          <form
            className="ask-input-box"
            onSubmit={(e) => {
              e.preventDefault()
              void sendQuestion(draft)
            }}
          >
            <span className="material-symbols-outlined ask-sparkle" aria-hidden="true">auto_awesome</span>
            <textarea
              ref={textareaRef}
              rows={1}
              value={draft}
              placeholder="Ask a question about your data..."
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
              disabled={busy || sourceId === ''}
            />
            <button
              type="submit"
              className="ask-send"
              disabled={busy || sourceId === '' || !draft.trim()}
              aria-label="Send"
            >
              <span className="material-symbols-outlined" aria-hidden="true">send</span>
            </button>
          </form>
          <p className="ask-disclaimer">
            {assistantName} generates SQL from your question — always check the query before
            acting on the result.
          </p>
        </div>
      </div>
    </div>
  )
}
