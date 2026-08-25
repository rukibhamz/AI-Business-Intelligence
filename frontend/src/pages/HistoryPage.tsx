import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type ConversationSummary } from '../api/client'
import { EmptyState, InlineMessage, Skeleton } from '../components/Feedback'
import './HistoryPage.css'

type Props = {
  onOpenConversation: (id: string) => void
  onNewChat: () => void
}

type DayGroup = { label: string; items: ConversationSummary[] }

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function relativeWhen(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const mins = Math.floor((Date.now() - date.getTime()) / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24 && startOfDay(date) === startOfDay(new Date())) {
    return hours === 1 ? '1 hour ago' : `${hours} hours ago`
  }
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function groupByDay(items: ConversationSummary[]): DayGroup[] {
  const today = startOfDay(new Date())
  const buckets: Record<string, ConversationSummary[]> = {
    Today: [],
    Yesterday: [],
    'Previous 7 days': [],
    Earlier: [],
  }

  for (const item of items) {
    const t = startOfDay(new Date(item.updated_at))
    if (t === today) buckets.Today.push(item)
    else if (t === today - 86400000) buckets.Yesterday.push(item)
    else if (t >= today - 7 * 86400000) buckets['Previous 7 days'].push(item)
    else buckets.Earlier.push(item)
  }

  return Object.entries(buckets)
    .filter(([, group]) => group.length > 0)
    .map(([label, group]) => ({ label, items: group }))
}

export function HistoryPage({ onOpenConversation, onNewChat }: Props) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      setConversations(await api.listConversations())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load your chats')
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    void load().finally(() => setLoading(false))
  }, [load])

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase()
    if (!needle) return conversations
    return conversations.filter((c) =>
      `${c.title} ${c.last_question ?? ''} ${c.last_answer ?? ''}`
        .toLowerCase()
        .includes(needle),
    )
  }, [conversations, search])

  const groups = useMemo(() => groupByDay(filtered), [filtered])

  async function handleRename(conversation: ConversationSummary) {
    const next = window.prompt('Rename this chat', conversation.title)
    if (next == null) return
    const trimmed = next.trim()
    if (!trimmed || trimmed === conversation.title) return
    setBusyId(conversation.id)
    try {
      const updated = await api.renameConversation(conversation.id, trimmed)
      setConversations((prev) =>
        prev.map((c) => (c.id === updated.id ? { ...c, title: updated.title } : c)),
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Rename failed')
    } finally {
      setBusyId(null)
    }
  }

  async function handleDelete(conversation: ConversationSummary) {
    const count = conversation.message_count
    const ok = window.confirm(
      `Delete "${conversation.title}"?\n\nThis permanently removes ${count} question${
        count === 1 ? '' : 's'
      } and their results. It cannot be undone.`,
    )
    if (!ok) return
    setBusyId(conversation.id)
    try {
      await api.deleteConversation(conversation.id)
      setConversations((prev) => prev.filter((c) => c.id !== conversation.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="chats">
      <header className="chats-header">
        <div>
          <h1 className="chats-title">History</h1>
          <p className="chats-sub">
            {loading
              ? 'Loading your chats…'
              : `${conversations.length} chat${conversations.length === 1 ? '' : 's'}`}
          </p>
        </div>
        <button type="button" className="chats-new" onClick={onNewChat}>
          <span className="material-symbols-outlined" aria-hidden="true">
            add_comment
          </span>
          New chat
        </button>
      </header>

      {error && (
        <InlineMessage tone="error" onDismiss={() => setError(null)}>
          {error}
        </InlineMessage>
      )}

      {conversations.length > 0 && (
        <label className="chats-search">
          <span className="material-symbols-outlined" aria-hidden="true">
            search
          </span>
          <input
            type="search"
            value={search}
            placeholder="Search your chats…"
            aria-label="Search chats"
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      )}

      {loading && (
        <div className="chats-list">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="chat-card">
              <Skeleton width="45%" height={16} />
              <Skeleton width="80%" height={13} />
            </div>
          ))}
        </div>
      )}

      {!loading && conversations.length === 0 && (
        <EmptyState
          icon="forum"
          title="No chats yet"
          body={
            <p>
              Questions you ask are saved here as chats, with the SQL that ran and the rows it
              returned. Pick one up again any time.
            </p>
          }
          action={
            <button type="button" className="chats-new" onClick={onNewChat}>
              <span className="material-symbols-outlined" aria-hidden="true">
                add_comment
              </span>
              Start a chat
            </button>
          }
        />
      )}

      {!loading && conversations.length > 0 && filtered.length === 0 && (
        <EmptyState
          icon="search_off"
          title="No chats match that search"
          body={<p>Try a different word, or clear the search to see everything.</p>}
          action={
            <button type="button" className="chats-clear" onClick={() => setSearch('')}>
              Clear search
            </button>
          }
        />
      )}

      {groups.map((group) => (
        <section key={group.label} className="chats-group">
          <h2 className="chats-group-label">
            {group.label}
            <span className="chats-group-count">{group.items.length}</span>
          </h2>

          <div className="chats-list">
            {group.items.map((conversation) => (
              <article
                key={conversation.id}
                className={`chat-card${busyId === conversation.id ? ' is-busy' : ''}`}
              >
                <button
                  type="button"
                  className="chat-card-open"
                  onClick={() => onOpenConversation(conversation.id)}
                >
                  <span className="chat-card-icon" aria-hidden="true">
                    <span className="material-symbols-outlined">forum</span>
                  </span>
                  <span className="chat-card-copy">
                    <span className="chat-card-title">{conversation.title}</span>
                    {conversation.last_answer && (
                      <span className="chat-card-preview">{conversation.last_answer}</span>
                    )}
                    <span className="chat-card-meta">
                      {conversation.message_count} message
                      {conversation.message_count === 1 ? '' : 's'}
                      <span className="chat-card-dot" aria-hidden="true" />
                      {relativeWhen(conversation.updated_at)}
                    </span>
                  </span>
                </button>

                <div className="chat-card-actions">
                  <button
                    type="button"
                    className="chat-action"
                    aria-label={`Rename ${conversation.title}`}
                    title="Rename"
                    disabled={busyId === conversation.id}
                    onClick={() => void handleRename(conversation)}
                  >
                    <span className="material-symbols-outlined" aria-hidden="true">
                      edit
                    </span>
                  </button>
                  <button
                    type="button"
                    className="chat-action chat-action--danger"
                    aria-label={`Delete ${conversation.title}`}
                    title="Delete"
                    disabled={busyId === conversation.id}
                    onClick={() => void handleDelete(conversation)}
                  >
                    <span className="material-symbols-outlined" aria-hidden="true">
                      delete
                    </span>
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
