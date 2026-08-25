import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import type { AppSettings, Finding, User } from '../api/client'
import { formatRelative } from '../lib/format'
import { applyTheme, getStoredTheme, type Theme } from '../lib/theme'
import { NAV_GROUPS, NAV_ITEMS, PAGE_META, type AppView } from './navigation'
import './AppShell.css'

export type { AppView }

const COLLAPSE_KEY = 'cl_sidebar_collapsed'

type Props = {
  user: User
  view: AppView
  onNavigate: (view: AppView) => void
  onLogout: () => void
  onOpenSearch: () => void
  onRefresh: () => void
  apiOnline?: boolean
  refreshing?: boolean
  branding?: AppSettings | null
  findings?: Finding[]
  findingsUpdatedAt?: string | null
  children: ReactNode
}

const SCHEME_VARS = [
  '--cl-primary',
  '--cl-primary-container',
  '--cl-secondary',
  '--cl-secondary-container',
] as const

/**
 * The four scheme colours drive every accent token. They must be set on the
 * root element: `--cl-accent` and friends are declared on `:root`, and a
 * custom property resolves its `var()` references against the element it is
 * declared on — so overriding the scheme lower in the tree would never
 * re-resolve them.
 */
function useColorScheme(branding?: AppSettings | null) {
  useEffect(() => {
    const root = document.documentElement
    const scheme = branding?.color_schemes.find((s) => s.id === branding.color_scheme)
    if (!scheme) {
      for (const name of SCHEME_VARS) root.style.removeProperty(name)
      return
    }
    root.style.setProperty('--cl-primary', scheme.primary)
    root.style.setProperty('--cl-primary-container', scheme.primary_container)
    root.style.setProperty('--cl-secondary', scheme.secondary)
    root.style.setProperty('--cl-secondary-container', scheme.secondary_container)
  }, [branding])
}

function initialsOf(user: User): string {
  const basis = user.full_name || user.email
  return (
    basis
      .split(/[\s@._-]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? '')
      .join('') || 'U'
  )
}

