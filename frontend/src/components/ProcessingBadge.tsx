import type { ProcessingSummary } from '../api/types'
import { JOB_STATUSES } from '../utils/vocab'

/** Processing status from the durable job queue; a PENDING job older than 10 minutes reads "Stalled". */
export function ProcessingBadge({ processing }: { processing: ProcessingSummary | null }) {
  if (!processing) return <span className="text-[0.8125rem] text-ink-faint">None</span>
  const meta = JOB_STATUSES.find((s) => s.id === processing.status)
  const stalled = processing.stalled
  const label = stalled ? 'Stalled' : (meta?.label ?? processing.status)
  const color = stalled ? 'var(--color-alert)' : (meta?.color ?? 'var(--color-ink-faint)')
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap text-[0.8125rem] ${stalled || processing.status === 'FAILED' ? 'font-medium text-alert' : 'text-ink'}`}>
      <span aria-hidden className="h-2 w-2 shrink-0" style={{ background: color }} />
      {label}
    </span>
  )
}
