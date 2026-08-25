import { useEffect, useState } from 'react'
import {
  api,
  type AppSettings,
  type AppSettingsUpdate,
  type ColorSchemeOption,
} from '../api/client'
import './SettingsPage.css'

type Props = {
  onSaved?: (settings: AppSettings) => void
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  mistral: 'Mistral',
  qwen: 'Qwen',
  gemini: 'Gemini',
  groq: 'Groq',
}

export function SettingsPage({ onSaved }: Props) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [okMsg, setOkMsg] = useState<string | null>(null)
  const [showKey, setShowKey] = useState(false)

  const [platformName, setPlatformName] = useState('')
  const [tagline, setTagline] = useState('')
  const [scheme, setScheme] = useState('cobalt')
  const [provider, setProvider] = useState('openai')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')

  function hydrate(s: AppSettings) {
    setSettings(s)
    setPlatformName(s.platform_name)
    setTagline(s.platform_tagline)
    setScheme(s.color_scheme)
    setProvider(s.llm_provider)
    setModel(s.openai_model)
    setBaseUrl(s.openai_base_url)
    setApiKey('')
  }

  useEffect(() => {
    setLoading(true)
    api
      .getSettings()
      .then(hydrate)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  function buildPayload(): AppSettingsUpdate {
    const payload: AppSettingsUpdate = {
      platform_name: platformName.trim(),
      platform_tagline: tagline.trim(),
      color_scheme: scheme,
      llm_provider: provider,
      openai_model: model.trim(),
      openai_base_url: baseUrl.trim(),
    }
    if (apiKey.trim() && !apiKey.includes('•')) {
      payload.openai_api_key = apiKey.trim()
    }
    return payload
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setOkMsg(null)
    try {
      const saved = await api.updateSettings(buildPayload())
      hydrate(saved)
      setOkMsg('Configuration saved.')
      onSaved?.(saved)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleCancel() {
    if (!settings) return
    hydrate(settings)
    setOkMsg(null)
    setError(null)
  }

  async function handleTest() {
    setBusy(true)
    setError(null)
    setOkMsg(null)
    try {
      const result = await api.testAiConnection(buildPayload())
      setOkMsg(result.message)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection test failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleLogo(file: File | null) {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const saved = await api.uploadLogo(file)
      hydrate(saved)
      setOkMsg('Logo updated.')
      onSaved?.(saved)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Logo upload failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleRemoveLogo() {
    setBusy(true)
    setError(null)
    try {
      const saved = await api.deleteLogo()
      hydrate(saved)
      setOkMsg('Logo removed.')
      onSaved?.(saved)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove logo')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <p className="settings-muted">Loading settings…</p>
  }

  const schemes: ColorSchemeOption[] = settings?.color_schemes ?? []
  const providers = settings?.providers ?? Object.keys(PROVIDER_LABELS)

  return (
    <div className="settings-page">
      <form className="settings-stack" onSubmit={handleSave}>
        {error && <p className="settings-error">{error}</p>}
        {okMsg && <p className="settings-ok">{okMsg}</p>}

        <section className="settings-card">
          <div className="settings-card-head">
            <h2>Platform branding</h2>
            <p>Name, logo, and color scheme for the Intelligence Hub.</p>
          </div>

          <label className="settings-field">
            <span className="settings-label">Platform name</span>
            <input
              value={platformName}
              onChange={(e) => setPlatformName(e.target.value)}
              placeholder="Cognitive Logic"
              required
            />
          </label>

          <label className="settings-field">
            <span className="settings-label">Tagline</span>
            <input
              value={tagline}
              onChange={(e) => setTagline(e.target.value)}
              placeholder="Business Intelligence"
            />
          </label>

          <div className="settings-field">
            <span className="settings-label">Logo</span>
            <div className="settings-logo-row">
              <div className="settings-logo-preview">
                {settings?.logo_url ? (
                  <img src={settings.logo_url} alt="Platform logo" />
                ) : (
                  <span className="material-symbols-outlined" aria-hidden="true">image</span>
                )}
              </div>
              <div className="settings-logo-actions">
                <label className="settings-file-btn">
                  Upload logo
                  <input
                    type="file"
                    accept=".png,.jpg,.jpeg,.webp,.svg"
                    hidden
                    onChange={(e) => void handleLogo(e.target.files?.[0] ?? null)}
                  />
                </label>
                {settings?.logo_url && (
                  <button type="button" className="settings-text-btn" onClick={() => void handleRemoveLogo()} disabled={busy}>
                    Remove
                  </button>
                )}
                <p className="settings-hint">PNG, JPG, WebP, or SVG · max 2MB</p>
              </div>
            </div>
          </div>

          <div className="settings-field">
            <span className="settings-label">Color scheme</span>
            <div className="settings-schemes">
              {schemes.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={`settings-scheme${scheme === s.id ? ' is-active' : ''}`}
                  aria-label={`Use the ${s.label} colour scheme`}
                  aria-pressed={scheme === s.id}
                  onClick={() => setScheme(s.id)}
                >
                  <span className="settings-swatches" aria-hidden>
                    <i style={{ background: s.primary }} />
                    <i style={{ background: s.primary_container }} />
                    <i style={{ background: s.secondary }} />
                  </span>
                  <span>{s.label}</span>
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="settings-card">
          <div className="settings-card-head">
            <h2>AI Provider Configuration</h2>
            <p>Configure the language model for {platformName || 'BI Assistant'} insights.</p>
          </div>

          <label className="settings-field">
            <span className="settings-label">LLM Provider</span>
            <div className="settings-select-wrap">
              <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                {providers.map((p) => (
                  <option key={p} value={p}>
                    {PROVIDER_LABELS[p] ?? p}
                  </option>
                ))}
              </select>
              <span className="material-symbols-outlined" aria-hidden="true">expand_more</span>
            </div>
          </label>

          <label className="settings-field">
            <span className="settings-label">Model name</span>
            <input
              className="settings-mono"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="gpt-4o"
            />
            <span className="settings-hint">Specific model identifier (e.g. claude-3-5-sonnet).</span>
          </label>

          <label className="settings-field">
            <span className="settings-label">API base URL</span>
            <input
              className="settings-mono"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
            />
            <span className="settings-hint">OpenAI-compatible chat completions endpoint.</span>
          </label>

          <div className="settings-field">
            <span className="settings-label">API Key</span>
            <div className="settings-key-row">
              <div className="settings-key-input">
                <input
                  className="settings-mono"
                  type={showKey ? 'text' : 'password'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={settings?.api_key_masked || 'sk-…'}
                  autoComplete="off"
                />
                <button
                  type="button"
                  className="settings-eye"
                  onClick={() => setShowKey((v) => !v)}
                  aria-label={showKey ? 'Hide API key' : 'Show API key'}
                >
                  <span className="material-symbols-outlined" aria-hidden="true">
                    {showKey ? 'visibility_off' : 'visibility'}
                  </span>
                </button>
              </div>
              <button type="button" className="settings-test-btn" onClick={() => void handleTest()} disabled={busy}>
                <span className="material-symbols-outlined" aria-hidden="true">cable</span>
                Test Connection
              </button>
            </div>
            {settings?.api_key_set && !apiKey && (
              <span className="settings-hint">Key on file — leave blank to keep current.</span>
            )}
          </div>

          <div className="settings-footer">
            <button type="button" className="settings-text-btn" onClick={() => void handleCancel()} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="settings-save" disabled={busy || !platformName.trim()}>
              Save Configuration
            </button>
          </div>
        </section>
      </form>
    </div>
  )
}
