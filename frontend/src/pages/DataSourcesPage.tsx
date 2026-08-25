import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  parseSchema,
  type DataSource,
  type MySQLConnectionConfig,
} from '../api/client'
import { EmptyState, InlineMessage } from '../components/Feedback'
import './DataSourcesPage.css'

const defaultMysql: MySQLConnectionConfig = {
  host: 'localhost',
  port: 3306,
  user: 'root',
  password: '',
  database: 'ai_bi',
}

type Props = {
  sources: DataSource[]
  onRefresh: () => Promise<void>
}

function formatRows(n: number | null | undefined) {
  if (n == null) return '—'
  return n.toLocaleString()
}

/** Which canonical fields this source actually contributes to analysis. */
function mappedSummary(source: DataSource): string | null {
  const mapping = source.field_mapping
  if (!mapping) return null
  const fields = [...new Set(Object.values(mapping))].filter(
    (f) => f !== 'Unmapped' && f !== 'Ignore',
  )
  if (fields.length === 0) return null
  const shown = fields.slice(0, 3).join(', ')
  return fields.length > 3 ? `${shown} +${fields.length - 3}` : shown
}

function sourceIcon(source: DataSource) {
  if (source.source_type === 'mysql') return 'public'
  const name = source.name.toLowerCase()
  if (name.includes('market') || name.includes('campaign')) return 'campaign'
  if (name.includes('inventor')) return 'public'
  return 'table_chart'
}

