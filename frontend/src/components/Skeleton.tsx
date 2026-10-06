type SkeletonProps = { className?: string }

/** A placeholder block in the record's ground tone; static, so it never competes with real data. */
export function Skeleton({ className = '' }: SkeletonProps) {
  return <div aria-hidden className={`rounded-[var(--radius-record)] bg-rule/70 ${className}`} />
}
