import { useQuery } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { detailKeys, getS3Info, listVersions } from '../../api/documents'
import type { DocumentItem } from '../../api/types'
import { ErrorState } from '../../components/ErrorState'
import { FieldList } from '../../components/FieldList'
import { SourceBadge } from '../../components/SourceBadge'
import { StorageClassBadge } from '../../components/StorageClassBadge'
import { UnavailableState } from '../../components/UnavailableState'
import { formatBytes, formatCount } from '../../utils/format'
import { formatDateTime } from '../../utils/vocab'
import { DetailPanel, ListSkeletonRows } from './Panel'

function KeyValues({ values }: { values: Record<string, string> }) {
  const entries = Object.entries(values)
  if (entries.length === 0) return <span className="text-ink-faint">None</span>
  return (
    <table className="w-full max-w-xl table-fixed text-[0.8125rem]">
      <tbody className="divide-y divide-rule">
        {entries.map(([k, v]) => (
          <tr key={k}>
            <th scope="row" className="w-2/5 break-all py-1 pr-4 text-left align-top font-mono font-normal text-ink-muted">{k}</th>
            <td className="break-all py-1 font-mono text-ink">{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/**
 * Doc 06.5 S3 Inspector: GET /documents/{id}/s3-info (simulated HeadObject + tags, T12).
 * Shows exactly the fields the backend returns; every load is a fresh read of the store.
 */
export function InspectorTab({
  doc,
  version,
  onVersion,
}: {
  doc: DocumentItem
  version: number | undefined
  onVersion: (v: number | undefined) => void
}) {
  const versions = useQuery({ queryKey: detailKeys.versions(doc.id), queryFn: () => listVersions(doc.id) })
  const info = useQuery({
    queryKey: detailKeys.s3Info(doc.id, version),
    queryFn: () => getS3Info(doc.id, version),
    staleTime: 0,
    retry: false,
  })
  const err = info.error instanceof ApiError ? info.error : null

  const picker = versions.data && versions.data.items.length > 1 && (
    <label className="flex items-center gap-2 text-sm">
      <span className="caption">Version</span>
      <select
        value={version ?? ''}
        onChange={(e) => onVersion(e.target.value ? Number(e.target.value) : undefined)}
        className="rounded-[var(--radius-record)] border border-rule-strong bg-panel px-2 py-1 text-sm text-ink"
      >
        <option value="">Current</option>
        {versions.data.items.map((v) => (
          <option key={v.version_number} value={v.version_number}>
            v{v.version_number}
            {v.state === 'S3_MISSING' ? ' (missing)' : ''}
          </option>
        ))}
      </select>
    </label>
  )

  return (
    <DetailPanel
      title="S3 Inspector"
      aside={
        <span className="flex flex-wrap items-center gap-3">
          {picker}
          <SourceBadge source="S3" />
        </span>
      }
    >
      {info.isPending && <ListSkeletonRows rows={6} />}
      {err?.status === 410 && (
        <div className="p-5 sm:p-6">
          <UnavailableState title="This version is no longer in the simulated store">
            CloudVault still lists it, but the stored object is gone (for example, expired by a lifecycle rule). Its
            version is marked missing; nothing was recreated.
          </UnavailableState>
        </div>
      )}
      {err?.status === 404 && (
        <div className="p-5 sm:p-6">
          <UnavailableState title="Version not found">
            This document has no v{version}. Choose a version from the list.
          </UnavailableState>
        </div>
      )}
      {info.isError && err?.status !== 410 && err?.status !== 404 && (
        <div className="p-5 sm:p-6">
          <ErrorState
            title="S3 unavailable, retry"
            message={err ? err.message : 'The simulated store could not be read.'}
            onRetry={() => info.refetch()}
            retrying={info.isFetching}
          />
        </div>
      )}
      {info.data && (
        <FieldList
          fields={[
            { label: 'Bucket', value: info.data.bucket, mono: true },
            { label: 'Key', value: info.data.key, mono: true },
            { label: 'Version ID', value: info.data.version_id, mono: true },
            { label: 'ETag', value: info.data.etag, mono: true },
            {
              label: 'Content length',
              value: (
                <span data-figure>
                  {formatBytes(info.data.content_length)}{' '}
                  <span className="text-ink-muted">({formatCount(info.data.content_length)} bytes)</span>
                </span>
              ),
            },
            { label: 'Content type', value: info.data.content_type, mono: true },
            { label: 'Last modified', value: formatDateTime(info.data.last_modified) },
            { label: 'Storage class', value: <StorageClassBadge storageClass={info.data.storage_class} /> },
            { label: 'Metadata', value: <KeyValues values={info.data.metadata} /> },
            { label: 'Tags', value: <KeyValues values={info.data.tags} /> },
            { label: 'Source', value: info.data.source, mono: true },
          ]}
        />
      )}
    </DetailPanel>
  )
}