export function DataSourcesPage({ sources, onRefresh }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [okMsg, setOkMsg] = useState<string | null>(null)
  const [canonical, setCanonical] = useState<string[]>([])
  const [mappingSourceId, setMappingSourceId] = useState<number | null>(null)
  const [draftMapping, setDraftMapping] = useState<Record<string, string>>({})
  const [showMysql, setShowMysql] = useState(false)
  const [mysqlName, setMysqlName] = useState('')
  const [mysqlConfig, setMysqlConfig] = useState<MySQLConnectionConfig>(defaultMysql)
  const [dragOver, setDragOver] = useState(false)

  const mappingSource = sources.find((s) => s.id === mappingSourceId) ?? null

  const pendingSource = useMemo(
    () => sources.find((s) => s.mapping_status === 'pending') ?? null,
    [sources],
  )

  useEffect(() => {
    api.canonicalFields().then((r) => setCanonical(r.fields)).catch(() => {
      setCanonical(['Unmapped', 'Ignore', 'Date', 'Revenue', 'Store ID', 'Region'])
    })
  }, [])

  useEffect(() => {
    if (mappingSourceId == null && pendingSource) {
      setMappingSourceId(pendingSource.id)
    }
  }, [pendingSource, mappingSourceId])

  useEffect(() => {
    if (!mappingSource) {
      setDraftMapping({})
      return
    }
    const schema = parseSchema(mappingSource.schema_json)
    const cols = schema?.tables[0]?.columns.map((c) => c.name) ?? Object.keys(mappingSource.field_mapping ?? {})
    const base = { ...(mappingSource.field_mapping ?? {}) }
    for (const col of cols) {
      if (!(col in base)) base[col] = 'Unmapped'
    }
    setDraftMapping(base)
  }, [mappingSource])

  const openMapping = useCallback((id: number) => {
    setMappingSourceId(id)
    setOkMsg(null)
    setError(null)
  }, [])

  async function uploadFile(file: File) {
    setBusy(true)
    setError(null)
    setOkMsg(null)
    try {
      const name = file.name.replace(/\.[^.]+$/, '') || 'Dataset'
      const created = await api.uploadSource(name, file)
      await onRefresh()
      setMappingSourceId(created.id)
      setOkMsg(`Uploaded “${created.name}”. Confirm field mapping below.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (!file) return
    if (!/\.(csv|xlsx)$/i.test(file.name)) {
      setError('Only .csv or .xlsx files are supported')
      return
    }
    await uploadFile(file)
  }

  async function handleConfirmMapping() {
    if (!mappingSource) return
    setBusy(true)
    setError(null)
    try {
      await api.updateSourceMapping(mappingSource.id, draftMapping, true)
      await onRefresh()
      setOkMsg('Field mapping confirmed.')
      setMappingSourceId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Mapping failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleRecompute(id: number) {
    setBusy(true)
    setError(null)
    try {
      await api.recomputeSource(id)
      await onRefresh()
      setOkMsg('Schema recomputed.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Recompute failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(id: number) {
    if (!confirm('Delete this data source?')) return
    setBusy(true)
    try {
      await api.deleteSource(id)
      if (mappingSourceId === id) setMappingSourceId(null)
      await onRefresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleMysql(e: React.FormEvent) {
    e.preventDefault()
    if (!mysqlName.trim()) return
    setBusy(true)
    setError(null)
    try {
      const created = await api.createMysqlSource(mysqlName.trim(), mysqlConfig)
      setMysqlName('')
      setShowMysql(false)
      await onRefresh()
      setMappingSourceId(created.id)
      setOkMsg(`Connected “${created.name}”. Confirm field mapping.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'MySQL connection failed')
    } finally {
      setBusy(false)
    }
  }

  const mappingColumns = useMemo(() => {
    if (!mappingSource) return [] as string[]
    const schema = parseSchema(mappingSource.schema_json)
    const fromSchema = schema?.tables[0]?.columns.map((c) => c.name) ?? []
    if (fromSchema.length) return fromSchema
    return Object.keys(draftMapping)
  }, [mappingSource, draftMapping])

  return (
    <div className="ds-page">
      <header className="ds-header">
        <div>
          <h1>Data sources</h1>
          <p>
            {sources.length === 0
              ? 'Connect a dataset to start computing live metrics.'
              : `${sources.length} connected · ${
                  sources.filter((s) => s.mapping_status === 'confirmed').length
                } ready for analysis`}
          </p>
        </div>
        <button
          type="button"
          className="ds-primary"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          <span className="material-symbols-outlined" aria-hidden="true">
            upload
          </span>
          Upload dataset
        </button>
      </header>

      {error && (
        <InlineMessage tone="error" onDismiss={() => setError(null)}>
          {error}
        </InlineMessage>
      )}
      {okMsg && (
        <InlineMessage tone="success" onDismiss={() => setOkMsg(null)}>
          {okMsg}
        </InlineMessage>
      )}

      <div className="ds-grid">
        <div className="ds-main">
          <section
            className={`ds-upload${dragOver ? ' is-drag' : ''}`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => void handleDrop(e)}
            onClick={() => fileRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') fileRef.current?.click()
            }}
          >
            <div className="ds-upload-icon">
              <span className="material-symbols-outlined" aria-hidden="true">cloud_upload</span>
            </div>
            <h3>Upload a business dataset</h3>
            <p>Sales, employees, inventory, deliveries, or marketing data</p>
            <p className="ds-upload-caps">.csv or .xlsx supported</p>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) void uploadFile(f)
              }}
            />
          </section>

          <div className="ds-mysql-toggle">
            <button type="button" className="ds-link" onClick={() => setShowMysql((v) => !v)}>
              {showMysql ? 'Hide MySQL connection' : 'Or connect a MySQL database'}
            </button>
          </div>

          {showMysql && (
            <form className="ds-mysql" onSubmit={(e) => void handleMysql(e)}>
              <label>
                Name
                <input value={mysqlName} onChange={(e) => setMysqlName(e.target.value)} placeholder="Production DB" />
              </label>
              <div className="ds-mysql-row">
                <label>
                  Host
                  <input value={mysqlConfig.host} onChange={(e) => setMysqlConfig({ ...mysqlConfig, host: e.target.value })} />
                </label>
                <label>
                  Port
                  <input
                    type="number"
                    value={mysqlConfig.port}
                    onChange={(e) => setMysqlConfig({ ...mysqlConfig, port: Number(e.target.value) })}
                  />
                </label>
              </div>
              <div className="ds-mysql-row">
                <label>
                  User
                  <input value={mysqlConfig.user} onChange={(e) => setMysqlConfig({ ...mysqlConfig, user: e.target.value })} />
                </label>
                <label>
                  Password
                  <input
                    type="password"
                    value={mysqlConfig.password}
                    onChange={(e) => setMysqlConfig({ ...mysqlConfig, password: e.target.value })}
                  />
                </label>
              </div>
              <label>
                Database
                <input
                  value={mysqlConfig.database}
                  onChange={(e) => setMysqlConfig({ ...mysqlConfig, database: e.target.value })}
                />
              </label>
              <button type="submit" disabled={busy || !mysqlName.trim()}>
                Connect MySQL
              </button>
            </form>
          )}

          {mappingSource && (
            <section className="ds-mapping">
              <div className="ds-mapping-accent" />
              <div className="ds-mapping-head">
                <h2>Confirm Field Mapping</h2>
                <span className={`ds-badge${mappingSource.mapping_status === 'confirmed' ? ' is-ok' : ' is-action'}`}>
                  {mappingSource.mapping_status === 'confirmed' ? 'Mapped' : 'Action Required'}
                </span>
              </div>
              <p className="ds-mapping-sub">
                Mapping columns for <strong>{mappingSource.name}</strong>
              </p>
              <div className="ds-mapping-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Source Column (CSV)</th>
                      <th>Map to Canonical Field</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mappingColumns.map((col) => {
                      const value = draftMapping[col] ?? 'Unmapped'
                      const highlighted = value === 'Revenue' || value === 'Date'
                      return (
                        <tr key={col} className={highlighted ? 'is-focus' : undefined}>
                          <td>{col}</td>
                          <td>
                            <div className="ds-select-wrap">
                              <select
                                value={value}
                                onChange={(e) =>
                                  setDraftMapping((prev) => ({ ...prev, [col]: e.target.value }))
                                }
                              >
                                {(canonical.length ? canonical : [value]).map((opt) => (
                                  <option key={opt} value={opt}>
                                    {opt}
                                  </option>
                                ))}
                              </select>
                              <span className="material-symbols-outlined" aria-hidden="true">expand_more</span>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <div className="ds-mapping-actions">
                <button type="button" className="ds-link" onClick={() => setMappingSourceId(null)}>
                  Close
                </button>
                <button type="button" className="ds-primary" disabled={busy} onClick={() => void handleConfirmMapping()}>
                  Confirm Mapping
                </button>
              </div>
            </section>
          )}
        </div>

        <aside className="ds-side">
          <h2>Your datasets</h2>
          {sources.length === 0 && (
            <EmptyState
              icon="folder_open"
              title="Nothing connected"
              body={<p>Upload a CSV or Excel file, or connect a MySQL database.</p>}
            />
          )}
          {sources.map((s) => {
            const status = s.mapping_status === 'confirmed' ? 'processed' : 'pending'
            return (
              <article key={s.id} className="ds-card">
                <div className="ds-card-top">
                  <div className="ds-card-title">
                    <span className="material-symbols-outlined" aria-hidden="true">{sourceIcon(s)}</span>
                    <h3 title={s.name}>{s.name}</h3>
                  </div>
                  <span className={`ds-status ds-status--${status}`}>
                    {status === 'processed' ? 'Processed' : 'Action needed'}
                  </span>
                </div>
                <p className="ds-rows">
                  {formatRows(s.row_count)} rows · {s.source_type}
                </p>
                {mappedSummary(s) && <p className="ds-mapped">{mappedSummary(s)}</p>}
                <div className="ds-card-actions">
                  <button type="button" className="ds-link" disabled={busy} onClick={() => openMapping(s.id)}>
                    Re-map
                  </button>
                  <span className="ds-dot">•</span>
                  <button type="button" className="ds-link muted" disabled={busy} onClick={() => void handleRecompute(s.id)}>
                    Recompute
                  </button>
                  <span className="ds-dot">•</span>
                  <button type="button" className="ds-link danger" disabled={busy} onClick={() => void handleDelete(s.id)}>
                    Delete
                  </button>
                </div>
              </article>
            )
          })}
        </aside>
      </div>
    </div>
  )
}
