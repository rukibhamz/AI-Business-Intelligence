import type { KpiFormat } from '../api/client'

/**
 * The display currency is an admin setting, so the formatters are rebuilt
 * whenever it changes rather than fixed at module load.
 */
export const DEFAULT_CURRENCY = 'NGN'

let currencyCode = DEFAULT_CURRENCY
let compactCurrency = buildCurrencyFormat(currencyCode, true)
let fullCurrency = buildCurrencyFormat(currencyCode, false)

function buildCurrencyFormat(code: string, compact: boolean): Intl.NumberFormat {
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: code,
      ...(compact
        ? { notation: 'compact' as const, maximumFractionDigits: 1 }
        : { maximumFractionDigits: 2 }),
    })
  } catch {
    // An unknown code must not break every number on the page.
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: DEFAULT_CURRENCY,
      ...(compact
        ? { notation: 'compact' as const, maximumFractionDigits: 1 }
        : { maximumFractionDigits: 2 }),
    })
  }
}

export function setCurrency(code: string | null | undefined) {
  const next = (code || DEFAULT_CURRENCY).toUpperCase()
  if (next === currencyCode) return
  currencyCode = next
  compactCurrency = buildCurrencyFormat(next, true)
  fullCurrency = buildCurrencyFormat(next, false)
}

export function getCurrency(): string {
  return currencyCode
}

const compactNumber = new Intl.NumberFormat(undefined, {
  notation: 'compact',
  maximumFractionDigits: 1,
})

const fullNumber = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })

export function toNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (value == null) return null
  const parsed = Number(String(value).replace(/[^0-9.-]/g, ''))
  return Number.isFinite(parsed) ? parsed : null
}

/** Compact display value for a KPI tile or axis tick. */
export function formatValue(value: number | string, format: KpiFormat): string {
  if (format === 'text') return String(value)
  const n = toNumber(value)
  if (n == null) return String(value)
  if (format === 'currency') {
    return Math.abs(n) >= 10000 ? compactCurrency.format(n) : fullCurrency.format(n)
  }
  if (format === 'percent') {
    return `${fullNumber.format(Math.round(n * 10) / 10)}%`
  }
  return Math.abs(n) >= 10000 ? compactNumber.format(n) : fullNumber.format(n)
}

/** Full-precision value for tooltips and `title` attributes. */
export function formatExact(value: number | string, format: KpiFormat): string {
  if (format === 'text') return String(value)
  const n = toNumber(value)
  if (n == null) return String(value)
  if (format === 'currency') return fullCurrency.format(n)
  if (format === 'percent') return `${fullNumber.format(n)}%`
  return fullNumber.format(n)
}

export function formatDelta(delta: number): string {
  const sign = delta > 0 ? '+' : ''
  return `${sign}${fullNumber.format(Math.round(delta * 10) / 10)}%`
}

export function formatRelative(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const diffMs = Date.now() - date.getTime()
  const mins = Math.floor(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return hours === 1 ? '1 hour ago' : `${hours} hours ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return days === 1 ? 'yesterday' : `${days} days ago`
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function formatCell(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : fullNumber.format(value)
  }
  return String(value)
}

/**
 * Turn a SQL column name into something a reader recognises.
 *
 * A legend reading `avg_stock_level` / `min_stock_level` asks the reader to
 * parse SQL to understand a picture. These are the abbreviations that actually
 * show up in generated queries.
 */
const COLUMN_WORDS: Record<string, string> = {
  avg: 'average',
  average: 'average',
  min: 'lowest',
  minimum: 'lowest',
  max: 'highest',
  maximum: 'highest',
  qty: 'quantity',
  num: 'number of',
  cnt: 'count of',
  pct: '%',
  percent: '%',
  roi: 'ROI',
  aov: 'average order value',
  yoy: 'year on year',
  mom: 'month on month',
  id: 'ID',
  sku: 'SKU',
  vip: 'VIP',
  sme: 'SME',
}

/** `avg_stock_level` → `Average stock level`; `roi_pct` → `ROI %`. */
export function humanizeColumn(name: string): string {
  const words = String(name || '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[\s_]+/)
    .filter(Boolean)
    .map((word) => COLUMN_WORDS[word.toLowerCase()] ?? word.toLowerCase())

  if (words.length === 0) return name
  const text = words.join(' ').replace(/\s+%/g, ' %').trim()
  // Keep acronyms as they are; sentence-case everything else.
  const first = words[0]
  const head = first === first.toUpperCase() && first.length > 1 ? first : first.charAt(0).toUpperCase() + first.slice(1)
  return [head, ...words.slice(1)].join(' ').replace(/\s+%/g, ' %').trim() || text
}
