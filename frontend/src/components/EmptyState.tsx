import type { ReactNode } from 'react'
import { Archive } from 'lucide-react'

type EmptyStateProps = { title: string; children?: ReactNode }

export function EmptyState({ title, children }: EmptyStateProps) {
  return (
    <div className="record flex flex-col items-start gap-3 border-dashed p-8 sm:flex-row sm:items-center sm:gap-5">
      <Archive className="h-8 w-8 shrink-0 text-accent" strokeWidth={1.5} aria-hidden />
      <div>
        <p className="text-base font-semibold text-ink">{title}</p>
        {children && <div className="mt-1 max-w-prose text-sm text-ink-muted">{children}</div>}
      </div>
    </div>
  )
}
