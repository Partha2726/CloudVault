import type { RecommendationStatus } from '../api/types'
import { RECOMMENDATION_STATUSES } from '../utils/vocab'

/** Square swatch + state, like ProcessingBadge. Stale is a hollow swatch: superseded, not failed. */
export function RecommendationStatusBadge({ status }: { status: RecommendationStatus }) {
  const meta = RECOMMENDATION_STATUSES.find((s) => s.id === status)
  const color = meta?.color ?? 'var(--color-ink-faint)'
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap text-[0.8125rem] ${status === 'STALE' ? 'text-ink-muted' : 'text-ink'}`}>
      <span
        aria-hidden
        className="h-2 w-2 shrink-0"
        style={meta?.hollow ? { boxShadow: `inset 0 0 0 1.5px ${color}` } : { background: color }}
      />
      {meta?.label ?? status}
    </span>
  )
}
