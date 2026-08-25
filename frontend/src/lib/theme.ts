export type Theme = 'light' | 'dark'

const THEME_KEY = 'cl_theme'

export function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    /* storage unavailable */
  }
  const attr = document.documentElement.getAttribute('data-theme')
  if (attr === 'dark') return 'dark'
  return 'light'
}

export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme)
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    /* storage unavailable */
  }
}
