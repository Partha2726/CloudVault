import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Link } from 'react-router-dom'
import type { DashboardSummary, JobStatus } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { formatBytes, formatCount, formatShare } from '../utils/format'
import { JOB_STATUSES, STORAGE_CLASSES } from '../utils/vocab'

const CLASSES = STORAGE_CLASSES
const JOBS = JOB_STATUSES

export function DashboardPage() {
  const summary = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api<DashboardSummary>('/dashboard/summary'),
  })

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-[2.125rem] font-semibold leading-tight tracking-tight text-ink">Dashboard</h1>
        <p className="mt-1.5 text-[0.9375rem] text-ink-muted">
          Holdings in your simulated S3 bucket, as recorded by CloudVault.
        </p>
      </div>

      {summary.isPending && <DashboardSkeleton />}
      {summary.isError && (
        <ErrorState
          title="The dashboard could not be loaded"
          message={summary.error.message}
          onRetry={() => summary.refetch()}
          retrying={summary.isFetching}
        />
      )}
      {summary.data && summary.data.document_count === 0 && (
        <EmptyState title="Upload your first document">
          Your simulated S3 bucket is empty. Uploaded documents appear here with their storage class, versions and
          processing status.{' '}
          <Link to="/documents" className="font-medium text-accent-strong underline underline-offset-4">
            Go to Documents to upload
          </Link>
        </EmptyState>
      )}
      {summary.data && summary.data.document_count > 0 && <Holdings data={summary.data} />}
    </div>
  )
}

function Holdings({ data }: { data: DashboardSummary }) {
  return (
    <>
      <section aria-label="Totals" className="record overflow-hidden">
        <dl className="grid grid-cols-2 gap-px bg-rule lg:grid-cols-4">
          <Figure label="Documents" value={formatCount(data.document_count)} note="Active in the bucket" to="/documents" />
          <Figure label="Current storage" value={formatBytes(data.current_bytes)} note="Latest version of each document" />
          <Figure
            label="Total with versions"
            value={formatBytes(data.total_bytes_all_versions)}
            note="Every stored version"
          />
          <Figure label="Downloads, 30 days" value={formatCount(data.accesses_30d)} note="Recorded by CloudVault" />
        </dl>
      </section>

      <div className="grid gap-6 lg:grid-cols-3 lg:items-start">
        <StorageByClass data={data} />
        <div className="flex flex-col gap-6">
          <Processing jobs={data.jobs_by_status} />
          <Recommendations open={data.open_recommendations} />
        </div>
      </div>
    </>
  )
}

function Figure({ label, value, note, to }: { label: string; value: string; note: string; to?: string }) {
  return (
    <div className="relative bg-panel px-5 py-4 hover:[&:has(a)]:bg-ground sm:px-6 sm:py-5">
      <dt className="caption">
        {to ? (
          <Link to={to} className="after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:outline-accent-strong">
            {label}
          </Link>
        ) : (
          label
        )}
      </dt>
      <dd data-figure className="mt-2 whitespace-nowrap text-[1.75rem] font-semibold leading-none tracking-tight text-ink">
        {value}
      </dd>
      <dd className="mt-2 text-[0.8125rem] text-ink-faint">{note}</dd>
    </div>
  )
}

function Panel({ title, aside, children, className = '' }: {
  title: string
  aside?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <section aria-label={title} className={`record ${className}`}>
      <header className="flex items-baseline justify-between gap-4 border-b border-rule px-5 py-3 sm:px-6">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        {aside && <span className="caption">{aside}</span>}
      </header>
      {children}
    </section>
  )
}

