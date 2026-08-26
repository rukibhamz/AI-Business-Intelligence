import { useEffect, useMemo, useState } from 'react'
import {
  api,
  type Dashboard,
  type Finding,
  type FindingSeverity,
  type QueryRecord,
} from '../api/client'
import { EmptyState, InlineMessage, Skeleton, Spinner } from '../components/Feedback'
import { ResultChart } from '../components/ResultChart'
import { formatCell, formatRelative, humanizeColumn } from '../lib/format'
import type { AppView } from '../layouts/navigation'
import './FindingsPage.css'

type Props = {
  findings: Finding[]
  loading: boolean
  error: string | null
  generatedAt: string | null
  onRefresh: () => void
  onNavigate: (view: AppView) => void
}

const SEVERITY_ORDER: Record<FindingSeverity, number> = {
  critical: 0,
  warning: 1,
  opportunity: 2,
  info: 3,
}

const SEVERITY_LABEL: Record<FindingSeverity, string> = {
  critical: 'Critical',
  warning: 'Warning',
  opportunity: 'Opportunity',
  info: 'Info',
}

type Filter = 'all' | FindingSeverity
type SortBy = 'severity' | 'source'

const DISMISS_KEY = 'cl_dismissed_findings'

function loadDismissed(): Set<string> {
  try {
    const raw = localStorage.getItem(DISMISS_KEY)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? new Set(parsed.map(String)) : new Set()
  } catch {
    return new Set()
  }
}

function saveDismissed(ids: Set<string>) {
  try {
    localStorage.setItem(DISMISS_KEY, JSON.stringify([...ids]))
  } catch {
    /* storage unavailable */
  }
}

