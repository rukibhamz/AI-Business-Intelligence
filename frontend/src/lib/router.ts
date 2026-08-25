import { useCallback, useEffect, useState } from 'react'
import type { AppView } from '../layouts/navigation'

/**
 * Minimal History-API router.
 *
 * Every view owns a URL so a reload, a bookmark, or the browser Back button
 * lands on the same screen instead of falling back to the dashboard.
 */

export const ROUTES: Record<AppView, string> = {
  chat: '/ask',
  overview: '/dashboard',
  findings: '/findings',
  sources: '/data-sources',
  history: '/history',
  settings: '/settings',
}

/** New Analysis is the landing page, so `/` resolves to it. */
export const DEFAULT_VIEW: AppView = 'chat'

const PATH_TO_VIEW = new Map<string, AppView>(
  (Object.entries(ROUTES) as [AppView, string][]).map(([view, path]) => [path, view]),
)

function normalize(pathname: string): string {
  const trimmed = pathname.replace(/\/+$/, '')
  return trimmed === '' ? '/' : trimmed.toLowerCase()
}

export function viewForPath(pathname: string): AppView | null {
  const path = normalize(pathname)
  if (path === '/') return DEFAULT_VIEW
  return PATH_TO_VIEW.get(path) ?? null
}

export type Location = {
  view: AppView
  /** Query string of the current URL, e.g. `?q=12`. */
  search: string
}

function readLocation(): Location {
  return {
    view: viewForPath(window.location.pathname) ?? DEFAULT_VIEW,
    search: window.location.search,
  }
}

export function useRouter() {
  const [location, setLocation] = useState<Location>(readLocation)

  useEffect(() => {
    function onPopState() {
      setLocation(readLocation())
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  // An unknown path (typo, stale bookmark) is rewritten to the landing page
  // without adding a history entry.
  useEffect(() => {
    if (viewForPath(window.location.pathname) === null) {
      window.history.replaceState(null, '', ROUTES[DEFAULT_VIEW])
      setLocation(readLocation())
    }
  }, [])

  const navigate = useCallback(
    (view: AppView, options?: { search?: string; replace?: boolean }) => {
      const search = options?.search ?? ''
      const url = `${ROUTES[view]}${search}`
      if (url === `${window.location.pathname}${window.location.search}`) {
        setLocation({ view, search })
        return
      }
      if (options?.replace) window.history.replaceState(null, '', url)
      else window.history.pushState(null, '', url)
      setLocation({ view, search })
    },
    [],
  )

  /** Update the query string of the current view without a history entry. */
  const setSearch = useCallback((search: string) => {
    const url = `${window.location.pathname}${search}`
    if (url === `${window.location.pathname}${window.location.search}`) return
    window.history.replaceState(null, '', url)
    setLocation((prev) => ({ ...prev, search }))
  }, [])

  return { location, navigate, setSearch }
}