function StorageByClass({ data }: { data: DashboardSummary }) {
  const total = data.total_bytes_all_versions
  const rows = CLASSES.map((c) => ({ ...c, bytes: data.bytes_by_class[c.id] ?? 0 }))

  // The container list: one ruled row per simulated class. Each bar is drawn at its exact
  // share of all stored bytes, so every row reads on the same scale.
  return (
    <Panel title="Storage by class" aside="Simulated S3" className="lg:col-span-2">
      <table className="w-full text-sm">
        <caption className="sr-only">Stored bytes by simulated storage class, as a share of all stored bytes</caption>
        <thead className="sr-only">
          <tr>
            <th scope="col">Class</th>
            <th scope="col">Share of stored bytes</th>
            <th scope="col">Stored</th>
            <th scope="col">Share</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-rule">
          {rows.map((r) => {
            const share = total > 0 ? r.bytes / total : 0
            return (
              <tr key={r.id} className="grid grid-cols-[1fr_auto_auto] items-center gap-x-4 gap-y-2.5 px-5 py-4 sm:grid-cols-[13rem_1fr_6rem_3.5rem] sm:gap-x-6 sm:px-6">
                <th scope="row" className="text-left font-normal">
                  <span className="flex items-center gap-2 font-semibold text-ink">
                    <span aria-hidden className="h-2.5 w-2.5 shrink-0" style={{ background: r.color }} />
                    {r.id}
                  </span>
                  <span className="mt-0.5 block pl-[1.125rem] text-[0.8125rem] text-ink-faint">{r.description}</span>
                </th>
                <td className="col-span-3 row-start-2 sm:col-span-1 sm:row-start-auto">
                  <div className="h-3 bg-ground" role="presentation">
                    <div className="h-full" style={{ width: `${share * 100}%`, background: r.color }} />
                  </div>
                </td>
                <td data-figure className="whitespace-nowrap text-right font-medium text-ink">
                  {formatBytes(r.bytes)}
                </td>
                <td data-figure className="whitespace-nowrap text-right text-ink-muted">
                  {formatShare(r.bytes, total)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Panel>
  )
}

function Processing({ jobs }: { jobs: Record<JobStatus, number> }) {
  const total = JOBS.reduce((sum, j) => sum + (jobs[j.id] ?? 0), 0)
  return (
    <Panel title="Processing" aside={`${formatCount(total)} jobs`}>
      <ul className="divide-y divide-rule">
        {JOBS.map((j) => {
          const count = jobs[j.id] ?? 0
          const alarming = j.id === 'FAILED' && count > 0
          return (
            <li key={j.id} className="flex items-center justify-between px-5 py-2.5 text-sm sm:px-6">
              <span className="inline-flex items-center gap-2 text-ink">
                <span aria-hidden className="h-2.5 w-2.5" style={{ background: j.color }} />
                {j.label}
              </span>
              <span data-figure className={alarming ? 'font-semibold text-alert' : 'text-ink'}>
                {formatCount(count)}
              </span>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}

function Recommendations({ open }: { open: number }) {
  return (
    <Panel title="Storage recommendations">
      <div className="px-5 py-4 sm:px-6">
        <p className="flex items-baseline gap-2">
          <span data-figure className="text-[1.75rem] font-semibold leading-none tracking-tight text-ink">
            {formatCount(open)}
          </span>
          <span className="text-sm text-ink-muted">open</span>
        </p>
        <p className="mt-3 text-[0.8125rem] leading-relaxed text-ink-faint">
          From CloudVault&apos;s heuristic over recorded access history, not AWS Intelligent-Tiering.
        </p>
        <Link
          to="/optimization"
          className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-accent-strong underline underline-offset-4"
        >
          {open > 0 ? 'Review in Optimization' : 'Go to Optimization'}
        </Link>
      </div>
    </Panel>
  )
}

function SkeletonPanel({ rows, className = '' }: { rows: number; className?: string }) {
  return (
    <div className={`record ${className}`}>
      <div className="border-b border-rule px-6 py-3.5">
        <Skeleton className="h-4 w-32" />
      </div>
      <div className="divide-y divide-rule">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="px-6 py-4">
            <Skeleton className="h-4 w-full" />
          </div>
        ))}
      </div>
    </div>
  )
}

/** Mirrors the loaded layout (strip, container list, two stacked panels) so nothing shifts on arrival. */
function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-8" aria-busy="true" aria-label="Loading dashboard">
      <div className="record grid grid-cols-2 gap-px overflow-hidden bg-rule lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="bg-panel px-5 py-4 sm:px-6 sm:py-5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-7 w-20" />
            <Skeleton className="mt-3 h-3 w-32" />
          </div>
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <SkeletonPanel rows={3} className="lg:col-span-2" />
        <div className="flex flex-col gap-6">
          <SkeletonPanel rows={4} />
          <SkeletonPanel rows={2} />
        </div>
      </div>
    </div>
  )
}
