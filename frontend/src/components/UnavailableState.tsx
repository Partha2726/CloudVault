import type { ReactNode } from 'react'
import { FileX2 } from 'lucide-react'

/** Something exists in CloudVault's records but cannot be shown (e.g. a version gone from the store). */
export function UnavailableState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div role="status" className="record flex flex-col items-start gap-3 bg-alert-soft/40 p-6 sm:flex-row sm:gap-4">
      <FileX2 className="h-6 w-6 shrink-0 text-alert" strokeWidth={1.75} aria-hidden />
      <div>
        <p className="font-semibold text-ink">{title}</p>
        {children && <div className="mt-1 max-w-prose text-sm text-ink-muted">{children}</div>}
      </div>
    </div>
  )
}
