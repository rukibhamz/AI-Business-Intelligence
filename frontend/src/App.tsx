import { useCallback, useEffect, useState } from 'react'
import {
  api,
  clearSession,
  getStoredUser,
  type AppSettings,
  type AuthConfig,
  type DataSource,
  type Finding,
  type HealthResponse,
  type QueryRecord,
  type User,
} from './api/client'
import { CommandPalette, type PaletteAction } from './components/CommandPalette'
import { InlineMessage } from './components/Feedback'
import { AppShell } from './layouts/AppShell'
import { setCurrency } from './lib/format'
import { useRouter } from './lib/router'
import { startNewSession } from './lib/session'
import { AskAiPage } from './pages/AskAiPage'
import { DataSourcesPage } from './pages/DataSourcesPage'
import { FindingsPage } from './pages/FindingsPage'
import { HistoryPage } from './pages/HistoryPage'
import { LoginPage } from './pages/LoginPage'
import { currentToken, loadAuthConfig, onAuthChange, signOut, supabase } from './lib/auth'
import { OverviewPage } from './pages/OverviewPage'
import { SettingsPage } from './pages/SettingsPage'
import './App.css'

function App() {
  const [user, setUser] = useState<User | null>(getStoredUser())
  const [authChecking, setAuthChecking] = useState(true)
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null)
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [sources, setSources] = useState<DataSource[]>([])
  const [queries, setQueries] = useState<QueryRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const { location, navigate, setSearch } = useRouter()
  const view = location.view
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

  /** Conversation addressed by the URL, e.g. /ask?c=s_abc123 */
  const conversationId = new URLSearchParams(location.search).get('c')

  /**
   * Restore whatever session exists.
   *
   * Which provider is in charge is the API's decision, so that comes first;
   * then Supabase is given the chance to rehydrate its own session from
   * storage before we ask who the caller is.
   */
  useEffect(() => {
    let cancelled = false

    async function restore() {
      try {
        const config = await loadAuthConfig(api.authConfig)
        if (cancelled) return
        setAuthConfig(config)
        if (config.provider === 'supabase') supabase()
      } catch {
        // The API is unreachable; the login screen will say so on submit.
      }

      const token = await currentToken()
      if (!token) {
        if (!cancelled) setAuthChecking(false)
        return
      }
      try {
        const me = await api.me()
        if (!cancelled) setUser(me)
      } catch {
        if (!cancelled) {
          clearSession()
          setUser(null)
        }
      } finally {
        if (!cancelled) setAuthChecking(false)
      }
    }

    void restore()
    return () => {
      cancelled = true
    }
  }, [])

  // A session ending in another tab should end here too.
  useEffect(() => {
    return onAuthChange((signedIn) => {
      if (!signedIn) {
        clearSession()
        setUser(null)
      }
    })
  }, [authConfig])

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
    if (settings) {
      setBranding(settings)
      // Every money figure renders in the admin's chosen currency.
      setCurrency(settings.currency)
    }
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
    void signOut()
    setUser(null)
    setSources([])
    setQueries([])
    setFindings([])
  }

  function handlePaletteAction(action: PaletteAction) {
    if (action.kind === 'navigate') {
      navigate(action.view)
    } else if (action.kind === 'source') {
      navigate('sources')
    } else if (action.kind === 'query') {
      navigate('history')
    } else if (action.kind === 'ask') {
      setPendingQuestion(action.text)
      navigate('chat')
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
    return (
      <LoginPage
        branding={branding}
        auth={authConfig}
        onSuccess={(loggedIn) => {
          setUser(loggedIn)
          // Sign-in always lands on a fresh analysis, whatever URL was open.
          navigate('chat', { replace: true })
        }}
      />
    )
  }

  return (
    <>
      <AppShell
        user={user}
        view={view}
        onNavigate={navigate}
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
            onNavigate={navigate}
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
            onNavigate={navigate}
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
            conversationId={conversationId}
            onConversationChange={(id) => setSearch(id ? `?c=${encodeURIComponent(id)}` : '')}
            onAnswered={() => {
              void api.listQueries().then(setQueries).catch(() => undefined)
            }}
          />
        )}

        {view === 'history' && (
          <HistoryPage
            onOpenConversation={(id) =>
              navigate('chat', { search: `?c=${encodeURIComponent(id)}` })
            }
            onNewChat={() => {
              startNewSession()
              navigate('chat')
            }}
          />
        )}

        {view === 'settings' &&
          (user.is_admin ? (
            <SettingsPage
              onSaved={(saved) => {
                setBranding(saved)
                setCurrency(saved.currency)
                refreshAll()
              }}
            />
          ) : (
            // Hiding the nav item is not a gate — the URL is still typeable.
            // The API refuses the writes; this explains why rather than
            // rendering a settings page that cannot save.
            <div className="cl-restricted" role="status">
              <span className="material-symbols-outlined" aria-hidden="true">
                lock
              </span>
              <div>
                <h2>Settings are managed by an administrator</h2>
                <p>
                  Your datasets, questions and dashboards are yours alone. The AI provider and
                  branding are configured once for the whole workspace.
                </p>
              </div>
            </div>
          ))}
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
