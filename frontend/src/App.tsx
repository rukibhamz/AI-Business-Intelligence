import { useCallback, useEffect, useState } from 'react'
import {
  api,
  clearSession,
  getStoredUser,
  getToken,
  parseSchema,
  type DataSource,
  type HealthResponse,
  type MySQLConnectionConfig,
  type PreviewResponse,
  type User,
} from './api/client'
import { LoginPage } from './pages/LoginPage'
import './App.css'

const defaultMysql: MySQLConnectionConfig = {
  host: 'localhost',
  port: 3306,
  user: 'root',
  password: '',
  database: 'ai_bi',
}

function App() {
  const [user, setUser] = useState<User | null>(getStoredUser())
  const [authChecking, setAuthChecking] = useState(!!getToken())
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [sources, setSources] = useState<DataSource[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [uploadName, setUploadName] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [mysqlName, setMysqlName] = useState('')
  const [mysqlConfig, setMysqlConfig] = useState<MySQLConnectionConfig>(defaultMysql)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const token = getToken()
    if (!token) {
      setAuthChecking(false)
      return
    }
    api.me()
      .then((u) => setUser(u))
      .catch(() => {
        clearSession()
        setUser(null)
      })
      .finally(() => setAuthChecking(false))
  }, [])

  const load = useCallback(async () => {
    setError(null)
    const [h, s] = await Promise.all([api.health(), api.listSources()])
    setHealth(h)
    setSources(s)
  }, [])

  useEffect(() => {
    if (!user) return
    setLoading(true)
    load()
      .catch((e: Error) => {
        if (e.message === 'UNAUTHORIZED') {
          setUser(null)
          return
        }
        setError(e.message)
      })
      .finally(() => setLoading(false))
  }, [user, load])

  const selected = sources.find((s) => s.id === selectedId) ?? null
  const schema = selected ? parseSchema(selected.schema_json) : null

  async function handlePreview(id: number, table?: string) {
    setSelectedId(id)
    setPreviewLoading(true)
    setError(null)
    try {
      const data = await api.previewSource(id, table)
      setPreview(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Preview failed')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault()
    if (!uploadFile || !uploadName.trim()) return
    setBusy(true)
    setError(null)
    try {
      await api.uploadSource(uploadName.trim(), uploadFile)
      setUploadName('')
      setUploadFile(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
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
      await api.createMysqlSource(mysqlName.trim(), mysqlConfig)
      setMysqlName('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'MySQL connection failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(id: number) {
    if (!confirm('Delete this data source?')) return
    setBusy(true)
    setError(null)
    try {
      await api.deleteSource(id)
      if (selectedId === id) {
        setSelectedId(null)
        setPreview(null)
      }
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setBusy(false)
    }
  }

  function handleLogout() {
    clearSession()
    setUser(null)
    setSources([])
    setPreview(null)
  }

  if (authChecking) {
    return (
      <div className="cl-auth-loading">
        <p className="text-body-md">Checking session…</p>
      </div>
    )
  }

  if (!user) {
    return <LoginPage onSuccess={setUser} />
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <p className="eyebrow">Cognitive Logic</p>
          <h1>AI Business Intelligence</h1>
          <p className="subtitle">Connect your business data sources and preview records.</p>
        </div>
        <div className="header-right">
          <div className="status-pill" data-ok={health?.status === 'ok'}>
            {loading ? 'Connecting…' : health?.status === 'ok' ? 'API Online' : 'API Offline'}
          </div>
          <div className="user-chip">
            <span>{user.full_name || user.email}</span>
            <button type="button" className="ghost" onClick={handleLogout}>Log out</button>
          </div>
        </div>
      </header>

      {error && (
        <section className="card error">
          <h2>Error</h2>
          <p>{error}</p>
        </section>
      )}

      <main className="layout">
        <section className="card">
          <h2>Data Sources</h2>
          {sources.length === 0 ? (
            <p className="muted">No sources yet. Upload a CSV or connect MySQL.</p>
          ) : (
            <ul className="source-list">
              {sources.map((s) => (
                <li key={s.id} className={selectedId === s.id ? 'selected' : ''}>
                  <div>
                    <strong>{s.name}</strong>
                    <span className="badge">{s.source_type}</span>
                  </div>
                  <div className="actions">
                    <button type="button" onClick={() => handlePreview(s.id)} disabled={busy}>
                      Preview
                    </button>
                    <button type="button" className="danger" onClick={() => handleDelete(s.id)} disabled={busy}>
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card">
          <h2>Add Data Source</h2>
          <form className="form" onSubmit={handleUpload}>
            <h3>Upload CSV / Excel</h3>
            <label>
              Name
              <input value={uploadName} onChange={(e) => setUploadName(e.target.value)} placeholder="Sales data" />
            </label>
            <label>
              File
              <input type="file" accept=".csv,.xlsx" onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)} />
            </label>
            <button type="submit" disabled={busy || !uploadFile || !uploadName.trim()}>Upload</button>
          </form>

          <form className="form" onSubmit={handleMysql}>
            <h3>Connect MySQL</h3>
            <label>
              Name
              <input value={mysqlName} onChange={(e) => setMysqlName(e.target.value)} placeholder="Production DB" />
            </label>
            <div className="row">
              <label>
                Host
                <input value={mysqlConfig.host} onChange={(e) => setMysqlConfig({ ...mysqlConfig, host: e.target.value })} />
              </label>
              <label>
                Port
                <input type="number" value={mysqlConfig.port} onChange={(e) => setMysqlConfig({ ...mysqlConfig, port: Number(e.target.value) })} />
              </label>
            </div>
            <div className="row">
              <label>
                User
                <input value={mysqlConfig.user} onChange={(e) => setMysqlConfig({ ...mysqlConfig, user: e.target.value })} />
              </label>
              <label>
                Password
                <input type="password" value={mysqlConfig.password} onChange={(e) => setMysqlConfig({ ...mysqlConfig, password: e.target.value })} />
              </label>
            </div>
            <label>
              Database
              <input value={mysqlConfig.database} onChange={(e) => setMysqlConfig({ ...mysqlConfig, database: e.target.value })} />
            </label>
            <button type="submit" disabled={busy || !mysqlName.trim()}>Connect</button>
          </form>
        </section>

        {(schema || preview) && (
          <section className="card wide">
            <h2>{selected?.name ?? 'Preview'}</h2>

            {schema && schema.tables.length > 0 && (
              <div className="schema-block">
                <h3>Schema</h3>
                {schema.tables.map((t) => (
                  <div key={t.name} className="schema-table">
                    <div className="schema-table-head">
                      <strong>{t.name}</strong>
                      {selected?.source_type === 'mysql' && (
                        <button type="button" onClick={() => selectedId && handlePreview(selectedId, t.name)}>
                          Preview table
                        </button>
                      )}
                    </div>
                    <div className="chips">
                      {t.columns.map((c) => (
                        <span key={c.name} className="chip">{c.name} <em>{c.type}</em></span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {previewLoading && <p className="muted">Loading preview…</p>}

            {preview && preview.rows.length > 0 && (
              <div className="table-wrap">
                <p className="hint">
                  Showing {preview.rows.length} of {preview.total} rows
                  {preview.table ? ` from ${preview.table}` : ''}
                </p>
                <table>
                  <thead>
                    <tr>
                      {preview.columns.map((col) => (
                        <th key={col}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((row, i) => (
                      <tr key={i}>
                        {preview.columns.map((col) => (
                          <td key={col}>{String(row[col] ?? '')}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {preview && preview.rows.length === 0 && (
              <p className="muted">No rows in this source.</p>
            )}
          </section>
        )}
      </main>
    </div>
  )
}

export default App
