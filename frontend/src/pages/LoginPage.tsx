import { useEffect, useState } from 'react'
import {
  api,
  describeNetworkFailure,
  isNetworkFailure,
  setSession,
  type AppSettings,
  type AuthConfig,
  type User,
} from '../api/client'
import { signIn, signUp } from '../lib/auth'
import './LoginPage.css'

export function LoginPage({
  onSuccess,
  branding,
  auth,
}: {
  onSuccess: (user: User) => void
  branding?: AppSettings | null
  auth?: AuthConfig | null
}) {
  const platformName = branding?.platform_name || 'Cognitive Logic'
  const tagline = branding?.platform_tagline || 'Business Intelligence'
  const viaSupabase = auth?.provider === 'supabase'
  const canSignUp = Boolean(auth?.allow_signup)

  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [remember, setRemember] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [verifyEmail, setVerifyEmail] = useState<string | null>(null)

  const signingUp = mode === 'signup' && canSignUp

  function closeVerifyModal() {
    setVerifyEmail(null)
    setMode('signin')
    setPassword('')
  }

  useEffect(() => {
    if (!verifyEmail) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') closeVerifyModal()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [verifyEmail])

  function readableError(err: unknown): string {
    const message = err instanceof Error ? err.message : 'Sign-in failed'
    if (isNetworkFailure(err)) {
      // Replaced a moment later by the diagnosis, which needs a round trip.
      return 'Could not reach the server…'
    }
    if (message.includes('Incorrect') || message.includes('401')) {
      return 'Incorrect email or password'
    }
    if (message.toLowerCase().includes('invalid login credentials')) {
      return 'Incorrect email or password'
    }
    try {
      const parsed = JSON.parse(message) as { detail?: string }
      return parsed.detail ?? message
    } catch {
      return message
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (viaSupabase) {
        if (signingUp) {
          const { needsConfirmation } = await signUp(email.trim(), password, fullName.trim())
          if (needsConfirmation) {
            setVerifyEmail(email.trim())
            setPassword('')
            return
          }
        } else {
          await signIn(email.trim(), password)
        }
        // The API provisions the local account from the verified token.
        onSuccess(await api.me())
        return
      }

      const result = await api.login(email.trim(), password)
      setSession(result.access_token, result.user)
      void remember
      onSuccess(result.user)
    } catch (err) {
      setError(readableError(err))
      // "Failed to fetch" covers both a blocked origin and a missing server.
      // Find out which, and say so, rather than leaving the reader to guess.
      if (isNetworkFailure(err)) setError(await describeNetworkFailure())
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
              <p className="cl-login-welcome">{signingUp ? 'Create your account' : 'Welcome back'}</p>
              <p className="cl-login-subtitle">
                {signingUp
                  ? `Your datasets stay private to your account on ${platformName}.`
                  : `Sign in to continue to ${platformName}.`}
              </p>
            </div>
          </div>

          <form className="cl-login-form" onSubmit={handleSubmit}>
            {error && <p className="cl-login-error" role="alert">{error}</p>}

            {signingUp && (
              <div className="cl-field">
                <label className="cl-label" htmlFor="cl-name">Full Name</label>
                <input
                  id="cl-name"
                  name="name"
                  type="text"
                  autoComplete="name"
                  placeholder="Ada Lovelace"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                />
              </div>
            )}

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
                  autoComplete={signingUp ? 'new-password' : 'current-password'}
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
                {viaSupabase
                  ? 'Password resets are handled by Supabase.'
                  : 'Password resets are handled by your administrator.'}
              </span>
            </div>

            <button type="submit" className="cl-signin-btn" disabled={busy}>
              {busy ? (
                signingUp ? 'Creating account…' : 'Signing in…'
              ) : (
                <>
                  {signingUp ? 'Create Account' : 'Sign In'}
                  <span className="material-symbols-outlined arrow" aria-hidden="true">arrow_forward</span>
                </>
              )}
            </button>
          </form>

          <div className="cl-login-footer">
            {canSignUp ? (
              <p>
                {signingUp ? 'Already have an account?' : "Don't have an account?"}{' '}
                <button
                  type="button"
                  className="cl-login-switch"
                  onClick={() => {
                    setMode(signingUp ? 'signin' : 'signup')
                    setError(null)
                  }}
                >
                  {signingUp ? 'Sign in' : 'Create one'}
                </button>
              </p>
            ) : (
              <p>Accounts are provisioned by your administrator.</p>
            )}
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

      {verifyEmail && (
        <div
          className="cl-verify-backdrop"
          role="presentation"
          onClick={closeVerifyModal}
        >
          <div
            className="cl-verify-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="cl-verify-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="cl-verify-icon" aria-hidden="true">
              <span className="material-symbols-outlined">mark_email_unread</span>
            </div>
            <h2 id="cl-verify-title">Verify your email</h2>
            <p className="cl-verify-body">
              We sent a confirmation link to{' '}
              <strong>{verifyEmail}</strong>. Open it to activate your account,
              then come back and sign in.
            </p>
            <p className="cl-verify-hint">
              Don’t see it? Check spam or promotions. The link may take a minute
              to arrive.
            </p>
            <button type="button" className="cl-signin-btn" onClick={closeVerifyModal}>
              Back to sign in
              <span className="material-symbols-outlined arrow" aria-hidden="true">
                arrow_forward
              </span>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
