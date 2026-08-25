import { useEffect, useMemo, useState } from 'react'
import { api, type AppSettings, type QueryRecord, type User } from '../api/client'
import { EmptyState, InlineMessage, Skeleton } from '../components/Feedback'
import { ResultChart } from '../components/ResultChart'
import { formatCell } from '../lib/format'
import './HistoryPage.css'

type Props = {
  onNewAnalysis: () => void
  branding?: AppSettings | null
  user?: User | null
  focusQueryId?: number | null
  onFocusConsumed?: () => void
}

type DayGroup = { label: string; items: QueryRecord[] }

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function relativeWhen(iso: string): string {
  const date = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24 && startOfDay(date) === startOfDay(now)) {
    return hours === 1 ? '1 hour ago' : `${hours} hours ago`
  }
  if (startOfDay(date) === startOfDay(now) - 86400000) {
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function groupByDay(queries: QueryRecord[]): DayGroup[] {
  const now = new Date()
  const today = startOfDay(now)
  const yesterday = today - 86400000
  const weekAgo = today - 7 * 86400000

  const buckets: Record<string, QueryRecord[]> = {
    Today: [],
    Yesterday: [],
    'Previous 7 Days': [],
    Earlier: [],
  }

  for (const q of queries) {
    const t = startOfDay(new Date(q.created_at))
    if (t === today) buckets.Today.push(q)
    else if (t === yesterday) buckets.Yesterday.push(q)
    else if (t >= weekAgo) buckets['Previous 7 Days'].push(q)
    else buckets.Earlier.push(q)
  }

  return Object.entries(buckets)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }))
}

function statusDot(status: string): 'ok' | 'warn' | 'neutral' {
  if (status === 'completed') return 'ok'
  if (status === 'failed' || status === 'error') return 'warn'
  return 'neutral'
}

