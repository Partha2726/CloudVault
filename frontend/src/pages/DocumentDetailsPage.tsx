import { useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArchiveRestore, ArrowLeft, Download, Trash2, Upload } from 'lucide-react'
import { ApiError } from '../api/client'
import {
  deleteDocument,
  detailKeys,
  getDocument,
  isDuplicate,
  permanentlyDeleteDocument,
  undeleteDocument,
  uploadVersion,
} from '../api/documents'
import type { DocumentItem, VersionItem } from '../api/types'
import { Button } from '../components/Button'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { ErrorState } from '../components/ErrorState'
import { ProcessingBadge } from '../components/ProcessingBadge'
import { RowMenu } from '../components/RowMenu'
import { Skeleton } from '../components/Skeleton'
import { StorageClassBadge } from '../components/StorageClassBadge'
import { Tabs } from '../components/Tabs'
import { UnavailableState } from '../components/UnavailableState'
import { useToast } from '../components/useToast'
import { startDownload } from '../utils/download'
import { refreshDocument } from '../utils/invalidate'
import { ACCEPTED_EXTENSIONS, formatDateTime } from '../utils/vocab'
import { AccessTab } from './details/AccessTab'
import { InspectorTab } from './details/InspectorTab'
import { OverviewTab } from './details/OverviewTab'
import { ProcessingTab } from './details/ProcessingTab'
import { VersionsTab } from './details/VersionsTab'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'versions', label: 'Versions' },
  { id: 'access', label: 'Access' },
  { id: 'inspector', label: 'S3 Inspector' },
  { id: 'processing', label: 'Processing' },
] as const
type TabId = (typeof TABS)[number]['id']

const MAX_UPLOAD_BYTES = 10_485_760 // convenience pre-check only; the server is authoritative (doc 06.4)
const message = (e: unknown) => (e instanceof ApiError ? e.message : 'Something went wrong.')

function BackLink() {
  return (
    <Link to="/documents" className="inline-flex items-center gap-1.5 self-start text-sm text-ink-muted hover:text-ink">
      <ArrowLeft className="h-4 w-4" aria-hidden />
      Documents
    </Link>
  )
}

