import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { detailKeys, listAccessLogs } from '../../api/documents'
import type { DocumentItem } from '../../api/types'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { Pagination } from '../../components/Pagination'
import { SourceBadge } from '../../components/SourceBadge'
import { formatDateTime } from '../../utils/vocab'
import { DetailPanel, ListSkeletonRows } from './Panel'

const EVENT_LABELS: Record<string, string> = { DOWNLOAD: 'Download link issued' }

/** Doc 06.5 Access: GET /documents/{id}/access-logs. [APP] CloudVault's own record, not S3's. */
export function AccessTab({ doc }: { doc: DocumentItem }) {
  const [page, setPage] = useState(1)
  const logs = useQuery({
    queryKey: detailKeys.access(doc.id, page),
    queryFn: () => listAccessLogs(doc.id, page),
    placeholderData: keepPreviousData,
  })
  return (
    <DetailPanel title="Access" aside={<SourceBadge source="CloudVault" />}>
      <p className="border-b border-rule px-5 py-3 text-[0.8125rem] text-ink-faint sm:px-6">
        Recorded by CloudVault each time it issues a download link. S3 does not report downloads back, so a link used
        elsewhere is not counted.
      </p>
      {logs.isPending && <ListSkeletonRows />}
      {logs.isError && (
        <div className="p-5 sm:p-6">
          <ErrorState
            title="Access history could not be loaded"
            message={logs.error instanceof ApiError ? logs.error.message : 'Something went wrong.'}
            onRetry={() => logs.refetch()}
            retrying={logs.isFetching}
          />
        </div>
      )}
      {logs.data && logs.data.items.length === 0 && (
        <div className="p-5 sm:p-6">
          <EmptyState title="No downloads recorded yet">Downloads of any version appear here, newest first.</EmptyState>
        </div>
      )}
      {logs.data && logs.data.items.length > 0 && (
        <div className={logs.isPlaceholderData ? 'opacity-60' : ''}>
          <ul className="divide-y divide-rule">
            {logs.data.items.map((log, i) => (
              <li key={`${log.accessed_at}-${i}`} className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 px-5 py-3 text-sm sm:px-6">
                <span className="text-ink">{EVENT_LABELS[log.event_type] ?? log.event_type}</span>
                <span data-figure className="flex gap-6 text-ink-muted">
                  <span>v{log.version_number}</span>
                  <span>{formatDateTime(log.accessed_at)}</span>
                </span>
              </li>
            ))}
          </ul>
          <Pagination page={logs.data.page} pageSize={logs.data.page_size} total={logs.data.total} onPage={setPage} />
        </div>
      )}
    </DetailPanel>
  )
}
