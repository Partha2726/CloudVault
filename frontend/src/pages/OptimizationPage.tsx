import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, RotateCw } from 'lucide-react'
import { ApiError } from '../api/client'
import {
  applyRecommendation,
  dismissRecommendation,
  listRecommendations,
  recommendationKeys,
  refreshRecommendations,
} from '../api/recommendations'
import type { Recommendation, RecommendationStatus } from '../api/types'
import { Button } from '../components/Button'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { RecommendationStatusBadge } from '../components/RecommendationStatusBadge'
import { Skeleton } from '../components/Skeleton'
import { StorageClassBadge } from '../components/StorageClassBadge'
import { Tabs } from '../components/Tabs'
import { useToast } from '../components/useToast'
import { formatBytes, formatCount } from '../utils/format'
import { RECOMMENDATION_STATUSES, SIGNAL_LABELS, formatDateTime } from '../utils/vocab'

const message = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong.')

const EMPTY: Record<RecommendationStatus, { title: string; body: string }> = {
  OPEN: {
    title: 'No recommendations; files are new or already optimal',
    body: 'Refresh re-runs CloudVault’s heuristic over the current version of every active document.',
  },
  APPLIED: { title: 'Nothing applied yet', body: 'Recommendations you apply are kept here with the class change they made.' },
  DISMISSED: { title: 'Nothing dismissed', body: 'Recommendations you dismiss are kept here; they never change storage.' },
  STALE: {
    title: 'No stale recommendations',
    body: 'A recommendation goes stale when a refresh replaces it or the document no longer matches it.',
  },
}

// What each non-open state means, shown above its list so the outcome never reads as a failure.
const STATE_NOTES: Partial<Record<RecommendationStatus, string>> = {
  APPLIED: 'Applied: the version was copied to the recommended class in the simulated bucket and its old copy removed.',
  DISMISSED: 'Dismissed: you chose to keep the current class. Nothing in storage changed.',
  STALE:
    'Stale: replaced by a later refresh, or the document changed (for example a new version, or a move to the trash) so CloudVault’s heuristic no longer gives this result. Stale recommendations cannot be applied; refresh for current ones.',
}

function signalValue(unit: 'days' | 'downloads' | 'bytes', n: number) {
  if (unit === 'bytes') return formatBytes(n)
  if (unit === 'days') return `${formatCount(n)} ${n === 1 ? 'day' : 'days'}`
  return formatCount(n)
}

function Signals({ signals }: { signals: Record<string, number> }) {
  const present = SIGNAL_LABELS.filter((s) => typeof signals[s.key] === 'number')
  if (present.length === 0) return null
  return (
    <dl data-figure className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[0.8125rem]">
      {present.map((s) => (
        <div key={s.key} className="flex gap-1.5">
          <dt className="text-ink-faint">{s.label}</dt>
          <dd className="text-ink-muted">{signalValue(s.unit, signals[s.key])}</dd>
        </div>
      ))}
    </dl>
  )
}

function Change({ rec, nowrap = false }: { rec: Recommendation; nowrap?: boolean }) {
  const settled = rec.status === 'STALE' || rec.status === 'DISMISSED'
  return (
    <span className={`inline-flex items-center gap-x-2 gap-y-1 ${nowrap ? 'whitespace-nowrap' : 'flex-wrap'} ${settled ? 'opacity-60' : ''}`}>
      <StorageClassBadge storageClass={rec.current_class} />
      <ArrowRight className="h-3.5 w-3.5 text-ink-faint" aria-label="to" />
      <StorageClassBadge storageClass={rec.recommended_class} />
    </span>
  )
}

function DocumentCell({ rec }: { rec: Recommendation }) {
  return (
    <>
      <Link to={`/documents/${rec.document_id}`} className="break-words font-medium text-ink underline-offset-2 hover:underline">
        {rec.display_name}
      </Link>
      <span className="ml-2 text-[0.8125rem] text-ink-muted">v{rec.version_number}</span>
    </>
  )
}

