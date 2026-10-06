import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, History, ScanSearch } from 'lucide-react'
import { ApiError } from '../../api/client'
import { detailKeys, listVersions, restoreVersion } from '../../api/documents'
import type { DocumentItem, VersionItem } from '../../api/types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { RowMenu, type RowAction } from '../../components/RowMenu'
import { StorageClassBadge } from '../../components/StorageClassBadge'
import { useToast } from '../../components/useToast'
import { startDownload } from '../../utils/download'
import { formatBytes } from '../../utils/format'
import { refreshDocument } from '../../utils/invalidate'
import { formatDateTime } from '../../utils/vocab'
import { DetailPanel, ListSkeletonRows } from './Panel'

const message = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong.')

function Origin({ v }: { v: VersionItem }) {
  return <>{v.origin === 'RESTORE' ? `Restored from v${v.restored_from_version}` : 'Upload'}</>
}

function State({ v }: { v: VersionItem }) {
  return v.state === 'S3_MISSING' ? (
    <span className="font-medium text-alert">Missing from storage</span>
  ) : (
    <span className="text-ink-muted">Stored</span>
  )
}

/** Doc 06.5 Versions: GET /documents/{id}/versions, newest first; Restore creates a new version (W6). */
export function VersionsTab({ doc, onInspect }: { doc: DocumentItem; onInspect: (version: number) => void }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const versions = useQuery({ queryKey: detailKeys.versions(doc.id), queryFn: () => listVersions(doc.id) })
  const [restoring, setRestoring] = useState<VersionItem | null>(null)
  const active = doc.status === 'ACTIVE'

  const restore = useMutation({
    mutationFn: (v: VersionItem) => restoreVersion(doc.id, v.version_number),
    onSuccess: (created, v) => toast({ tone: 'success', message: `Restored v${v.version_number} as v${created.version_number}.` }),
    onError: (e, v) => toast({ tone: 'error', message: `Restore of v${v.version_number}: ${message(e)}` }),
    onSettled: () => {
      setRestoring(null)
      return refreshDocument(queryClient, doc.id)
    },
  })

  const download = async (v: VersionItem) => {
    try {
      await startDownload(queryClient, doc.id, v.version_number)
    } catch (e) {
      toast({ tone: 'error', message: `Download of v${v.version_number}: ${message(e)}` })
    }
  }

  const actionsFor = (v: VersionItem): RowAction[] => {
    const stored = v.state === 'ACTIVE'
    return [
      { label: 'Download this version', icon: <Download className="h-4 w-4" aria-hidden />, disabled: !stored || !active, onSelect: () => download(v) },
      { label: 'Inspect in S3', icon: <ScanSearch className="h-4 w-4" aria-hidden />, disabled: !stored, onSelect: () => onInspect(v.version_number) },
      ...(v.is_current
        ? []
        : [{ label: 'Restore as new version', icon: <History className="h-4 w-4" aria-hidden />, disabled: !stored || !active, onSelect: () => setRestoring(v) }]),
    ]
  }

  const aside = !active ? <span className="caption">Restore from the trash to download or restore versions</span> : undefined

  return (
    <DetailPanel title="Versions" aside={aside}>
      {versions.isPending && <ListSkeletonRows />}
      {versions.isError && (
        <div className="p-5 sm:p-6">
          <ErrorState title="Versions could not be loaded" message={message(versions.error)} onRetry={() => versions.refetch()} retrying={versions.isFetching} />
        </div>
      )}
      {versions.data && versions.data.items.length === 0 && (
        <div className="p-5 sm:p-6">
          <EmptyState title="No stored versions">Every stored version of this document is gone from the simulated store.</EmptyState>
        </div>
      )}
      {versions.data && versions.data.items.length > 0 && (
        <>
          <table className="hidden w-full text-sm md:table">
            <caption className="sr-only">Versions of {doc.display_name}, newest first</caption>
            <thead>
              <tr className="border-b border-rule text-left">
                <th scope="col" className="caption px-6 py-2.5 font-semibold">Version</th>
                <th scope="col" className="caption px-3 py-2.5 font-semibold">Origin</th>
                <th scope="col" className="caption px-3 py-2.5 text-right font-semibold">Size</th>
                <th scope="col" className="caption px-3 py-2.5 font-semibold">Class</th>
                <th scope="col" className="caption px-3 py-2.5 font-semibold">State</th>
                <th scope="col" className="caption px-3 py-2.5 font-semibold">Created</th>
                <th scope="col" className="w-12 px-4 py-2.5"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {versions.data.items.map((v) => (
                <tr key={v.version_number} className={v.state === 'S3_MISSING' ? 'bg-alert-soft/30' : undefined}>
                  <th scope="row" className="px-6 py-3 text-left font-semibold text-ink">
                    v{v.version_number}
                    {v.is_current && <span className="caption ml-2 text-accent-strong">Current</span>}
                  </th>
                  <td className="px-3 py-3 text-ink-muted"><Origin v={v} /></td>
                  <td data-figure className="whitespace-nowrap px-3 py-3 text-right">{formatBytes(v.size_bytes)}</td>
                  <td className="px-3 py-3"><StorageClassBadge storageClass={v.storage_class} /></td>
                  <td className="px-3 py-3"><State v={v} /></td>
                  <td className="whitespace-nowrap px-3 py-3 text-ink-muted">{formatDateTime(v.created_at)}</td>
                  <td className="px-4 py-2 text-right"><RowMenu label={`Actions for v${v.version_number}`} actions={actionsFor(v)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="divide-y divide-rule md:hidden" aria-label={`Versions of ${doc.display_name}`}>
            {versions.data.items.map((v) => (
              <li key={v.version_number} className="flex items-start gap-3 px-5 py-3.5">
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-ink">
                    v{v.version_number}
                    {v.is_current && <span className="caption ml-2 text-accent-strong">Current</span>}
                  </p>
                  <p data-figure className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[0.8125rem] text-ink-muted">
                    <span><Origin v={v} /></span>
                    <span>{formatBytes(v.size_bytes)}</span>
                    <span>{formatDateTime(v.created_at)}</span>
                  </p>
                  <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem]">
                    <StorageClassBadge storageClass={v.storage_class} />
                    <State v={v} />
                  </p>
                </div>
                <RowMenu label={`Actions for v${v.version_number}`} actions={actionsFor(v)} />
              </li>
            ))}
          </ul>
        </>
      )}
      <ConfirmDialog
        open={restoring !== null}
        title={`Restore v${restoring?.version_number ?? ''}?`}
        confirmLabel="Restore as new version"
        pending={restore.isPending}
        onConfirm={() => restoring && restore.mutate(restoring)}
        onCancel={() => setRestoring(null)}
      >
        <p>
          Creates a new version from v{restoring?.version_number}. The simulated S3 copy lands in STANDARD; every existing
          version, including v{restoring?.version_number}, stays as it is.
        </p>
      </ConfirmDialog>
    </DetailPanel>
  )
}
