import type { ReactNode } from 'react'

/** A record panel with a titled header row; the same treatment as the dashboard panels. */
export function DetailPanel({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section aria-label={title} className="record">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-5 py-3 sm:px-6">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        {aside}
      </header>
      {children}
    </section>
  )
}

export function ListSkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy="true" className="divide-y divide-rule">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="px-5 py-4 sm:px-6">
          <div className="h-4 w-full rounded-[var(--radius-record)] bg-rule/70" />
        </div>
      ))}
    </div>
  )
}