/** Doc 06.5 Optimization: CloudVault's heuristic (T13), served and applied by the T14 endpoints. */
export function OptimizationPage() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const status: RecommendationStatus =
    RECOMMENDATION_STATUSES.find((s) => s.id.toLowerCase() === params.get('status'))?.id ?? 'OPEN'
  const list = useQuery({ queryKey: recommendationKeys.list(status), queryFn: () => listRecommendations(status) })
  const [applying, setApplying] = useState<Recommendation | null>(null)

  // Apply changes a document's storage class, so its views and the dashboard refetch too (doc 06.4).
  const refreshAfter = (documentId?: string) =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: recommendationKeys.all }),
      queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
      queryClient.invalidateQueries({ queryKey: ['documents'] }),
      documentId ? queryClient.invalidateQueries({ queryKey: ['document', documentId] }) : undefined,
    ])

  const refresh = useMutation({
    mutationFn: refreshRecommendations,
    onSuccess: ({ items }) => {
      toast({
        tone: 'success',
        message:
          items.length === 0
            ? 'Refreshed. No recommendations; files are new or already optimal.'
            : `Refreshed. CloudVault’s heuristic has ${items.length} open ${items.length === 1 ? 'recommendation' : 'recommendations'}.`,
      })
      setParams({}, { replace: true })
    },
    onError: (e) => toast({ tone: 'error', message: `Refresh failed: ${message(e)}` }),
    onSettled: () => refreshAfter(),
  })

  const apply = useMutation({
    mutationFn: (rec: Recommendation) => applyRecommendation(rec.id),
    onSuccess: (rec) =>
      toast({
        tone: 'success',
        message: `Storage class changed to ${rec.recommended_class} for ${rec.display_name} v${rec.version_number}.`,
      }),
    onError: (e, rec) => toast({ tone: 'error', message: `${rec.display_name} v${rec.version_number}: ${message(e)}` }),
    onSettled: (_, __, rec) => {
      setApplying(null)
      return refreshAfter(rec.document_id)
    },
  })

  const dismiss = useMutation({
    mutationFn: (rec: Recommendation) => dismissRecommendation(rec.id),
    onSuccess: (rec) =>
      toast({ message: `Dismissed for ${rec.display_name} v${rec.version_number}; it stays in ${rec.current_class}.` }),
    onError: (e, rec) => toast({ tone: 'error', message: `${rec.display_name} v${rec.version_number}: ${message(e)}` }),
    onSettled: () => refreshAfter(),
  })

  const busy = (rec: Recommendation) =>
    (apply.isPending && apply.variables?.id === rec.id) || (dismiss.isPending && dismiss.variables?.id === rec.id)

  const outcome = (rec: Recommendation) =>
    rec.status === 'OPEN' ? (
      <span className="flex justify-end gap-2">
        <Button size="sm" variant="secondary" onClick={() => setApplying(rec)} disabled={busy(rec)}>
          Apply
        </Button>
        <Button size="sm" variant="quiet" onClick={() => dismiss.mutate(rec)} pending={dismiss.isPending && dismiss.variables?.id === rec.id} disabled={busy(rec)}>
          Dismiss
        </Button>
      </span>
    ) : (
      <RecommendationStatusBadge status={rec.status} />
    )

  const items = list.data?.items ?? []

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[2.125rem] font-semibold leading-tight tracking-tight text-ink">Optimization</h1>
          <p className="mt-1.5 text-[0.9375rem] text-ink-muted">
            Storage-class recommendations for the current version of each active document.
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => refresh.mutate()}
          pending={refresh.isPending}
          icon={<RotateCw className="h-4 w-4" aria-hidden />}
          className="self-start sm:self-auto"
        >
          Refresh
        </Button>
      </div>

      <section aria-label="About these recommendations" className="record bg-panel px-5 py-4 sm:px-6">
        <h2 className="text-base font-semibold text-ink">CloudVault&apos;s heuristic, not AWS Intelligent-Tiering</h2>
        <p className="mt-1.5 max-w-[72ch] text-sm leading-relaxed text-ink-muted">
          Fixed rules look at each current version&apos;s age, size, time in its class and the downloads recorded by
          CloudVault, then suggest a simulated storage class. Nothing changes until you apply a recommendation. No
          cost or savings estimate is shown.
        </p>
      </section>

      <Tabs
        label="Recommendation state"
        tabs={RECOMMENDATION_STATUSES.map((s) => ({ id: s.id, label: s.tab }))}
        active={status}
        onChange={(s) => setParams(s === 'OPEN' ? {} : { status: s.toLowerCase() }, { replace: true })}
      />

      <section aria-label={`${RECOMMENDATION_STATUSES.find((s) => s.id === status)?.tab} recommendations`} className="flex flex-col gap-4">
        {STATE_NOTES[status] && <p className="max-w-[72ch] text-sm text-ink-muted">{STATE_NOTES[status]}</p>}

        {list.isPending && (
          <div className="record divide-y divide-rule" aria-busy="true">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex flex-col gap-2 px-5 py-4 sm:px-6">
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            ))}
          </div>
        )}
        {list.isError && (
          <ErrorState
            title="Recommendations could not be loaded"
            message={message(list.error)}
            onRetry={() => list.refetch()}
            retrying={list.isFetching}
          />
        )}
        {list.data && items.length === 0 && <EmptyState title={EMPTY[status].title}>{EMPTY[status].body}</EmptyState>}
        {items.length > 0 && (
          <div className={`record ${list.isFetching && !list.isPending ? 'opacity-70' : ''}`}>
            <table className="hidden w-full text-sm lg:table">
              <caption className="sr-only">
                {RECOMMENDATION_STATUSES.find((s) => s.id === status)?.tab} recommendations, newest first
              </caption>
              <thead>
                <tr className="border-b border-rule text-left">
                  <th scope="col" className="caption px-6 py-2.5 font-semibold">Document</th>
                  <th scope="col" className="caption px-3 py-2.5 font-semibold">Change</th>
                  <th scope="col" className="caption px-3 py-2.5 font-semibold">Reason and signals</th>
                  <th scope="col" className="caption px-3 py-2.5 font-semibold">Generated</th>
                  <th scope="col" className="caption px-6 py-2.5 text-right font-semibold">
                    {status === 'OPEN' ? <span className="sr-only">Actions</span> : 'State'}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {items.map((rec) => (
                  <tr key={rec.id} className="align-top">
                    <td className="max-w-[14rem] px-6 py-3.5"><DocumentCell rec={rec} /></td>
                    <td className="px-3 py-3.5"><Change rec={rec} nowrap /></td>
                    <td className="px-3 py-3.5">
                      <p className={rec.status === 'OPEN' ? 'text-ink' : 'text-ink-muted'}>{rec.reason}</p>
                      <Signals signals={rec.signals} />
                    </td>
                    <td className="whitespace-nowrap px-3 py-3.5 text-ink-muted">{formatDateTime(rec.created_at)}</td>
                    <td className="px-6 py-3 text-right">{outcome(rec)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="divide-y divide-rule lg:hidden" aria-label="Recommendations">
              {items.map((rec) => (
                <li key={rec.id} className="flex flex-col gap-2.5 px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0"><DocumentCell rec={rec} /></p>
                    {rec.status !== 'OPEN' && <RecommendationStatusBadge status={rec.status} />}
                  </div>
                  <Change rec={rec} />
                  <div>
                    <p className={`text-sm ${rec.status === 'OPEN' ? 'text-ink' : 'text-ink-muted'}`}>{rec.reason}</p>
                    <Signals signals={rec.signals} />
                    <p className="mt-1 text-[0.8125rem] text-ink-faint">Generated {formatDateTime(rec.created_at)}</p>
                  </div>
                  {rec.status === 'OPEN' && <div className="flex justify-start">{outcome(rec)}</div>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <ConfirmDialog
        open={applying !== null}
        title="Change the storage class?"
        confirmLabel={`Change to ${applying?.recommended_class ?? ''}`}
        pending={apply.isPending}
        onConfirm={() => applying && apply.mutate(applying)}
        onCancel={() => setApplying(null)}
      >
        {applying && (
          <div className="flex flex-col gap-3">
            <p>
              <span className="font-medium text-ink">{applying.display_name}</span> v{applying.version_number}:{' '}
              {applying.current_class} to {applying.recommended_class}.
            </p>
            <p>
              Copies the object to the new class and removes the old version. In the simulated bucket the copy gets a
              new S3 version ID; CloudVault still calls it v{applying.version_number}.
            </p>
            <p>
              CloudVault re-checks the document first. If its heuristic no longer gives this result, nothing changes
              and the recommendation is marked stale.
            </p>
          </div>
        )}
      </ConfirmDialog>
    </div>
  )
}
