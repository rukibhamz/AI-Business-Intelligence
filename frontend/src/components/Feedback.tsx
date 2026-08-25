import type { ReactNode } from 'react'
import './Feedback.css'

type EmptyStateProps = {
  icon: string
  title: string
  body?: ReactNode
  action?: ReactNode
  tone?: 'neutral' | 'positive'
}

export function EmptyState({ icon, title, body, action, tone = 'neutral' }: EmptyStateProps) {
  return (
    <div className={`cl-empty cl-empty--${tone}`}>
      <div className="cl-empty-icon">
        <span className="material-symbols-outlined" aria-hidden="true">{icon}</span>
      </div>
      <h3 className="cl-empty-title">{title}</h3>
      {body && <div className="cl-empty-body">{body}</div>}
      {action && <div className="cl-empty-action">{action}</div>}
    </div>
  )
}

export function Skeleton({
  height = 16,
  width = '100%',
  radius = 'var(--cl-radius-sm)',
}: {
  height?: number | string
  width?: number | string
  radius?: string
}) {
  return (
    <span
      className="cl-skeleton"
      style={{ height, width, borderRadius: radius }}
      aria-hidden="true"
    />
  )
}

export function InlineMessage({
  tone,
  children,
  onDismiss,
}: {
  tone: 'error' | 'warning' | 'success' | 'info'
  children: ReactNode
  onDismiss?: () => void
}) {
  const icons = {
    error: 'error',
    warning: 'warning',
    success: 'check_circle',
    info: 'info',
  } as const
  return (
    <div className={`cl-inline cl-inline--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <span className="material-symbols-outlined" aria-hidden="true">{icons[tone]}</span>
      <div className="cl-inline-body">{children}</div>
      {onDismiss && (
        <button type="button" className="cl-inline-close" onClick={onDismiss} aria-label="Dismiss">
          <span className="material-symbols-outlined" aria-hidden="true">close</span>
        </button>
      )}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="cl-spinner-row" role="status">
      <span className="cl-spinner" aria-hidden="true" />
      {label && <span className="cl-spinner-label">{label}</span>}
    </div>
  )
}
