import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  api,
  type Finding,
  type KpiCard as KpiCardData,
  type OverviewResponse,
} from '../api/client'
import { EmptyState, InlineMessage, Skeleton } from '../components/Feedback'
import { LiveChart } from '../components/LiveChart'
import { formatDelta, formatExact, formatValue, formatRelative } from '../lib/format'
import type { AppView } from '../layouts/navigation'
import './OverviewPage.css'

type Props = {
  onNavigate: (view: AppView) => void
  findings: Finding[]
  findingsLoading: boolean
  refreshToken: number
}

const SEVERITY_ICON: Record<string, string> = {
  critical: 'error',
  warning: 'warning',
  opportunity: 'trending_up',
  info: 'info',
}

function KpiTile({ kpi }: { kpi: KpiCardData }) {
  const isText = kpi.format === 'text'
  return (
    <article className="kpi-card">
      <h3 className="text-label-caps kpi-label">{kpi.label}</h3>
      <div className="kpi-body">
        <div
          className={isText ? 'kpi-value kpi-value--text' : 'kpi-value'}
          title={formatExact(kpi.value, kpi.format)}
        >
          {formatValue(kpi.value, kpi.format)}
        </div>
        {kpi.delta_pct != null && kpi.direction && (
          <span className={`kpi-delta kpi-delta--${kpi.tone ?? 'neutral'}`}>
            <span className="material-symbols-outlined" aria-hidden="true">
              {kpi.direction === 'up' ? 'trending_up' : 'trending_down'}
            </span>
            {formatDelta(kpi.delta_pct)}
          </span>
        )}
      </div>
      {kpi.caption && <p className="kpi-caption">{kpi.caption}</p>}
    </article>
  )
}

function KpiSkeletonRow() {
  return (
    <>
      {[0, 1, 2, 3, 4].map((i) => (
        <article key={i} className="kpi-card">
          <Skeleton width={90} height={11} />
          <div className="kpi-body">
            <Skeleton width={120} height={30} />
          </div>
          <Skeleton width={70} height={11} />
        </article>
      ))}
    </>
  )
}

