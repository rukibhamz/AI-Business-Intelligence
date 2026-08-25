import { useEffect, useMemo, useRef, useState } from 'react'
import type { DataSource, QueryRecord } from '../api/client'
import type { AppView } from '../layouts/navigation'
import { NAV_ITEMS } from '../layouts/navigation'
import './CommandPalette.css'

export type PaletteAction =
  | { kind: 'navigate'; view: AppView }
  | { kind: 'source'; id: number }
  | { kind: 'query'; id: number }
  | { kind: 'ask'; text: string }

type Entry = {
  id: string
  group: string
  icon: string
  label: string
  hint?: string
  action: PaletteAction
}

type Props = {
  open: boolean
  onClose: () => void
  sources: DataSource[]
  queries: QueryRecord[]
  onAction: (action: PaletteAction) => void
}

function score(entry: Entry, query: string): number {
  if (!query) return 1
  const haystack = `${entry.label} ${entry.hint ?? ''} ${entry.group}`.toLowerCase()
  const needle = query.toLowerCase()
  if (haystack.startsWith(needle)) return 3
  if (haystack.includes(needle)) return 2
  // Loose subsequence match so "dsrc" finds "Data Sources".
  let cursor = 0
  for (const char of needle) {
    cursor = haystack.indexOf(char, cursor)
    if (cursor === -1) return 0
    cursor += 1
  }
  return 1
}

export function CommandPalette({ open, onClose, sources, queries, onAction }: Props) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const entries = useMemo<Entry[]>(() => {
    const nav: Entry[] = NAV_ITEMS.map((item) => ({
      id: `nav-${item.id}`,
      group: 'Navigate',
      icon: item.icon,
      label: item.label,
      hint: item.description,
      action: { kind: 'navigate', view: item.id },
    }))

    const sourceEntries: Entry[] = sources.map((s) => ({
      id: `source-${s.id}`,
      group: 'Data sources',
      icon: s.source_type === 'mysql' ? 'database' : 'table_chart',
      label: s.name,
      hint: `${s.source_type}${s.row_count != null ? ` · ${s.row_count.toLocaleString()} rows` : ''}`,
      action: { kind: 'source', id: s.id },
    }))

    const queryEntries: Entry[] = queries.slice(0, 12).map((q) => ({
      id: `query-${q.id}`,
      group: 'Recent questions',
      icon: 'history',
      label: q.natural_language,
      hint: new Date(q.created_at).toLocaleDateString(),
      action: { kind: 'query', id: q.id },
    }))

    return [...nav, ...sourceEntries, ...queryEntries]
  }, [sources, queries])

  const results = useMemo(() => {
    const trimmed = query.trim()
    const ranked = entries
      .map((entry) => ({ entry, rank: score(entry, trimmed) }))
      .filter((r) => r.rank > 0)
      .sort((a, b) => b.rank - a.rank)
      .map((r) => r.entry)

    if (trimmed.length > 2) {
      ranked.push({
        id: 'ask-ai',
        group: 'Ask AI',
        icon: 'auto_awesome',
        label: `Ask "${trimmed}"`,
        hint: 'Run this as a question against your data',
        action: { kind: 'ask', text: trimmed },
      })
    }
    return ranked.slice(0, 30)
  }, [entries, query])

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>('[data-active="true"]')
      ?.scrollIntoView({ block: 'nearest' })
  }, [active])

  if (!open) return null

  const grouped: { group: string; items: Entry[] }[] = []
  for (const entry of results) {
    const last = grouped[grouped.length - 1]
    if (last && last.group === entry.group) last.items.push(entry)
    else grouped.push({ group: entry.group, items: [entry] })
  }

  function choose(entry: Entry) {
    onAction(entry.action)
    onClose()
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => (results.length ? (i + 1) % results.length : 0))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => (results.length ? (i - 1 + results.length) % results.length : 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const entry = results[active]
      if (entry) choose(entry)
    }
  }

  let flatIndex = -1

  return (
    <div className="cl-palette-scrim" role="presentation" onMouseDown={onClose}>
      <div
        className="cl-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Search"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="cl-palette-input">
          <span className="material-symbols-outlined" aria-hidden="true">search</span>
          <input
            ref={inputRef}
            value={query}
            autoFocus
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            onKeyDown={handleKeyDown}
            placeholder="Search pages, data sources, and past questions…"
            aria-label="Search"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="cl-palette-kbd">Esc</kbd>
        </div>

        <div className="cl-palette-results" ref={listRef}>
          {results.length === 0 && (
            <p className="cl-palette-empty">No matches for “{query}”.</p>
          )}
          {grouped.map((section) => (
            <div key={section.group} className="cl-palette-group">
              <p className="cl-palette-group-label">{section.group}</p>
              {section.items.map((entry) => {
                flatIndex += 1
                const index = flatIndex
                return (
                  <button
                    key={entry.id}
                    type="button"
                    className="cl-palette-item"
                    data-active={index === active}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => choose(entry)}
                  >
                    <span className="material-symbols-outlined" aria-hidden="true">{entry.icon}</span>
                    <span className="cl-palette-item-copy">
                      <span className="cl-palette-item-label">{entry.label}</span>
                      {entry.hint && <span className="cl-palette-item-hint">{entry.hint}</span>}
                    </span>
                  </button>
                )
              })}
            </div>
          ))}
        </div>

        <div className="cl-palette-footer">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> to navigate
          </span>
          <span>
            <kbd>↵</kbd> to open
          </span>
        </div>
      </div>
    </div>
  )
}
