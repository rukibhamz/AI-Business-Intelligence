import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import { clearSession, getToken, setTokenSource, type AuthConfig, type User } from '../api/client'

/**
 * Sign-in, whichever way this deployment is configured.
 *
 * The API decides: with a Supabase project wired up, accounts and passwords
 * live there and the browser talks to it directly; without one, the API issues
 * its own token as before. Everything above this module works the same either
 * way — it asks for a token and gets one.
 */

let config: AuthConfig | null = null
let client: SupabaseClient | null = null

export function authConfig(): AuthConfig | null {
  return config
}

export function isSupabase(): boolean {
  return config?.provider === 'supabase'
}

export function supabase(): SupabaseClient | null {
  if (!config || config.provider !== 'supabase') return null
  if (!client) {
    client = createClient(config.supabase_url, config.supabase_anon_key, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
    // From here the API client asks Supabase for the current token rather than
    // reading a stale one out of storage.
    setTokenSource(currentToken, () => {
      void client?.auth.signOut()
      clearSession()
    })
  }
  return client
}

/** Load the sign-in configuration once, before the login screen renders. */
export async function loadAuthConfig(fetchConfig: () => Promise<AuthConfig>): Promise<AuthConfig> {
  if (config) return config
  config = await fetchConfig()
  return config
}

/**
 * The bearer token for an API call.
 *
 * Supabase access tokens expire in an hour, so this asks the client for the
 * current one every time — it refreshes in the background and hands back the
 * fresh token rather than a stale one from storage.
 */
export async function currentToken(): Promise<string | null> {
  const sb = supabase()
  if (!sb) return getToken()
  const { data } = await sb.auth.getSession()
  return data.session?.access_token ?? null
}

export async function signIn(email: string, password: string): Promise<void> {
  const sb = supabase()
  if (!sb) throw new Error('Supabase is not configured for this workspace.')
  const { error } = await sb.auth.signInWithPassword({ email, password })
  if (error) throw new Error(error.message)
}

export type SignUpResult = { needsConfirmation: boolean }

export async function signUp(
  email: string,
  password: string,
  fullName: string,
): Promise<SignUpResult> {
  const sb = supabase()
  if (!sb) throw new Error('Supabase is not configured for this workspace.')
  const { data, error } = await sb.auth.signUp({
    email,
    password,
    options: { data: { full_name: fullName } },
  })
  if (error) throw new Error(error.message)
  // With email confirmation on, Supabase returns a user but no session until
  // the link is clicked. Say so rather than leaving the screen looking stuck.
  return { needsConfirmation: !data.session }
}

export async function signOut(): Promise<void> {
  const sb = supabase()
  if (sb) await sb.auth.signOut()
  clearSession()
}

/** Fires when a token is refreshed or the session ends in another tab. */
export function onAuthChange(handler: (signedIn: boolean) => void): () => void {
  const sb = supabase()
  if (!sb) return () => undefined
  const { data } = sb.auth.onAuthStateChange((event, session) => {
    if (event === 'SIGNED_OUT' || (!session && event !== 'INITIAL_SESSION')) handler(false)
    else if (session) handler(true)
  })
  return () => data.subscription.unsubscribe()
}

export type { User }
