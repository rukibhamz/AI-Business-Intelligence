/**
 * An analysis session groups the questions asked in one sitting so history can
 * show them together. The id is minted client-side and sent with each query.
 */

const SESSION_KEY = 'cl_analysis_session'
/** The in-progress transcript, cleared whenever a new session starts. */
export const THREAD_KEY = 'cl_ask_thread'

function mint(): string {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  return `s_${random}`.slice(0, 64)
}

export function getSessionId(): string {
  try {
    const existing = localStorage.getItem(SESSION_KEY)
    if (existing) return existing
    const created = mint()
    localStorage.setItem(SESSION_KEY, created)
    return created
  } catch {
    // Storage unavailable: still return a usable id for this page view.
    return mint()
  }
}

/** Start a fresh session, dropping the current transcript. Returns the new id. */
export function startNewSession(): string {
  const created = mint()
  try {
    localStorage.setItem(SESSION_KEY, created)
    sessionStorage.removeItem(THREAD_KEY)
  } catch {
    /* storage unavailable */
  }
  return created
}
