import { ChevronLeft, ChevronRight } from 'lucide-react'
import { formatCount } from '../utils/format'
import { Button } from './Button'

type PaginationProps = { page: number; pageSize: number; total: number; onPage: (page: number) => void }

export function Pagination({ page, pageSize, total, onPage }: PaginationProps) {
  if (total === 0) return null
  const first = (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-4 border-t border-rule px-5 py-3 sm:px-6">
      <p data-figure className="text-[0.8125rem] text-ink-muted">
        {formatCount(first)}–{formatCount(last)} of {formatCount(total)}
      </p>
      {pages > 1 && <div className="flex gap-2">
        <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)} icon={<ChevronLeft className="h-4 w-4" aria-hidden />}>
          Previous
        </Button>
        <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
          <ChevronRight className="h-4 w-4" aria-hidden />
        </Button>
      </div>}
    </nav>
  )
}
