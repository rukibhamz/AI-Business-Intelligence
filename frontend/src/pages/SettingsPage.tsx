import { useEffect, useState } from 'react'
import {
  api,
  type AppSettings,
  type AppSettingsUpdate,
  type ColorSchemeOption,
  type LlmProviderProfile,
  type LlmProviderUpdate,
} from '../api/client'
import './SettingsPage.css'

type Props = {
  onSaved?: (settings: AppSettings) => void
}

type DraftProvider = LlmProviderUpdate & {
  id: string
  label: string
  provider: string
  model: string
  base_url: string
  priority: number
  enabled: boolean
  api_key: string
  api_key_set?: boolean
  api_key_masked?: string | null
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic (via compatible gateway)',
  mistral: 'Mistral',
  qwen: 'Qwen',
  gemini: 'Gemini',
  groq: 'Groq',
  custom: 'Custom (OpenAI-compatible)',
}

const PRESET_DEFAULTS: Record<string, { base_url: string; model: string }> = {
  openai: { base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  anthropic: { base_url: 'https://openrouter.ai/api/v1', model: 'anthropic/claude-3.5-sonnet' },
  mistral: { base_url: 'https://api.mistral.ai/v1', model: 'mistral-large-latest' },
  qwen: {
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-plus',
  },
  gemini: {
    base_url: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    model: 'gemini-2.0-flash',
  },
  groq: { base_url: 'https://api.groq.com/openai/v1', model: 'llama-3.3-70b-versatile' },
  custom: { base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
}

function toDraft(p: LlmProviderProfile): DraftProvider {
  return {
    id: p.id,
    label: p.label,
    provider: p.provider,
    model: p.model,
    base_url: p.base_url,
    priority: p.priority,
    enabled: p.enabled,
    api_key: '',
    api_key_set: p.api_key_set,
    api_key_masked: p.api_key_masked,
  }
}

function newDraft(priority: number): DraftProvider {
  const preset = PRESET_DEFAULTS.openai
  return {
    id: `new-${Date.now()}`,
    label: `Provider ${priority}`,
    provider: 'openai',
    model: preset.model,
    base_url: preset.base_url,
    priority,
    enabled: true,
    api_key: '',
    api_key_set: false,
    api_key_masked: null,
  }
}

export function SettingsPage({ onSaved }: Props) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [okMsg, setOkMsg] = useState<string | null>(null)
  const [testMsg, setTestMsg] = useState<string | null>(null)
  const [testOk, setTestOk] = useState<boolean | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({})

  const [platformName, setPlatformName] = useState('')
  const [tagline, setTagline] = useState('')
  const [scheme, setScheme] = useState('cobalt')
  const [currency, setCurrencyChoice] = useState('NGN')
  const [providers, setProviders] = useState<DraftProvider[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  // Web research: the practice lane on advisory answers. Off unless a key is set.
  const [researchOn, setResearchOn] = useState(false)
  const [braveKey, setBraveKey] = useState('')
  const [braveCountry, setBraveCountry] = useState('')

  function hydrate(s: AppSettings) {
    setSettings(s)
    setPlatformName(s.platform_name)
    setTagline(s.platform_tagline)
    setScheme(s.color_scheme)
    setCurrencyChoice(s.currency || 'NGN')
    setResearchOn(Boolean(s.web_research_enabled))
    setBraveCountry(s.brave_search_country || '')
    setBraveKey(s.brave_search_key_masked || '')
    const list = (s.llm_providers?.length ? s.llm_providers : []).map(toDraft)
    if (list.length === 0) {
      list.push(
        toDraft({
          id: 'legacy-default',
          label: 'Primary',
          provider: s.llm_provider || 'openai',
          model: s.openai_model,
          base_url: s.openai_base_url,
          priority: 1,
          enabled: true,
          api_key_set: s.api_key_set,
          api_key_masked: s.api_key_masked,
        }),
      )
    }
    setProviders(list)
    setActiveId(s.active_provider_id || list[0]?.id || null)
  }

  useEffect(() => {
    setLoading(true)
    api
      .getSettings()
      .then(hydrate)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  function updateProvider(id: string, patch: Partial<DraftProvider>) {
    setProviders((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)))
  }

  function buildPayload(): AppSettingsUpdate {
    return {
      platform_name: platformName.trim(),
      platform_tagline: tagline.trim(),
      color_scheme: scheme,
      currency,
      web_research_enabled: researchOn,
      brave_search_country: braveCountry.trim().toUpperCase() || undefined,
      // A masked value round-tripping is a no-op; only a real key is saved.
      ...(braveKey.trim() && !braveKey.includes('•')
        ? { brave_search_api_key: braveKey.trim() }
        : {}),
      active_provider_id: activeId || undefined,
      llm_providers: providers.map((p) => {
        const row: LlmProviderUpdate = {
          id: p.id.startsWith('new-') ? undefined : p.id,
          label: p.label.trim() || p.provider,
          provider: p.provider,
          model: p.model.trim(),
          base_url: p.base_url.trim(),
          priority: Number(p.priority) || 1,
          enabled: p.enabled,
        }
        if (p.api_key.trim() && !p.api_key.includes('•')) {
          row.api_key = p.api_key.trim()
        }
        return row
      }),
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setOkMsg(null)
    setTestMsg(null)
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
    setTestMsg(null)
  }

  async function handleTest(p: DraftProvider) {
    setTestingId(p.id)
    setBusy(true)
    setError(null)
    setOkMsg(null)
    setTestMsg(null)
    setTestOk(null)
    try {
      const payload: {
        provider_id?: string
        llm_provider: string
        openai_model: string
        openai_base_url: string
        openai_api_key?: string
      } = {
        llm_provider: p.provider,
        openai_model: p.model.trim(),
        openai_base_url: p.base_url.trim(),
      }
      if (!p.id.startsWith('new-')) {
        payload.provider_id = p.id
      }
      if (p.api_key.trim() && !p.api_key.includes('•')) {
        payload.openai_api_key = p.api_key.trim()
      }
      const result = await api.testAiConnection(payload)
      setTestOk(true)
      setTestMsg(result.message)
      setOkMsg(result.message)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Connection test failed'
      setTestOk(false)
      setTestMsg(message)
      setError(message)
    } finally {
      setBusy(false)
      setTestingId(null)
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
  const providerOptions = settings?.providers?.length
    ? settings.providers
    : Object.keys(PROVIDER_LABELS)

  return (
    <div className="settings-page">
      <form className="settings-stack" onSubmit={handleSave}>
        {error && <p className="settings-error">{error}</p>}
        {okMsg && !error && <p className="settings-ok">{okMsg}</p>}

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
                  <span className="material-symbols-outlined" aria-hidden="true">
                    image
                  </span>
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
                  <button
                    type="button"
                    className="settings-text-btn"
                    onClick={() => void handleRemoveLogo()}
                    disabled={busy}
                  >
                    Remove
                  </button>
                )}
                <p className="settings-hint">PNG, JPG, WebP, or SVG · max 2MB</p>
              </div>
            </div>
          </div>

          <div className="settings-field">
            <span className="settings-label">Currency</span>
            <div className="settings-select-wrap">
              <select value={currency} onChange={(e) => setCurrencyChoice(e.target.value)}>
                {(settings?.currencies ?? []).map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.symbol}  {c.code} — {c.label}
                  </option>
                ))}
              </select>
              <span className="material-symbols-outlined" aria-hidden="true">
                expand_more
              </span>
            </div>
            <span className="settings-hint">
              Applies to every money figure — KPIs, charts, and AI answers.
            </span>
          </div>

          <div className="settings-field">
            <span className="settings-label">Web research</span>
            <label className="settings-toggle">
              <input
                type="checkbox"
                checked={researchOn}
                onChange={(e) => setResearchOn(e.target.checked)}
              />
              <span>Add outside guidance to advice questions</span>
            </label>
            <span className="settings-hint">
              When someone asks what to do, the answer keeps its measured findings and
              adds a separate, clearly marked list of general practices retrieved from
              the web, each with a link. Retrieved guidance never carries a figure
              about your business — every number still comes from your own data.
            </span>
            <input
              type="password"
              value={braveKey}
              placeholder="Brave Search API key"
              autoComplete="off"
              onChange={(e) => setBraveKey(e.target.value)}
            />
            <input
              type="text"
              value={braveCountry}
              placeholder="Country bias, e.g. NG (optional)"
              maxLength={2}
              onChange={(e) => setBraveCountry(e.target.value)}
            />
            <span className="settings-hint">
              {settings?.brave_search_key_set
                ? 'A key is saved. Leave the field untouched to keep it.'
                : 'No key saved — advice answers stay measured-only until one is added.'}
            </span>
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
            <h2>AI provider configurations</h2>
            <p>
              Save multiple OpenAI-compatible providers, set priority (1 = highest), and switch
              which one is active. Ask AI uses the active provider; if it has no key, the next
              enabled profile by priority is used.
            </p>
          </div>

          <div className="settings-provider-list">
            {providers.map((p) => {
              const isActive = activeId === p.id
              return (
                <article
                  key={p.id}
                  className={`settings-provider-card${isActive ? ' is-active' : ''}${
                    !p.enabled ? ' is-disabled' : ''
                  }`}
                >
                  <div className="settings-provider-top">
                    <label className="settings-active-radio">
                      <input
                        type="radio"
                        name="active-provider"
                        checked={isActive}
                        onChange={() => setActiveId(p.id)}
                      />
                      <span>{isActive ? 'Active' : 'Set active'}</span>
                    </label>
                    <label className="settings-enable">
                      <input
                        type="checkbox"
                        checked={p.enabled}
                        onChange={(e) => updateProvider(p.id, { enabled: e.target.checked })}
                      />
                      Enabled
                    </label>
                    <button
                      type="button"
                      className="settings-text-btn"
                      disabled={providers.length <= 1 || busy}
                      onClick={() => {
                        setProviders((prev) => prev.filter((x) => x.id !== p.id))
                        if (activeId === p.id) {
                          const next = providers.find((x) => x.id !== p.id)
                          setActiveId(next?.id ?? null)
                        }
                      }}
                    >
                      Remove
                    </button>
                  </div>

                  <div className="settings-provider-grid">
                    <label className="settings-field">
                      <span className="settings-label">Label</span>
                      <input
                        value={p.label}
                        onChange={(e) => updateProvider(p.id, { label: e.target.value })}
                        placeholder="Production OpenAI"
                      />
                    </label>
                    <label className="settings-field">
                      <span className="settings-label">Priority</span>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={p.priority}
                        onChange={(e) =>
                          updateProvider(p.id, { priority: Number(e.target.value) || 1 })
                        }
                      />
                    </label>
                    <label className="settings-field">
                      <span className="settings-label">Provider</span>
                      <div className="settings-select-wrap">
                        <select
                          value={p.provider}
                          onChange={(e) => {
                            const next = e.target.value
                            const preset = PRESET_DEFAULTS[next] || PRESET_DEFAULTS.custom
                            updateProvider(p.id, {
                              provider: next,
                              base_url: preset.base_url,
                              model: preset.model,
                            })
                          }}
                        >
                          {providerOptions.map((id) => (
                            <option key={id} value={id}>
                              {PROVIDER_LABELS[id] ?? id}
                            </option>
                          ))}
                        </select>
                        <span className="material-symbols-outlined" aria-hidden="true">
                          expand_more
                        </span>
                      </div>
                    </label>
                    <label className="settings-field">
                      <span className="settings-label">Model</span>
                      <input
                        className="settings-mono"
                        value={p.model}
                        onChange={(e) => updateProvider(p.id, { model: e.target.value })}
                        placeholder="gpt-4o-mini"
                      />
                    </label>
                    <label className="settings-field settings-field--full">
                      <span className="settings-label">API base URL</span>
                      <input
                        className="settings-mono"
                        value={p.base_url}
                        onChange={(e) => updateProvider(p.id, { base_url: e.target.value })}
                        placeholder="https://api.openai.com/v1"
                      />
                      <span className="settings-hint">
                        Must expose OpenAI-compatible <code>/chat/completions</code>.
                      </span>
                    </label>
                    <div className="settings-field settings-field--full">
                      <span className="settings-label">API key</span>
                      <div className="settings-key-row">
                        <div className="settings-key-input">
                          <input
                            className="settings-mono"
                            type={showKeys[p.id] ? 'text' : 'password'}
                            value={p.api_key}
                            onChange={(e) => updateProvider(p.id, { api_key: e.target.value })}
                            placeholder={p.api_key_masked || 'sk-…'}
                            autoComplete="off"
                          />
                          <button
                            type="button"
                            className="settings-eye"
                            onClick={() =>
                              setShowKeys((prev) => ({ ...prev, [p.id]: !prev[p.id] }))
                            }
                            aria-label={showKeys[p.id] ? 'Hide API key' : 'Show API key'}
                          >
                            <span className="material-symbols-outlined" aria-hidden="true">
                              {showKeys[p.id] ? 'visibility_off' : 'visibility'}
                            </span>
                          </button>
                        </div>
                        <button
                          type="button"
                          className="settings-test-btn"
                          onClick={() => void handleTest(p)}
                          disabled={busy}
                        >
                          <span className="material-symbols-outlined" aria-hidden="true">
                            cable
                          </span>
                          {testingId === p.id ? 'Testing…' : 'Test connection'}
                        </button>
                      </div>
                      {p.api_key_set && !p.api_key && (
                        <span className="settings-hint">Key on file — leave blank to keep.</span>
                      )}
                    </div>
                  </div>
                </article>
              )
            })}
          </div>

          {testMsg && (
            <p className={testOk ? 'settings-ok' : 'settings-error'} role="status">
              {testMsg}
            </p>
          )}

          <div className="settings-provider-actions">
            <button
              type="button"
              className="settings-file-btn"
              disabled={busy}
              onClick={() => {
                const nextPriority =
                  providers.reduce((max, p) => Math.max(max, Number(p.priority) || 0), 0) + 1
                const draft = newDraft(nextPriority)
                setProviders((prev) => [...prev, draft])
                if (!activeId) setActiveId(draft.id)
              }}
            >
              <span className="material-symbols-outlined" aria-hidden="true">
                add
              </span>
              Add provider
            </button>
          </div>

          <div className="settings-footer">
            <button
              type="button"
              className="settings-text-btn"
              onClick={() => void handleCancel()}
              disabled={busy}
            >
              Cancel
            </button>
            <button type="submit" className="settings-save" disabled={busy || !platformName.trim()}>
              Save configuration
            </button>
          </div>
        </section>
      </form>
    </div>
  )
}
