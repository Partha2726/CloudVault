import { Database, NotebookPen } from 'lucide-react'

/** Labels where data comes from (doc 06.3): the simulated S3 store, or CloudVault's own records. */
export function SourceBadge({ source }: { source: 'S3' | 'CloudVault' }) {
  const s3 = source === 'S3'
  const Icon = s3 ? Database : NotebookPen
  return (
    <span className="inline-flex items-center gap-1.5 rounded-[var(--radius-record)] border border-rule-strong bg-panel px-2 py-0.5 text-xs font-semibold uppercase tracking-[0.08em] text-ink-muted">
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {s3 ? 'Live from simulated S3' : 'Recorded by CloudVault'}
    </span>
  )
}