export function HistoryPage({
  onNewAnalysis,
  branding,
  user,
  focusQueryId,
  onFocusConsumed,
}: Props) {
  const [queries, setQueries] = useState<QueryRecord[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [selected, setSelected] = useState<QueryRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sqlOpen, setSqlOpen] = useState(false)
  const [pinned, setPinned] = useState(false)
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null)

  const groups = useMemo(() => groupByDay(queries), [queries])

  useEffect(() => {
    setLoading(true)
    api
      .listQueries()
      .then((list) => {
        setQueries(list)
        if (list.length > 0) setSelectedId(list[0].id)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (focusQueryId == null) return
    setSelectedId(focusQueryId)
    onFocusConsumed?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusQueryId])

  useEffect(() => {
    if (selectedId == null) {
      setSelected(null)
      return
    }
    const cached = queries.find((q) => q.id === selectedId)
    if (cached?.result || cached?.status === 'failed') {
      setSelected(cached)
      setSqlOpen(false)
      setPinned(false)
      setFeedback(null)
      return
    }
    let cancelled = false
    void api
      .getQuery(selectedId)
      .then((q) => {
        if (cancelled) return
        setSelected(q)
        setQueries((prev) => prev.map((row) => (row.id === q.id ? q : row)))
        setSqlOpen(false)
        setPinned(false)
        setFeedback(null)
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message)
      })
    return () => {
      cancelled = true
    }
    // Intentionally only re-run when selection changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  async function handleCopy() {
    if (!selected) return
    const text = [
      selected.natural_language,
      selected.explanation ?? '',
      selected.generated_sql ?? '',
    ]
      .filter(Boolean)
      .join('\n\n')
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      /* ignore */
    }
  }

  async function handlePin() {
    if (!selected || selected.status !== 'completed') return
    try {
      const dash = await api.ensureDefaultDashboard()
      await api.addDashboardWidget(dash.id, {
        query_id: selected.id,
        title: selected.natural_language.slice(0, 80),
        chart_type: selected.chart?.type,
      })
      setPinned(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Pin failed')
    }
  }

  const verified = selected?.status === 'completed'
  const showChart =
    selected?.result && selected.chart && selected.chart.type !== 'table'
  const rows = selected?.result?.rows ?? []
  const cols = selected?.result?.columns ?? []
  const platformLabel = `${branding?.platform_name || 'Cognitive Logic'} response`

  return (
    <div className="qa-history">
      <aside className="qa-list-pane">
        <div className="qa-list-head">
          <h2>Q&amp;A History</h2>
          <button type="button" className="qa-icon-btn" aria-label="Filter" disabled>
            <span className="material-symbols-outlined" aria-hidden="true">filter_list</span>
          </button>
        </div>

        <div className="qa-list-scroll">
          {loading && (
            <div className="qa-skeletons">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="qa-skeleton-item">
                  <Skeleton width={70} height={11} />
                  <Skeleton width="88%" height={13} />
                </div>
              ))}
            </div>
          )}
          {error && <InlineMessage tone="error">{error}</InlineMessage>}
          {!loading && queries.length === 0 && (
            <div className="qa-list-empty">
              <span className="material-symbols-outlined" aria-hidden="true">history</span>
              <p>No questions asked yet</p>
              <button type="button" className="qa-new-btn" onClick={onNewAnalysis}>
                <span className="material-symbols-outlined" aria-hidden="true">add</span>
                New analysis
              </button>
            </div>
          )}

          {groups.map((group) => (
            <div key={group.label} className="qa-group">
              <p className="qa-group-label">{group.label}</p>
              {group.items.map((q) => {
                const dot = statusDot(q.status)
                const active = q.id === selectedId
                return (
                  <button
                    key={q.id}
                    type="button"
                    className={`qa-item${active ? ' is-active' : ''}`}
                    onClick={() => setSelectedId(q.id)}
                  >
                    {active && <span className="qa-item-accent" aria-hidden />}
                    <div className="qa-item-meta">
                      <span className="qa-item-when">{relativeWhen(q.created_at)}</span>
                      {dot !== 'neutral' && (
                        <span className={`qa-dot qa-dot--${dot}`} aria-hidden />
                      )}
                    </div>
                    <p className="qa-item-text">{q.natural_language}</p>
                  </button>
                )
              })}
            </div>
          ))}
        </div>
      </aside>

      <section className="qa-detail-pane">
        {!selected && !loading && (
          <div className="qa-detail-empty">
            <EmptyState
              icon="forum"
              title={queries.length === 0 ? 'Nothing asked yet' : 'Select a question'}
              body={
                <p>
                  {queries.length === 0
                    ? 'Questions you ask in Ask AI are recorded here with the SQL that ran and the rows it returned.'
                    : 'Pick a question from the list to review its answer, chart, and generated SQL.'}
                </p>
              }
              action={
                <button type="button" className="qa-new-btn" onClick={onNewAnalysis}>
                  <span className="material-symbols-outlined" aria-hidden="true">add</span>
                  New analysis
                </button>
              }
            />
          </div>
        )}

        {selected && (
          <div className="qa-detail-inner">
            <div className="qa-actions">
              <div className="qa-actions-left">
                <button type="button" className="qa-action" onClick={() => void handleCopy()}>
                  <span className="material-symbols-outlined" aria-hidden="true">content_copy</span>
                  Copy
                </button>
                {selected.status === 'completed' && (
                  <>
                    <button
                      type="button"
                      className="qa-action"
                      onClick={() => void api.downloadQueryCsv(selected.id)}
                    >
                      <span className="material-symbols-outlined" aria-hidden="true">download</span>
                      CSV
                    </button>
                    <button
                      type="button"
                      className="qa-action"
                      disabled={pinned}
                      onClick={() => void handlePin()}
                    >
                      <span className="material-symbols-outlined" aria-hidden="true">push_pin</span>
                      {pinned ? 'Pinned' : 'Pin'}
                    </button>
                  </>
                )}
              </div>
            </div>

            <header className="qa-question">
              <h1>{selected.natural_language}</h1>
              <div className="qa-question-meta">
                <span>Asked {relativeWhen(selected.created_at)}</span>
                <span className="qa-meta-dot" aria-hidden />
                <span>by {user?.full_name || user?.email || 'you'}</span>
              </div>
            </header>

            <article className="qa-response">
              <div className="qa-response-head">
                <span className="material-symbols-outlined" aria-hidden="true">auto_awesome</span>
                <span className="qa-response-label">{platformLabel}</span>
                <span className={`qa-verified${verified ? ' is-ok' : ' is-warn'}`}>
                  <span className="material-symbols-outlined" aria-hidden="true">
                    {verified ? 'check_circle' : 'warning'}
                  </span>
                  {verified ? 'Verified' : 'Needs review'}
                </span>
              </div>

              <div className="qa-response-body">
                <p>
                  {selected.explanation ??
                    (selected.result
                      ? `Returned ${selected.result.rows.length} row(s).`
                      : selected.status === 'failed'
                        ? 'This query did not complete successfully.'
                        : 'No explanation available.')}
                </p>
              </div>

              {showChart && selected.result && (
                <div className="qa-viz">
                  <div className="qa-viz-head">
                    <div>
                      <h3>{selected.chart?.type?.toUpperCase()} chart</h3>
                      <p className="qa-viz-sub">Recommended visualization</p>
                    </div>
                  </div>
                  <ResultChart result={selected.result} chart={selected.chart} height={220} />
                </div>
              )}

              {rows.length > 0 && (
                <div className="qa-table-wrap">
                  <table>
                    <thead>
                      <tr>
                        {cols.map((c) => (
                          <th key={c}>{c}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.slice(0, 25).map((row, i) => (
                        <tr key={i}>
                          {cols.map((c) => (
                            <td key={c}>{formatCell(row[c])}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {selected.generated_sql && (
                <div className="qa-sql-block">
                  <button
                    type="button"
                    className="qa-sql-toggle"
                    onClick={() => setSqlOpen((v) => !v)}
                    aria-expanded={sqlOpen}
                  >
                    <span className="qa-sql-toggle-label">
                      <span className="material-symbols-outlined" aria-hidden="true">code</span>
                      View generated query
                    </span>
                    <span className="material-symbols-outlined" aria-hidden="true">
                      {sqlOpen ? 'expand_less' : 'expand_more'}
                    </span>
                  </button>
                  {sqlOpen && (
                    <pre className="qa-sql-pre">
                      <code>{selected.generated_sql}</code>
                    </pre>
                  )}
                </div>
              )}
            </article>

            <div className="qa-feedback">
              <p>Was this answer helpful?</p>
              <button
                type="button"
                className={`qa-fb${feedback === 'up' ? ' is-on' : ''}`}
                aria-label="Helpful"
                onClick={() => setFeedback('up')}
              >
                <span className="material-symbols-outlined" aria-hidden="true">thumb_up</span>
              </button>
              <button
                type="button"
                className={`qa-fb qa-fb--down${feedback === 'down' ? ' is-on' : ''}`}
                aria-label="Not helpful"
                onClick={() => setFeedback('down')}
              >
                <span className="material-symbols-outlined" aria-hidden="true">thumb_down</span>
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
