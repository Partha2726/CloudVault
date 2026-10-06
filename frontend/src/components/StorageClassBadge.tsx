import type { StorageClass } from '../api/types'
import { STORAGE_CLASSES } from '../utils/vocab'

/** Square swatch + class code. The code is the S3 class name, never translated (AM-7). */
export function StorageClassBadge({ storageClass }: { storageClass: StorageClass }) {
  const meta = STORAGE_CLASSES.find((c) => c.id === storageClass)
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[0.8125rem] font-medium text-ink" title={meta?.description}>
      <span aria-hidden className="h-2 w-2 shrink-0" style={{ background: meta?.color ?? 'var(--color-ink-faint)' }} />
      {storageClass}
    </span>
  )
}