/** Doc 06.5 Document Details: header (name, badges, actions) and tabs. Tab and version live in the URL. */
export function DocumentDetailsPage() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const tab: TabId = TABS.some((t) => t.id === params.get('tab')) ? (params.get('tab') as TabId) : 'overview'
  const versionParam = Number(params.get('version'))
  const version = Number.isInteger(versionParam) && versionParam > 0 ? versionParam : undefined

  const doc = useQuery({ queryKey: detailKeys.all(id), queryFn: () => getDocument(id), retry: false })

  const go = (next: TabId, v?: number) => {
    const p: Record<string, string> = {}
    if (next !== 'overview') p.tab = next
    if (next === 'inspector' && v) p.version = String(v)
    setParams(p, { replace: true })
  }

  if (doc.isPending) {
    return (
      <div className="flex flex-col gap-6" aria-busy="true">
        <BackLink />
        <Skeleton className="h-10 w-2/3 max-w-md" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (doc.isError) {
    const err = doc.error instanceof ApiError ? doc.error : null
    const missing = err?.status === 404 || err?.status === 422
    return (
      <div className="flex flex-col gap-6">
        <BackLink />
        {missing ? (
          <UnavailableState title="Document not found">
            It does not exist, was permanently deleted, or belongs to another account.{' '}
            <Link to="/documents" className="font-medium text-ink underline underline-offset-2">Back to Documents</Link>
          </UnavailableState>
        ) : (
          <ErrorState title="Document could not be loaded" message={message(doc.error)} onRetry={() => doc.refetch()} retrying={doc.isFetching} />
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <BackLink />
      <Header doc={doc.data} />
      <Tabs label="Document details" tabs={[...TABS]} active={tab} onChange={(t) => go(t)} />
      <div role="tabpanel" aria-label={TABS.find((t) => t.id === tab)?.label}>
        {tab === 'overview' && <OverviewTab doc={doc.data} />}
        {tab === 'versions' && <VersionsTab doc={doc.data} onInspect={(v) => go('inspector', v)} />}
        {tab === 'access' && <AccessTab doc={doc.data} />}
        {tab === 'inspector' && <InspectorTab doc={doc.data} version={version} onVersion={(v) => go('inspector', v)} />}
        {tab === 'processing' && <ProcessingTab doc={doc.data} />}
      </div>
    </div>
  )
}

function Header({ doc }: { doc: DocumentItem }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()
  const fileInput = useRef<HTMLInputElement>(null)
  const [confirm, setConfirm] = useState<'delete' | 'purge' | null>(null)
  const [downloading, setDownloading] = useState(false)
  const refresh = () => refreshDocument(queryClient, doc.id)
  const trashed = doc.status === 'DELETED'

  const upload = useMutation({
    mutationFn: (file: File) => uploadVersion(doc.id, file),
    onSuccess: (result, file) =>
      isDuplicate(result)
        ? toast({ message: `${file.name} matches the current version; nothing changed.` })
        : toast({ tone: 'success', message: `Uploaded ${file.name} as v${(result as VersionItem).version_number}.` }),
    onError: (e, file) => toast({ tone: 'error', message: `${file.name}: ${message(e)}` }),
    onSettled: refresh,
  })
  const softDelete = useMutation({
    mutationFn: () => deleteDocument(doc.id),
    onSuccess: () => toast({ tone: 'success', message: `${doc.display_name} moved to the trash.` }),
    onError: (e) => toast({ tone: 'error', message: `${doc.display_name}: ${message(e)}` }),
    onSettled: () => {
      setConfirm(null)
      return refresh()
    },
  })
  const undelete = useMutation({
    mutationFn: () => undeleteDocument(doc.id),
    onSuccess: () => toast({ tone: 'success', message: `${doc.display_name} restored from the trash.` }),
    onError: (e) => toast({ tone: 'error', message: `${doc.display_name}: ${message(e)}` }),
    onSettled: refresh,
  })
  const purge = useMutation({
    mutationFn: () => permanentlyDeleteDocument(doc.id),
    onSuccess: () => {
      toast({ tone: 'success', message: `${doc.display_name} was permanently deleted.` })
      queryClient.removeQueries({ queryKey: detailKeys.all(doc.id) })
      navigate('/documents?view=trash', { replace: true })
    },
    onError: (e) => toast({ tone: 'error', message: `${doc.display_name}: ${message(e)}` }),
    onSettled: () => {
      setConfirm(null)
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const onFile = (file: File | undefined) => {
    if (!file) return
    if (file.size > MAX_UPLOAD_BYTES) {
      toast({ tone: 'error', message: `${file.name} is larger than 10 MiB and was not uploaded.` })
      return
    }
    upload.mutate(file)
  }

  const download = async () => {
    setDownloading(true)
    try {
      await startDownload(queryClient, doc.id)
    } catch (e) {
      toast({ tone: 'error', message: `Download of ${doc.display_name}: ${message(e)}` })
    } finally {
      setDownloading(false)
    }
  }

  return (
    <>
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <h1 className="break-words text-[1.75rem] sm:text-[2.125rem] font-semibold leading-tight tracking-tight text-ink">{doc.display_name}</h1>
          <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[0.8125rem]">
            {trashed && <span className="caption bg-alert-soft px-1.5 py-0.5 text-alert">In trash</span>}
            {doc.current_version && <StorageClassBadge storageClass={doc.current_version.storage_class} />}
            <ProcessingBadge processing={doc.processing} />
            {doc.current_version && <span data-figure className="text-ink-muted">v{doc.current_version.version_number} of {doc.version_count}</span>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {trashed ? (
            <>
              <Button variant="primary" onClick={() => undelete.mutate()} pending={undelete.isPending} icon={<ArchiveRestore className="h-4 w-4" aria-hidden />}>
                Restore from trash
              </Button>
              <RowMenu
                label="More actions"
                actions={[{ label: 'Delete permanently', icon: <Trash2 className="h-4 w-4" aria-hidden />, destructive: true, onSelect: () => setConfirm('purge') }]}
              />
            </>
          ) : (
            <>
              <Button
                variant="primary"
                onClick={download}
                pending={downloading}
                disabled={doc.current_version?.state !== 'ACTIVE'}
                icon={<Download className="h-4 w-4" aria-hidden />}
              >
                Download
              </Button>
              <Button variant="secondary" onClick={() => fileInput.current?.click()} pending={upload.isPending} icon={<Upload className="h-4 w-4" aria-hidden />}>
                Upload new version
              </Button>
              <input
                ref={fileInput}
                type="file"
                accept={ACCEPTED_EXTENSIONS}
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                onChange={(e) => {
                  onFile(e.target.files?.[0])
                  e.target.value = ''
                }}
              />
              <RowMenu
                label="More actions"
                actions={[{ label: 'Move to trash', icon: <Trash2 className="h-4 w-4" aria-hidden />, destructive: true, onSelect: () => setConfirm('delete') }]}
              />
            </>
          )}
        </div>
      </header>

      {trashed && (
        <p role="status" className="record border-alert/40 bg-alert-soft/40 px-5 py-3 text-sm text-ink">
          In the trash since {doc.deleted_at ? formatDateTime(doc.deleted_at) : 'recently'}. The current object version is
          hidden behind an S3 delete marker; every version is kept. Restore it to download or add versions.
        </p>
      )}

      <ConfirmDialog
        open={confirm === 'delete'}
        title="Move to trash?"
        confirmLabel="Move to trash"
        destructive
        pending={softDelete.isPending}
        onConfirm={() => softDelete.mutate()}
        onCancel={() => setConfirm(null)}
      >
        <p>
          <span className="font-medium text-ink">{doc.display_name}</span> moves to the trash (S3 delete marker). Its data
          and versions are kept, and you can restore it.
        </p>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === 'purge'}
        title="Delete permanently?"
        confirmLabel="Delete permanently"
        destructive
        requireText={doc.display_name}
        pending={purge.isPending}
        onConfirm={() => purge.mutate()}
        onCancel={() => setConfirm(null)}
      >
        <p>
          Every stored version and delete marker of <span className="font-medium text-ink">{doc.display_name}</span> is
          removed from the simulated S3 bucket, with its access history. This cannot be undone.
        </p>
      </ConfirmDialog>
    </>
  )
}