export function FindingsPage({
  findings,
  loading,
  error,
  generatedAt,
  onRefresh,
  onNavigate,
}: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const [sortBy, setSortBy] = useState<SortBy>('severity')
  const [dismissed, setDismissed] = useState<Set<string>>(loadDismissed)

  // Pinned reports (live dashboards + saved queries)
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [queries, setQueries] = useState<Record<number, QueryRecord>>({})
  const [dashLoading, setDashLoading] = useState(true)
  const [dashError, setDashError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [newName, setNewName] = useState('')

  const active = dashboards.find((d) => d.id === activeId) ?? dashboards[0] ?? null

  useEffect(() => {
    saveDismissed(dismissed)
  }, [dismissed])

  const visible = useMemo(() => {
    let list = findings.filter((f) => !dismissed.has(f.id))
    if (filter !== 'all') list = list.filter((f) => f.severity === filter)
    if (sortBy === 'severity') {
      list = [...list].sort(
        (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
      )
    } else {
      list = [...list].sort((a, b) =>
        (a.source_name ?? '').localeCompare(b.source_name ?? ''),
      )
    }
    return list
  }, [findings, dismissed, filter, sortBy])

  const activeCount = findings.filter((f) => !dismissed.has(f.id)).length
  const dismissedCount = findings.filter((f) => dismissed.has(f.id)).length

  const counts = useMemo(() => {
    const map: Record<string, number> = { all: activeCount }
    for (const f of findings) {
      if (dismissed.has(f.id)) continue
      map[f.severity] = (map[f.severity] ?? 0) + 1
    }
    return map
  }, [findings, dismissed, activeCount])

  async function refreshDashboards() {
    setDashError(null)
    const list = await api.listDashboards()
    if (list.length === 0) {
      const created = await api.ensureDefaultDashboard()
      setDashboards([created])
      setActiveId(created.id)
      return
    }
    setDashboards(list)
    setActiveId((prev) => prev ?? list[0].id)
  }

  useEffect(() => {
    setDashLoading(true)
    refreshDashboards()
      .catch((e: Error) => setDashError(e.message))
      .finally(() => setDashLoading(false))
  }, [])

  useEffect(() => {
    if (!active) return
    const missing = active.widgets.map((w) => w.query_id).filter((id) => !queries[id])
    if (missing.length === 0) return
    void Promise.all(
      missing.map(async (id) => {
        try {
          const q = await api.getQuery(id)
          setQueries((prev) => ({ ...prev, [id]: q }))
        } catch {
          /* widget points at a deleted query */
        }
      }),
    )
  }, [active, queries])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    setBusy(true)
    try {
      const d = await api.createDashboard(newName.trim())
      setNewName('')
      setDashboards((prev) => [d, ...prev])
      setActiveId(d.id)
    } catch (err) {
      setDashError(err instanceof Error ? err.message : 'Create failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleDeleteDashboard(id: number) {
    if (!confirm('Delete this dashboard and its pinned widgets?')) return
    setBusy(true)
    try {
      await api.deleteDashboard(id)
      const next = dashboards.filter((d) => d.id !== id)
      setDashboards(next)
      setActiveId(next[0]?.id ?? null)
      if (next.length === 0) await refreshDashboards()
    } catch (err) {
      setDashError(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleRemoveWidget(widgetId: string) {
    if (!active) return
    setBusy(true)
    try {
      const updated = await api.removeDashboardWidget(active.id, widgetId)
      setDashboards((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
    } catch (err) {
      setDashError(err instanceof Error ? err.message : 'Remove failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="findings-page">
      <header className="findings-header">
        <div>
          <h1 className="findings-title">Findings</h1>
          <p className="findings-sub">
            {loading && findings.length === 0
              ? 'Scanning your connected data…'
              : activeCount === 0
                ? 'No active signals in your connected data'
                : `${activeCount} active signal${activeCount === 1 ? '' : 's'} detected`}
            {generatedAt && ` · computed ${formatRelative(generatedAt)}`}
          </p>
        </div>
        <button type="button" className="findings-refresh" onClick={onRefresh} disabled={loading}>
          <span className={`material-symbols-outlined${loading ? ' is-spinning' : ''}`} aria-hidden="true">
            refresh
          </span>
          Recompute
        </button>
      </header>

      {error && <InlineMessage tone="error">{error}</InlineMessage>}

      <div className="findings-controls">
        <div className="findings-filters" role="group" aria-label="Severity filter">
          <span className="findings-filters-label">Severity</span>
          {(['all', 'critical', 'warning', 'opportunity', 'info'] as const).map((id) => (
            <button
              key={id}
              type="button"
              className={`findings-chip${filter === id ? ' is-active' : ''}`}
              onClick={() => setFilter(id)}
              disabled={id !== 'all' && !counts[id]}
            >
              {id !== 'all' && (
                <span className={`findings-dot findings-dot--${id}`} aria-hidden="true" />
              )}
              {id === 'all' ? 'All' : SEVERITY_LABEL[id]}
              <span className="findings-chip-count">{counts[id] ?? 0}</span>
            </button>
          ))}
        </div>

        <div className="findings-controls-right">
          {dismissedCount > 0 && (
            <button
              type="button"
              className="findings-restore"
              onClick={() => setDismissed(new Set())}
            >
              Restore {dismissedCount} dismissed
            </button>
          )}
          <label className="findings-sort">
            <span>Sort by</span>
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value as SortBy)}>
              <option value="severity">Severity</option>
              <option value="source">Data source</option>
            </select>
          </label>
        </div>
      </div>

      {loading && findings.length === 0 && (
        <div className="findings-list">
          {[0, 1, 2].map((i) => (
            <article key={i} className="finding-card">
              <Skeleton width={100} height={20} radius="var(--cl-radius-full)" />
              <Skeleton width="60%" height={20} />
              <Skeleton width="95%" height={14} />
              <Skeleton width="80%" height={14} />
            </article>
          ))}
        </div>
      )}

      {!loading && visible.length === 0 && (
        <EmptyState
          tone="positive"
          icon="task_alt"
          title={activeCount === 0 ? 'No active findings' : 'Nothing matches this filter'}
          body={
            activeCount === 0 ? (
              <p>
                Every check passed against your connected data — no anomalies, concentration
                risks, margin swings, or data-quality problems were detected.
              </p>
            ) : (
              <p>Try a different severity filter to see the remaining signals.</p>
            )
          }
          action={
            activeCount === 0 ? (
              <button
                type="button"
                className="findings-primary"
                onClick={() => onNavigate('sources')}
              >
                Connect more data
              </button>
            ) : (
              <button type="button" className="findings-primary" onClick={() => setFilter('all')}>
                Show all
              </button>
            )
          }
        />
      )}

      {visible.length > 0 && (
        <div className="findings-list">
          {visible.map((f) => (
            <article key={f.id} className={`finding-card finding-card--${f.severity}`}>
              <div className={`finding-accent finding-accent--${f.severity}`} aria-hidden="true" />
              <div className="finding-card-top">
                <div className="finding-meta">
                  <span className={`finding-badge finding-badge--${f.severity}`}>
                    {SEVERITY_LABEL[f.severity]}
                  </span>
                  <span className="finding-when">{f.context}</span>
                  {f.source_name && (
                    <>
                      <span className="finding-meta-dot" aria-hidden="true" />
                      <button
                        type="button"
                        className="finding-source"
                        onClick={() => onNavigate('sources')}
                      >
                        {f.source_name}
                      </button>
                    </>
                  )}
                  {f.metric && <span className="finding-metric">{f.metric}</span>}
                </div>
                <button
                  type="button"
                  className="finding-dismiss"
                  aria-label={`Dismiss: ${f.title}`}
                  title="Dismiss"
                  onClick={() => setDismissed((prev) => new Set(prev).add(f.id))}
                >
                  <span className="material-symbols-outlined" aria-hidden="true">close</span>
                </button>
              </div>
              <h2 className="finding-card-title">{f.title}</h2>
              <p className="finding-card-body">{f.body}</p>
              <div className="finding-action-box">
                <span className="material-symbols-outlined" aria-hidden="true">lightbulb</span>
                <div>
                  <h3 className="finding-action-label">Recommended action</h3>
                  <p className="finding-action-text">{f.action}</p>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* ----------------------------------------------- pinned reports */}
      <section className="findings-pinned" aria-label="Pinned reports">
        <div className="findings-pinned-head">
          <div>
            <h2 className="findings-pinned-title">Pinned reports</h2>
            <p className="findings-pinned-sub">Charts and tables you saved from Ask AI</p>
          </div>
          <form className="dash-create" onSubmit={handleCreate}>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="New dashboard name"
              aria-label="New dashboard name"
            />
            <button type="submit" disabled={busy || !newName.trim()}>
              Create
            </button>
          </form>
        </div>

        {dashError && <InlineMessage tone="error">{dashError}</InlineMessage>}
        {dashLoading && <Spinner label="Loading dashboards…" />}

        {!dashLoading && (
          <>
            {dashboards.length > 1 && (
              <div className="dash-tabs" role="tablist">
                {dashboards.map((d) => (
                  <button
                    key={d.id}
                    type="button"
                    role="tab"
                    aria-selected={active?.id === d.id}
                    className={`dash-tab${active?.id === d.id ? ' is-active' : ''}`}
                    onClick={() => setActiveId(d.id)}
                  >
                    {d.name}
                    <span className="dash-tab-count">{d.widgets.length}</span>
                  </button>
                ))}
              </div>
            )}

            {active && (
              <div className="dash-toolbar">
                <span className="dash-muted">
                  {active.name} · {active.widgets.length} widget
                  {active.widgets.length === 1 ? '' : 's'}
                </span>
                <button
                  type="button"
                  className="dash-danger"
                  disabled={busy}
                  onClick={() => void handleDeleteDashboard(active.id)}
                >
                  Delete dashboard
                </button>
              </div>
            )}

            {active && active.widgets.length === 0 && (
              <EmptyState
                icon="dashboard_customize"
                title="No pinned reports yet"
                body={
                  <p>
                    Run a question in Ask AI, then use <strong>Pin</strong> on the answer to save
                    its chart here.
                  </p>
                }
                action={
                  <button
                    type="button"
                    className="findings-primary"
                    onClick={() => onNavigate('chat')}
                  >
                    <span className="material-symbols-outlined" aria-hidden="true">auto_awesome</span>
                    Ask a question
                  </button>
                }
              />
            )}

            {active && active.widgets.length > 0 && (
              <div className="dash-grid">
                {active.widgets.map((w) => {
                  const q = queries[w.query_id]
                  return (
                    <article key={w.id} className="dash-widget">
                      <div className="dash-widget-head">
                        <h3 title={w.title}>{w.title}</h3>
                        <div className="dash-widget-actions">
                          {q && (
                            <button
                              type="button"
                              className="dash-link"
                              onClick={() => void api.downloadQueryCsv(q.id)}
                            >
                              CSV
                            </button>
                          )}
                          <button
                            type="button"
                            className="dash-link dash-link--danger"
                            disabled={busy}
                            onClick={() => void handleRemoveWidget(w.id)}
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                      {!q && <Skeleton height={180} radius="var(--cl-radius)" />}
                      {q?.result && (
                        <>
                          <ResultChart
                            result={q.result}
                            chart={q.chart}
                            chartType={w.chart_type}
                            height={200}
                          />
                          {(!q.chart || w.chart_type === 'table' || q.chart.type === 'table') && (
                            <div className="dash-table-wrap">
                              <table>
                                <thead>
                                  <tr>
                                    {q.result.columns.map((c) => (
                                      <th key={c} title={c}>{humanizeColumn(c)}</th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {q.result.rows.slice(0, 8).map((row, i) => (
                                    <tr key={i}>
                                      {q.result!.columns.map((c) => (
                                        <td key={c}>{formatCell(row[c])}</td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </>
                      )}
                    </article>
                  )
                })}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}
