import { useState } from 'react'
import { api, setSession, type User } from '../api/client'
import './LoginPage.css'

export function LoginPage({ onSuccess }: { onSuccess: (user: User) => void }) {
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
    <div className="cl-login-root" data-theme="light">
      <div className="cl-login-left">
        <div className="cl-login-stack">
          <div className="cl-login-intro">
            <div className="cl-login-brand">
              <div className="cl-login-mark" aria-hidden="true">
                <span className="material-symbols-outlined filled">auto_awesome</span>
              </div>
              <p className="cl-login-brand-title">Cognitive Logic</p>
            </div>
            <div>
              <p className="cl-login-welcome">Welcome back</p>
              <p className="cl-login-subtitle">Sign in to continue to your dashboard.</p>
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
                  <span className="material-symbols-outlined">
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
              <a className="cl-text-link" href="#" onClick={(e) => e.preventDefault()}>
                Forgot Password?
              </a>
            </div>

            <button type="submit" className="cl-signin-btn" disabled={busy}>
              {busy ? 'Signing in…' : (
                <>
                  Sign In
                  <span className="material-symbols-outlined arrow">arrow_forward</span>
                </>
              )}
            </button>
          </form>

          <div className="cl-login-footer">
            <p>
              Don&apos;t have an account?{' '}
              <a className="cl-text-link" href="#" onClick={(e) => e.preventDefault()}>
                Request Access
              </a>
            </p>
          </div>

          <div className="cl-login-version">
            <p>v2.4.1 (Enterprise)</p>
          </div>
        </div>
      </div>

      <aside className="cl-login-right" aria-hidden="true">
        <div className="cl-login-right-grad" />
        <div className="cl-login-right-radial" />

        <div className="cl-teaser">
          <div className="cl-teaser-card">
            <div className="cl-teaser-chrome">
              <span className="traffic red" />
              <span className="traffic yellow" />
              <span className="traffic green" />
              <div className="cl-model-chip">Model: GPT-4-Turbo</div>
            </div>
            <div className="cl-teaser-body">
              <img
                className="cl-teaser-img"
                src="/brand/login-dashboard.png"
                alt=""
              />
              <div className="cl-teaser-overlay">
                <div className="cl-teaser-overlay-inner">
                  <div className="cl-teaser-icon">
                    <span className="material-symbols-outlined filled">insights</span>
                  </div>
                  <div>
                    <p className="cl-teaser-overlay-title">Predictive Analysis Complete</p>
                    <p className="cl-teaser-overlay-body">
                      Identified 3 key optimization vectors in Q3 data stream.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="cl-teaser-copy">
          <p className="cl-teaser-headline">Intelligence, Applied.</p>
          <p className="cl-teaser-desc">
            Transform your complex data streams into actionable executive insights with our
            proprietary logic engine.
          </p>
        </div>
      </aside>
    </div>
  )
}
