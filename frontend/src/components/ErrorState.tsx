import { RotateCw, TriangleAlert } from 'lucide-react'

type ErrorStateProps = {
  title: string
  message: string
  onRetry: () => void
  retrying?: boolean
}

export function ErrorState({ title, message, onRetry, retrying = false }: ErrorStateProps) {
  return (
    <div role="alert" className="record flex flex-col gap-4 p-6 sm:flex-row sm:items-start sm:justify-between">
      <div className="flex gap-3">
        <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-alert" aria-hidden />
        <div>
          <p className="font-semibold text-ink">{title}</p>
          <p className="mt-1 text-sm text-ink-muted">{message}</p>
        </div>
      </div>
      <button
        type="button"
        onClick={onRetry}
        disabled={retrying}
        className="inline-flex items-center justify-center gap-2 rounded-[var(--radius-record)] border border-rule-strong bg-panel px-3 py-1.5 text-sm font-medium text-ink hover:border-accent hover:bg-ground disabled:cursor-wait disabled:opacity-60"
      >
        <RotateCw className={`h-4 w-4 ${retrying ? 'animate-spin' : ''}`} aria-hidden />
        {retrying ? 'Retrying' : 'Retry'}
      </button>
    </div>
  )
}