export function OverviewPage({ onNavigate, findings, findingsLoading, refreshToken }: Props) {
  const [data, setData] = useState<OverviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sourceId, setSourceId] = useState<number | null>(null)

  const load = useCallback(
    async (id: number | null) => {
      setError(null)
      try {
        const result = await api.getOverview(id ?? undefined)
        setData(result)
        if (result.source && id == null) setSourceId(result.source.id)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not load overview')
      }
    },
    [],
  )

  useEffect(() => {
    setLoading(true)
    void load(sourceId).finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceId, refreshToken])

  const topFindings = useMemo(() => findings.slice(0, 4), [findings])
  const source = data?.source ?? null
  const sources = data?.available_sources ?? []
  const charts = data?.charts ?? []
  const kpis = data?.kpis ?? []

  const period = data?.period
  const periodLabel =
    period?.start && period?.end
      ? `${new Date(period.start).toLocaleDateString(undefined, {
          month: 'short',
          day: 'numeric',
          year: 'numeric',
        })} – ${new Date(period.end).toLocaleDateString(undefined, {
          month: 'short',
          day: 'numeric',
          year: 'numeric',
        })}`
      : null

  if (!loading && sources.length === 0) {
    return (
      <div className="overview">
        <EmptyState
          icon="database"
          title="No data connected yet"
          body={
            <p>
              This dashboard only ever shows figures computed from your own data. Upload a CSV
              or Excel file, or connect a MySQL database, and the KPIs and charts will populate
              from it.
            </p>
          }
          action={
            <button type="button" className="ov-primary" onClick={() => onNavigate('sources')}>
              <span className="material-symbols-outlined" aria-hidden="true">add</span>
              Connect a data source
            </button>
          }
        />
      </div>
    )
  }

  return (
    <div className="overview">
      <div className="overview-header">
        <div className="overview-header-copy">
          <h2 className="overview-title">
            {source ? source.name : 'Overview'}
            {source && <span className="overview-type-chip">{source.source_type}</span>}
          </h2>
          <p className="overview-sub">
            {source ? (
              <>
                {source.rows_analyzed.toLocaleString()} rows analysed
                {source.truncated && ` of ${source.total_rows.toLocaleString()}`}
                {periodLabel && ` · ${periodLabel}`}
                {data?.generated_at && ` · updated ${formatRelative(data.generated_at)}`}
              </>
            ) : (
              'Select a data source to compute live metrics'
            )}
          </p>
        </div>

        {sources.length > 0 && (
          <label className="overview-source-picker">
            <span className="cl-visually-hidden">Data source</span>
            <span className="material-symbols-outlined" aria-hidden="true">database</span>
            <select
              value={sourceId ?? source?.id ?? ''}
              onChange={(e) => setSourceId(Number(e.target.value))}
            >
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                  {s.analyzable ? '' : ' (needs mapping)'}
                </option>
              ))}
            </select>
            <span className="material-symbols-outlined" aria-hidden="true">expand_more</span>
          </label>
        )}
      </div>

      {error && <InlineMessage tone="error">{error}</InlineMessage>}
      {data?.error && <InlineMessage tone="error">{data.error}</InlineMessage>}

      {data?.notices?.map((notice) => (
        <InlineMessage key={notice} tone="info">
          {notice}{' '}
          <button type="button" className="ov-inline-link" onClick={() => onNavigate('sources')}>
            Open Data Sources
          </button>
        </InlineMessage>
      ))}

      <section className="overview-kpis" aria-label="Key metrics">
        {loading && kpis.length === 0 ? (
          <KpiSkeletonRow />
        ) : kpis.length > 0 ? (
          kpis.map((kpi) => <KpiTile key={kpi.id} kpi={kpi} />)
        ) : (
          <div className="overview-kpis-empty">
            <EmptyState
              icon="calculate"
              title="No metrics could be computed"
              body={
                <p>
                  None of this source&apos;s columns are mapped to a measurable field yet. Map at
                  least one column to Revenue, Cost, Profit, or Quantity.
                </p>
              }
              action={
                <button type="button" className="ov-primary" onClick={() => onNavigate('sources')}>
                  Map fields
                </button>
              }
            />
          </div>
        )}
      </section>

      <div className="overview-grid">
        <section className="overview-findings" aria-label="Findings">
          <div className="overview-section-head">
            <span className="material-symbols-outlined filled" aria-hidden="true">auto_awesome</span>
            <h2 className="text-headline-sm">Findings</h2>
            {findings.length > 0 && (
              <button
                type="button"
                className="ov-section-link"
                onClick={() => onNavigate('findings')}
              >
                View all ({findings.length})
              </button>
            )}
          </div>

          {findingsLoading && findings.length === 0 && (
            <div className="findings-list">
              {[0, 1, 2].map((i) => (
                <article key={i} className="finding">
                  <Skeleton width={80} height={18} radius="var(--cl-radius-full)" />
                  <Skeleton width="90%" height={15} />
                  <Skeleton width="70%" height={13} />
                </article>
              ))}
            </div>
          )}

          {!findingsLoading && findings.length === 0 && (
            <EmptyState
              tone="positive"
              icon="task_alt"
              title="Nothing needs attention"
              body={<p>No anomalies, concentration risks, or data-quality issues were detected.</p>}
            />
          )}

          {topFindings.length > 0 && (
            <div className="findings-list">
              {topFindings.map((f) => (
                <article key={f.id} className={`finding finding--${f.severity}`}>
                  <div className="finding-top">
                    <span className="finding-badge">{f.severity}</span>
                    <span className="material-symbols-outlined finding-icon" aria-hidden="true">
                      {SEVERITY_ICON[f.severity] ?? 'info'}
                    </span>
                  </div>
                  <h4>{f.title}</h4>
                  <p>{f.body}</p>
                  <div className="finding-action">
                    <span className="material-symbols-outlined" aria-hidden="true">lightbulb</span>
                    <span>
                      <strong>Action:</strong> {f.action}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="overview-charts" aria-label="Charts">
          <div className="overview-section-head">
            <span className="material-symbols-outlined" aria-hidden="true">bar_chart</span>
            <h2 className="text-headline-sm">Performance</h2>
          </div>

          {loading && charts.length === 0 && (
            <div className="charts-grid">
              {[0, 1].map((i) => (
                <article key={i} className="chart-card">
                  <Skeleton width={160} height={14} />
                  <Skeleton height={220} radius="var(--cl-radius)" />
                </article>
              ))}
            </div>
          )}

          {!loading && charts.length === 0 && (
            <EmptyState
              icon="insert_chart"
              title="No charts available for this source"
              body={
                <p>
                  Charts need a date column plus at least one measure, or a dimension such as
                  Region or Category. Adjust the field mapping to unlock them.
                </p>
              }
              action={
                <button type="button" className="ov-primary" onClick={() => onNavigate('sources')}>
                  Adjust mapping
                </button>
              }
            />
          )}

          {charts.length > 0 && (
            <div className="charts-grid">
              {charts.map((chart, i) => (
                <article
                  key={chart.id}
                  className={`chart-card${i === 0 && chart.type === 'line' ? ' chart-card--wide' : ''}`}
                >
                  <div className="chart-card-head">
                    <h3>{chart.title}</h3>
                    <span className="chart-card-count">{chart.data.length} points</span>
                  </div>
                  <LiveChart chart={chart} height={i === 0 && chart.type === 'line' ? 280 : 240} />
                </article>
              ))}
            </div>
          )}
        </section>
      </div>

      {data?.coverage && (
        <section className="overview-coverage" aria-label="Field coverage">
          <div className="overview-section-head">
            <span className="material-symbols-outlined" aria-hidden="true">rule</span>
            <h2 className="text-headline-sm">Field coverage</h2>
            <button
              type="button"
              className="ov-section-link"
              onClick={() => onNavigate('sources')}
            >
              Edit mapping
            </button>
          </div>
          <div className="coverage-chips">
            {data.coverage.mapped.map((f) => (
              <span key={f} className="coverage-chip coverage-chip--on">
                <span className="material-symbols-outlined" aria-hidden="true">check</span>
                {f}
              </span>
            ))}
            {data.coverage.missing.map((f) => (
              <span key={f} className="coverage-chip coverage-chip--off" title="Not mapped">
                {f}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
