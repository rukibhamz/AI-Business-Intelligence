import { useCallback, useEffect, useState } from 'react'
import {
  api,
  clearSession,
  getStoredUser,
  getToken,
  type AppSettings,
  type DataSource,
  type Finding,
  type HealthResponse,
  type QueryRecord,
  type User,
} from './api/client'
import { CommandPalette, type PaletteAction } from './components/CommandPalette'
import { InlineMessage } from './components/Feedback'
import { AppShell } from './layouts/AppShell'
import type { AppView } from './layouts/navigation'
import { AskAiPage } from './pages/AskAiPage'
import { DataSourcesPage } from './pages/DataSourcesPage'
import { FindingsPage } from './pages/FindingsPage'
import { HistoryPage } from './pages/HistoryPage'
import { LoginPage } from './pages/LoginPage'
import { OverviewPage } from './pages/OverviewPage'
import { SettingsPage } from './pages/SettingsPage'
import './App.css'

function App() {
  const [user, setUser] = useState<User | null>(getStoredUser())
  const [authChecking, setAuthChecking] = useState(!!getToken())
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [sources, setSources] = useState<DataSource[]>([])
  const [queries, setQueries] = useState<QueryRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState<AppView>('overview')
  const [branding, setBranding] = useState<AppSettings | null>(null)

  // Live findings power the sidebar badge, the alerts popover, the dashboard
  // panel, and the Findings page — so they are fetched once here.
  const [findings, setFindings] = useState<Finding[]>([])
  const [findingsLoading, setFindingsLoading] = useState(false)
  const [findingsError, setFindingsError] = useState<string | null>(null)
  const [findingsAt, setFindingsAt] = useState<string | null>(null)

  const [paletteOpen, setPaletteOpen] = useState(false)
  const [refreshToken, setRefreshToken] = useState(0)
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null)
  const [focusQueryId, setFocusQueryId] = useState<number | null>(null)

  useEffect(() => {
    const token = getToken()
    if (!token) {
      setAuthChecking(false)
      return
    }
    api
      .me()
      .then(setUser)
      .catch(() => {
        clearSession()
        setUser(null)
      })
      .finally(() => setAuthChecking(false))
  }, [])

  const load = useCallback(async () => {
    setError(null)
    const [h, s, settings, q] = await Promise.all([
      api.health(),
      api.listSources(),
      api.getSettings().catch(() => null),
      api.listQueries().catch(() => [] as QueryRecord[]),
    ])
    setHealth(h)
    setSources(s)
    setQueries(q)
    if (settings) setBranding(settings)
  }, [])

  const loadFindings = useCallback(async () => {
    setFindingsLoading(true)
    setFindingsError(null)
    try {
      const result = await api.getFindings()
      setFindings(result.findings)
      setFindingsAt(result.generated_at)
      if (result.errors.length > 0) setFindingsError(result.errors.join(' · '))
    } catch (e) {
      if (e instanceof Error && e.message === 'UNAUTHORIZED') {
        setUser(null)
        return
      }
      setFindingsError(e instanceof Error ? e.message : 'Could not compute findings')
    } finally {
      setFindingsLoading(false)
    }
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
  }, [user, load, refreshToken])

  useEffect(() => {
    if (!user) return
    void loadFindings()
  }, [user, loadFindings, refreshToken])

  // Ctrl/Cmd+K opens search from anywhere.
  useEffect(() => {
    if (!user) return
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [user])

  const refreshAll = useCallback(() => setRefreshToken((n) => n + 1), [])

  function handleLogout() {
    clearSession()
    setUser(null)
    setSources([])
    setQueries([])
    setFindings([])
  }

  function handlePaletteAction(action: PaletteAction) {
    if (action.kind === 'navigate') {
      setView(action.view)
    } else if (action.kind === 'source') {
      setView('sources')
    } else if (action.kind === 'query') {
      setFocusQueryId(action.id)
      setView('history')
    } else if (action.kind === 'ask') {
      setPendingQuestion(action.text)
      setView('chat')
    }
  }

  if (authChecking) {
    return (
      <div className="cl-auth-loading">
        <span className="cl-auth-spinner" aria-hidden="true" />
        <p className="text-body-md">Checking your session…</p>
      </div>
    )
  }

  if (!user) {
    return <LoginPage onSuccess={setUser} branding={branding} />
  }

  return (
    <>
      <AppShell
        user={user}
        view={view}
        onNavigate={setView}
        onLogout={handleLogout}
        onOpenSearch={() => setPaletteOpen(true)}
        onRefresh={refreshAll}
        refreshing={loading || findingsLoading}
        apiOnline={!loading && health?.status === 'ok'}
        branding={branding}
        findings={findings}
        findingsUpdatedAt={findingsAt}
      >
        {error && (
          <div className="app-inline-error">
            <InlineMessage tone="error" onDismiss={() => setError(null)}>
              {error}
            </InlineMessage>
          </div>
        )}

        {view === 'overview' && (
          <OverviewPage
            onNavigate={setView}
            findings={findings}
            findingsLoading={findingsLoading}
            refreshToken={refreshToken}
          />
        )}

        {view === 'findings' && (
          <FindingsPage
            findings={findings}
            loading={findingsLoading}
            error={findingsError}
            generatedAt={findingsAt}
            onRefresh={() => void loadFindings()}
            onNavigate={setView}
          />
        )}

        {view === 'sources' && (
          <DataSourcesPage
            sources={sources}
            onRefresh={async () => {
              await load()
              void loadFindings()
            }}
          />
        )}

        {view === 'chat' && (
          <AskAiPage
            sources={sources}
            branding={branding}
            pendingQuestion={pendingQuestion}
            onPendingConsumed={() => setPendingQuestion(null)}
            onAnswered={() => {
              void api.listQueries().then(setQueries).catch(() => undefined)
            }}
          />
        )}

        {view === 'history' && (
          <HistoryPage
            branding={branding}
            user={user}
            focusQueryId={focusQueryId}
            onFocusConsumed={() => setFocusQueryId(null)}
            onNewAnalysis={() => setView('chat')}
          />
        )}

        {view === 'settings' && <SettingsPage onSaved={setBranding} />}
      </AppShell>

      {paletteOpen && (
        <CommandPalette
          open
          onClose={() => setPaletteOpen(false)}
          sources={sources}
          queries={queries}
          onAction={handlePaletteAction}
        />
      )}
    </>
  )
}

export default App
