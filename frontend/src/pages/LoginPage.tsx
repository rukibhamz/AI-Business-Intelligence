import { useState } from 'react'
import { api, setSession, type AppSettings, type User } from '../api/client'
import './LoginPage.css'

export function LoginPage({
  onSuccess,
  branding,
}: {
  onSuccess: (user: User) => void
  branding?: AppSettings | null
}) {
  const platformName = branding?.platform_name || 'Cognitive Logic'
  const tagline = branding?.platform_tagline || 'Business Intelligence'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [remember, setRemember] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await api.login(email.trim(), password)
      setSession(result.access_token, result.user)
      void remember
      onSuccess(result.user)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed'
      if (message.includes('Incorrect') || message.includes('401')) {
        setError('Incorrect email or password')
      } else {
        try {
          const parsed = JSON.parse(message) as { detail?: string }
          setError(parsed.detail ?? message)
        } catch {
          setError(message)
        }
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="cl-login-root">
      <div className="cl-login-left">
        <div className="cl-login-stack">
          <div className="cl-login-intro">
            <div className="cl-login-brand">
              <div className="cl-login-mark" aria-hidden="true">
                {branding?.logo_url ? (
                  <img src={branding.logo_url} alt="" />
                ) : (
                  <span className="material-symbols-outlined filled" aria-hidden="true">insights</span>
                )}
              </div>
              <p className="cl-login-brand-title">{platformName}</p>
            </div>
            <div>
              <p className="cl-login-welcome">Welcome back</p>
              <p className="cl-login-subtitle">Sign in to continue to {platformName}.</p>
            </div>
          </div>

          <form className="cl-login-form" onSubmit={handleSubmit}>
            {error && <p className="cl-login-error" role="alert">{error}</p>}

            <div className="cl-field">
              <label className="cl-label" htmlFor="cl-email">Email Address</label>
              <input
                id="cl-email"
                name="email"
                type="email"
                autoComplete="username"
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="cl-field">
              <label className="cl-label" htmlFor="cl-password">Password</label>
              <div className="cl-password-wrap">
                <input
                  id="cl-password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  className="cl-visibility"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  onClick={() => setShowPassword((v) => !v)}
                >
                  <span className="material-symbols-outlined" aria-hidden="true">
                    {showPassword ? 'visibility_off' : 'visibility'}
                  </span>
                </button>
              </div>
            </div>

            <div className="cl-login-meta">
              <div className="cl-remember">
                <input
                  id="cl-remember"
                  name="remember"
                  type="checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                />
                <label htmlFor="cl-remember">Remember me</label>
              </div>
              <span className="cl-login-hint">
                Password resets are handled by your administrator.
              </span>
            </div>

            <button type="submit" className="cl-signin-btn" disabled={busy}>
              {busy ? 'Signing in…' : (
                <>
                  Sign In
                  <span className="material-symbols-outlined arrow" aria-hidden="true">arrow_forward</span>
                </>
              )}
            </button>
          </form>

          <div className="cl-login-footer">
            <p>Accounts are provisioned by your administrator.</p>
          </div>

        </div>
      </div>

      <aside className="cl-login-right" aria-hidden="true">
        <div className="cl-login-right-grad" />
        <div className="cl-login-right-radial" />

        <div className="cl-teaser-copy">
          <p className="cl-teaser-eyebrow">{tagline}</p>
          <p className="cl-teaser-headline">Ask your data a question.</p>
          <p className="cl-teaser-desc">
            {platformName} turns plain-English questions into SQL, runs it against the sources
            you connect, and reports only what your own data says.
          </p>
          <ul className="cl-teaser-points">
            <li>
              <span className="material-symbols-outlined" aria-hidden="true">database</span>
              Connect CSV, Excel, or MySQL
            </li>
            <li>
              <span className="material-symbols-outlined" aria-hidden="true">query_stats</span>
              KPIs and charts computed from live rows
            </li>
            <li>
              <span className="material-symbols-outlined" aria-hidden="true">flag</span>
              Findings surfaced from real anomalies
            </li>
          </ul>
        </div>
      </aside>
    </div>
  )
}
