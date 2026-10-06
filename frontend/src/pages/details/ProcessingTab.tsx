import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCw } from 'lucide-react'
import { ApiError } from '../../api/client'
import { detailKeys, listProcessing, retryProcessing } from '../../api/documents'
import type { DocumentItem, ProcessingItem } from '../../api/types'
import { Button } from '../../components/Button'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { ProcessingBadge } from '../../components/ProcessingBadge'
import { useToast } from '../../components/useToast'
import { formatCount } from '../../utils/format'
import { refreshDocument } from '../../utils/invalidate'
import { jobErrorLabel } from '../../utils/vocab'
import { DetailPanel, ListSkeletonRows } from './Panel'

const message = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong.')

/**
 * Doc 06.5 Processing: GET /documents/{id}/processing and retry (W16). The background
 * worker does the work; this tab only shows its records. No polling: Refresh reloads them.
 */
export function ProcessingTab({ doc }: { doc: DocumentItem }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const jobs = useQuery({ queryKey: detailKeys.processing(doc.id), queryFn: () => listProcessing(doc.id) })
  const retry = useMutation({
    mutationFn: (job: ProcessingItem) => retryProcessing(doc.id, job.version_number),
    onSuccess: (_, job) => toast({ tone: 'success', message: `Processing of v${job.version_number} queued again.` }),
    onError: (e, job) => toast({ tone: 'error', message: `Retry of v${job.version_number}: ${message(e)}` }),
    onSettled: () => refreshDocument(queryClient, doc.id),
  })

  return (
    <DetailPanel
      title="Processing"
      aside={
        <Button size="sm" variant="quiet" onClick={() => queryClient.invalidateQueries({ queryKey: detailKeys.all(doc.id) })} pending={jobs.isFetching && !jobs.isPending} icon={<RotateCw className="h-4 w-4" aria-hidden />}>
          Refresh
        </Button>
      }
    >
      <p className="border-b border-rule px-5 py-3 text-[0.8125rem] text-ink-faint sm:px-6">
        Text extraction runs in CloudVault's background job queue after each upload or restore. A job still pending after
        10 minutes is stalled and can be retried.
      </p>
      {jobs.isPending && <ListSkeletonRows />}
      {jobs.isError && (
        <div className="p-5 sm:p-6">
          <ErrorState title="Processing status could not be loaded" message={message(jobs.error)} onRetry={() => jobs.refetch()} retrying={jobs.isFetching} />
        </div>
      )}
      {jobs.data && jobs.data.items.length === 0 && (
        <div className="p-5 sm:p-6">
          <EmptyState title="No processing records">No stored version of this document has a processing job.</EmptyState>
        </div>
      )}
      {jobs.data && jobs.data.items.length > 0 && (
        <ul className="divide-y divide-rule">
          {jobs.data.items.map((job) => {
            const retryable = job.status === 'FAILED' || job.stalled
            const reason = jobErrorLabel(job.error_code)
            return (
              <li key={job.version_number} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                    <span className="font-semibold text-ink">v{job.version_number}</span>
                    <ProcessingBadge processing={job} />
                    {job.page_count != null && <span data-figure className="text-ink-muted">{formatCount(job.page_count)} {job.page_count === 1 ? 'page' : 'pages'}</span>}
                    {job.word_count != null && <span data-figure className="text-ink-muted">{formatCount(job.word_count)} {job.word_count === 1 ? 'word' : 'words'}</span>}
                  </p>
                  {(reason || job.attempts > 0) && (
                    <p className="mt-1 text-[0.8125rem] text-ink-faint">
                      {reason}
                      {reason && job.attempts > 0 && ' · '}
                      {job.attempts > 0 && `Retried ${job.attempts} ${job.attempts === 1 ? 'time' : 'times'}`}
                    </p>
                  )}
                </div>
                {retryable && (
                  <Button size="sm" variant="secondary" onClick={() => retry.mutate(job)} pending={retry.isPending && retry.variables?.version_number === job.version_number} icon={<RotateCw className="h-4 w-4" aria-hidden />}>
                    Retry
                  </Button>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </DetailPanel>
  )
}