export function AppShell({
  user,
  view,
  onNavigate,
  onLogout,
  onOpenSearch,
  onRefresh,
  apiOnline,
  refreshing,
  branding,
  findings = [],
  findingsUpdatedAt,
  children,
}: Props) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === '1'
    } catch {
      return false
    }
  })
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [theme, setTheme] = useState<Theme>(() => getStoredTheme())
  const [alertsOpen, setAlertsOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const alertsRef = useRef<HTMLDivElement>(null)
  const userMenuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
    } catch {
      /* storage unavailable */
    }
  }, [collapsed])

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  useColorScheme(branding)

  // Close the mobile drawer whenever the view changes.
  useEffect(() => {
    setDrawerOpen(false)
  }, [view])

  useEffect(() => {
    if (!alertsOpen && !userMenuOpen) return
    function onPointerDown(e: MouseEvent) {
      const target = e.target as Node
      if (alertsOpen && alertsRef.current && !alertsRef.current.contains(target)) {
        setAlertsOpen(false)
      }
      if (userMenuOpen && userMenuRef.current && !userMenuRef.current.contains(target)) {
        setUserMenuOpen(false)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setAlertsOpen(false)
        setUserMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [alertsOpen, userMenuOpen])

  const navigate = useCallback(
    (next: AppView) => {
      onNavigate(next)
      setAlertsOpen(false)
      setUserMenuOpen(false)
    },
    [onNavigate],
  )

  const displayName = user.full_name || user.email.split('@')[0] || 'User'
  const initials = initialsOf(user)
  const platformName = branding?.platform_name || 'Cognitive Logic'
  const tagline = branding?.platform_tagline || 'Business Intelligence'
  const meta = PAGE_META[view]

  const urgent = findings.filter(
    (f) => f.severity === 'critical' || f.severity === 'warning',
  )
  const alertCount = urgent.length

  const sidebar = (
    <>
      <div className="shell-brand">
        <div className="shell-brand-mark" aria-hidden="true">
          {branding?.logo_url ? (
            <img src={branding.logo_url} alt="" />
          ) : (
            <span className="material-symbols-outlined filled" aria-hidden="true">insights</span>
          )}
        </div>
        <div className="shell-brand-copy">
          <p className="shell-brand-name" title={platformName}>
            {platformName}
          </p>
          <p className="shell-brand-tagline" title={tagline}>
            {tagline}
          </p>
        </div>
        <button
          type="button"
          className="shell-collapse"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((v) => !v)}
        >
          <span className="material-symbols-outlined" aria-hidden="true">
            {collapsed ? 'chevron_right' : 'chevron_left'}
          </span>
        </button>
      </div>

      <nav className="shell-nav-scroll" aria-label="Main navigation">
        {NAV_GROUPS.map((group) => {
          const items = NAV_ITEMS.filter((item) => item.group === group)
          if (items.length === 0) return null
          return (
            <div key={group} className="shell-nav-section">
              <p className="shell-section-label">{group}</p>
              <div className="shell-nav">
                {items.map((item) => {
                  const active = view === item.id
                  const badge = item.id === 'findings' && alertCount > 0 ? alertCount : null
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={`shell-nav-item${active ? ' is-active' : ''}`}
                      aria-label={item.label}
                      aria-current={active ? 'page' : undefined}
                      onClick={() => navigate(item.id)}
                      data-tooltip={item.label}
                    >
                      <span className="material-symbols-outlined" aria-hidden="true">{item.icon}</span>
                      <span className="shell-nav-label">{item.label}</span>
                      {badge != null && (
                        <span className="shell-nav-badge" aria-label={`${badge} open findings`}>
                          {badge > 99 ? '99+' : badge}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </nav>

      <div className="shell-user" ref={userMenuRef}>
        <button
          type="button"
          className="shell-user-trigger"
          aria-label={`Account menu for ${displayName}`}
          aria-haspopup="menu"
          aria-expanded={userMenuOpen}
          onClick={() => setUserMenuOpen((v) => !v)}
          data-tooltip={displayName}
        >
          <span className="shell-avatar" aria-hidden="true">
            {initials}
          </span>
          <span className="shell-user-copy">
            <span className="shell-user-name">{displayName}</span>
            <span className="shell-user-email">{user.email}</span>
          </span>
          <span className="material-symbols-outlined shell-user-caret" aria-hidden="true">unfold_more</span>
        </button>

        {userMenuOpen && (
          <div className="shell-menu" role="menu">
            <p className="shell-menu-head">{user.email}</p>
            <button
              type="button"
              role="menuitem"
              className="shell-menu-item"
              onClick={() => navigate('settings')}
            >
              <span className="material-symbols-outlined" aria-hidden="true">settings</span>
              Settings
            </button>
            <button
              type="button"
              role="menuitem"
              className="shell-menu-item"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              <span className="material-symbols-outlined" aria-hidden="true">
                {theme === 'dark' ? 'light_mode' : 'dark_mode'}
              </span>
              {theme === 'dark' ? 'Light theme' : 'Dark theme'}
            </button>
            <div className="shell-menu-sep" />
            <button
              type="button"
              role="menuitem"
              className="shell-menu-item shell-menu-item--danger"
              onClick={onLogout}
            >
              <span className="material-symbols-outlined" aria-hidden="true">logout</span>
              Log out
            </button>
          </div>
        )}
      </div>
    </>
  )

  return (
    <div
      className={`shell${collapsed ? ' shell--collapsed' : ''}${
        drawerOpen ? ' shell--drawer-open' : ''
      }`}
    >
      <aside className="shell-sidebar" aria-label="Sidebar">
        {sidebar}
      </aside>

      {drawerOpen && (
        <div
          className="shell-scrim"
          role="presentation"
          onClick={() => setDrawerOpen(false)}
        />
      )}

      <header className="shell-topbar">
        <button
          type="button"
          className="shell-menu-btn"
          aria-label="Open navigation"
          aria-expanded={drawerOpen}
          onClick={() => setDrawerOpen(true)}
        >
          <span className="material-symbols-outlined" aria-hidden="true">menu</span>
        </button>

        <div className="shell-page-meta">
          <h1 className="shell-page-title">{meta.title}</h1>
          <p className="shell-page-sub">{meta.subtitle}</p>
        </div>

        <button
          type="button"
          className="shell-search"
          aria-label="Search pages, data sources, and questions"
          onClick={onOpenSearch}
        >
          <span className="material-symbols-outlined" aria-hidden="true">search</span>
          <span className="shell-search-text">Search…</span>
          <kbd className="shell-search-kbd">Ctrl K</kbd>
        </button>

        <div className="shell-top-actions">
          <button
            type="button"
            className="shell-icon-btn"
            onClick={onRefresh}
            disabled={refreshing}
            aria-label="Refresh live data"
            title="Refresh live data"
          >
            <span
              className={`material-symbols-outlined${refreshing ? ' is-spinning' : ''}`}
              aria-hidden="true"
            >
              refresh
            </span>
          </button>

          <button
            type="button"
            className="shell-icon-btn"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
          >
            <span className="material-symbols-outlined" aria-hidden="true">
              {theme === 'dark' ? 'light_mode' : 'dark_mode'}
            </span>
          </button>

          <div className="shell-alerts" ref={alertsRef}>
            <button
              type="button"
              className="shell-icon-btn"
              aria-label={`Findings${alertCount ? `, ${alertCount} needing attention` : ''}`}
              aria-expanded={alertsOpen}
              onClick={() => setAlertsOpen((v) => !v)}
            >
              <span className="material-symbols-outlined" aria-hidden="true">notifications</span>
              {alertCount > 0 && (
                <span className="shell-alert-dot">{alertCount > 9 ? '9+' : alertCount}</span>
              )}
            </button>

            {alertsOpen && (
              <div className="shell-popover" role="dialog" aria-label="Findings">
                <div className="shell-popover-head">
                  <p>Findings</p>
                  {findingsUpdatedAt && (
                    <span>updated {formatRelative(findingsUpdatedAt)}</span>
                  )}
                </div>
                {urgent.length === 0 ? (
                  <p className="shell-popover-empty">
                    Nothing needs attention in your connected data right now.
                  </p>
                ) : (
                  <ul className="shell-popover-list">
                    {urgent.slice(0, 5).map((finding) => (
                      <li key={finding.id}>
                        <button type="button" onClick={() => navigate('findings')}>
                          <span
                            className={`shell-popover-dot shell-popover-dot--${finding.severity}`}
                            aria-hidden="true"
                          />
                          <span className="shell-popover-copy">
                            <span className="shell-popover-title">{finding.title}</span>
                            <span className="shell-popover-meta">
                              {finding.source_name ?? finding.context}
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <button
                  type="button"
                  className="shell-popover-all"
                  onClick={() => navigate('findings')}
                >
                  View all findings
                </button>
              </div>
            )}
          </div>

          <span
            className={`shell-api${apiOnline ? ' is-ok' : ''}`}
            title={apiOnline ? 'API reachable' : 'API unreachable'}
          >
            <span className="shell-api-dot" aria-hidden="true" />
            {apiOnline ? 'Online' : 'Offline'}
          </span>
        </div>
      </header>

      <main
        className={`shell-main${view === 'chat' || view === 'history' ? ' shell-main--full' : ''}`}
        id="main"
      >
        {children}
      </main>
    </div>
  )
}
