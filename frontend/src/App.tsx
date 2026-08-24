import { useEffect, useState } from 'react'
import { api, type DataSource, type HealthResponse } from './api/client'
import './App.css'

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [sources, setSources] = useState<DataSource[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([api.health(), api.listSources()])
      .then(([h, s]) => {
        setHealth(h)
        setSources(s)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="app">
      <header className="header">
        <div>
          <p className="eyebrow">Phase 1 — Foundation</p>
          <h1>AI Business Intelligence</h1>
          <p className="subtitle">Connect data. Ask questions. Get insights.</p>
        </div>
        <div className="status-pill" data-ok={health?.status === 'ok'}>
          {loading ? 'Connecting…' : health?.status === 'ok' ? 'API Online' : 'API Offline'}
        </div>
      </header>

      {error && (
        <section className="card error">
          <h2>Connection Error</h2>
          <p>{error}</p>
          <p className="hint">Start the backend: <code>uvicorn app.main:app --reload</code></p>
        </section>
      )}

      <main className="grid">
        <section className="card">
          <h2>System Status</h2>
          {health ? (
            <dl className="meta">
              <div><dt>Status</dt><dd>{health.status}</dd></div>
              <div><dt>Version</dt><dd>{health.version}</dd></div>
              <div><dt>Environment</dt><dd>{health.environment}</dd></div>
            </dl>
          ) : (
            <p className="muted">Waiting for API…</p>
          )}
        </section>

        <section className="card">
          <h2>Data Sources</h2>
          {sources.length === 0 ? (
            <p className="muted">No data sources yet. Phase 2 adds connectors.</p>
          ) : (
            <ul className="source-list">
              {sources.map((s) => (
                <li key={s.id}>
                  <strong>{s.name}</strong>
                  <span>{s.source_type}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card wide">
          <h2>Build Roadmap</h2>
          <ol className="roadmap">
            <li className="active"><strong>Phase 1</strong> — Foundation (current)</li>
            <li><strong>Phase 2</strong> — Data layer & file connectors</li>
            <li><strong>Phase 3</strong> — Auth & multi-tenancy</li>
            <li><strong>Phase 4</strong> — AI natural-language queries</li>
            <li><strong>Phase 5</strong> — Dashboards & charts</li>
            <li><strong>Phase 6</strong> — Production hardening</li>
          </ol>
          <p className="hint">See <code>docs/BUILD_AND_HANDOFF.md</code> for agent handoff details.</p>
        </section>
      </main>
    </div>
  )
}

export default App
