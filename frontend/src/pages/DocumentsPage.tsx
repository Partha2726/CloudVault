import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArchiveRestore, Download, Search, Trash2, X } from 'lucide-react'
import { ApiError } from '../api/client'
import {
  type DocumentQuery,
  deleteDocument,
  documentKeys,
  isDuplicate,
  listDocuments,
  permanentlyDeleteDocument,
  undeleteDocument,
  uploadDocument,
  uploadVersion,
} from '../api/documents'
import type { DocumentItem, VersionItem } from '../api/types'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { DocumentTable } from '../components/DocumentTable'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { Pagination } from '../components/Pagination'
import type { RowAction } from '../components/RowMenu'
import { Skeleton } from '../components/Skeleton'
import { Tabs } from '../components/Tabs'
import { UploadDropzone } from '../components/UploadDropzone'
import { useToast } from '../components/useToast'
import { startDownload } from '../utils/download'
import { STORAGE_CLASSES, TYPE_FILTERS } from '../utils/vocab'

const PAGE_SIZE = 25
const MAX_UPLOAD_BYTES = 10_485_760 // convenience pre-check only; the server is authoritative (doc 06.4)
const SORTS = [
  { value: '-updated', label: 'Recently updated' },
  { value: 'updated', label: 'Oldest updated' },
  { value: 'name', label: 'Name A–Z' },
  { value: '-name', label: 'Name Z–A' },
  { value: '-size', label: 'Largest' },
  { value: 'size', label: 'Smallest' },
]

type Conflict = { file: File; existingId: string }
type Pending = { kind: 'delete' | 'purge'; doc: DocumentItem } | null

function errorMessage(e: unknown): string {
  return e instanceof ApiError ? e.message : 'Something went wrong.'
}

export function DocumentsPage() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'trash' ? 'trash' : 'active'
  const query: DocumentQuery = {
    status: view === 'trash' ? 'deleted' : 'active',
    q: params.get('q') || undefined,
    type: (view === 'active' && params.get('type')) || undefined,
    storage_class: (view === 'active' && params.get('class')) || undefined,
    sort: params.get('sort') || '-updated',
    page: Number(params.get('page')) || 1,
    page_size: PAGE_SIZE,
  }
  const filtered = Boolean(query.q || query.type || query.storage_class)

  const setParam = (changes: Record<string, string | null>, keepPage = false) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!keepPage) next.delete('page')
    setParams(next, { replace: true })
  }

  const queryClient = useQueryClient()
  const toast = useToast()
  const docs = useQuery({
    queryKey: documentKeys.list(query),
    queryFn: () => listDocuments(query),
    placeholderData: keepPreviousData,
  })
  const refreshAll = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: documentKeys.all }),
      queryClient.invalidateQueries({ queryKey: ['dashboard'] }),
    ])

  // ---- upload queue (sequential; a 409 pauses it for the user's choice) ----
  const [uploading, setUploading] = useState<string | null>(null)
  const [queued, setQueued] = useState(0)
  const [conflict, setConflict] = useState<Conflict | null>(null)
  const [conflictPending, setConflictPending] = useState(false)
  const resolveConflict = useRef<((proceed: boolean) => void) | null>(null)

  const askAboutConflict = (c: Conflict) =>
    new Promise<boolean>((resolve) => {
      resolveConflict.current = resolve
      setConflict(c)
    })

  const uploadOne = async (file: File) => {
    if (file.size > MAX_UPLOAD_BYTES) {
      toast({ tone: 'error', message: `${file.name} is larger than 10 MiB and was not uploaded.` })
      return
    }
    try {
      const result = await uploadDocument(file)
      if (isDuplicate(result)) {
        toast({ message: `${result.document.display_name} is already stored with the same content.` })
      } else {
        toast({ tone: 'success', message: `Uploaded ${result.display_name} as v1.` })
      }
    } catch (e) {
      const existingId = e instanceof ApiError && e.code === 'NAME_EXISTS' ? e.details.existing_document_id : null
      if (typeof existingId === 'string') {
        await askAboutConflict({ file, existingId })
      } else {
        toast({ tone: 'error', message: `${file.name}: ${errorMessage(e)}` })
      }
    } finally {
      await refreshAll()
    }
  }

  const onFiles = async (files: File[]) => {
    for (let i = 0; i < files.length; i++) {
      setUploading(files[i].name)
      setQueued(files.length - i - 1)
      await uploadOne(files[i])
    }
    setUploading(null)
    setQueued(0)
  }

  const uploadAsNewVersion = async () => {
    if (!conflict) return
    setConflictPending(true)
    try {
      const result = await uploadVersion(conflict.existingId, conflict.file)
      if (isDuplicate(result)) {
        toast({ message: `${conflict.file.name} matches the current version; nothing changed.` })
      } else {
        toast({ tone: 'success', message: `Uploaded ${conflict.file.name} as v${(result as VersionItem).version_number}.` })
      }
    } catch (e) {
      toast({ tone: 'error', message: `${conflict.file.name}: ${errorMessage(e)}` })
    } finally {
      setConflictPending(false)
      setConflict(null)
      resolveConflict.current?.(true)
      await refreshAll()
    }
  }

  const cancelConflict = () => {
    if (conflict) toast({ message: `${conflict.file.name} was not uploaded.` })
    setConflict(null)
    resolveConflict.current?.(false)
  }

  // ---- row actions ----
  const [pending, setPending] = useState<Pending>(null)
  const softDelete = useMutation({
    mutationFn: (doc: DocumentItem) => deleteDocument(doc.id),
    onSuccess: (_, doc) => toast({ tone: 'success', message: `${doc.display_name} moved to the trash.` }),
    onError: (e, doc) => toast({ tone: 'error', message: `${doc.display_name}: ${errorMessage(e)}` }),
    onSettled: () => {
      setPending(null)
      return refreshAll()
    },
  })
  const purge = useMutation({
    mutationFn: (doc: DocumentItem) => permanentlyDeleteDocument(doc.id),
    onSuccess: (_, doc) => toast({ tone: 'success', message: `${doc.display_name} was permanently deleted.` }),
    onError: (e, doc) => toast({ tone: 'error', message: `${doc.display_name}: ${errorMessage(e)}` }),
    onSettled: () => {
      setPending(null)
      return refreshAll()
    },
  })
  const restore = useMutation({
    mutationFn: (doc: DocumentItem) => undeleteDocument(doc.id),
    onSuccess: (doc) => toast({ tone: 'success', message: `${doc.display_name} restored from the trash.` }),
    onError: (e, doc) => toast({ tone: 'error', message: `${doc.display_name}: ${errorMessage(e)}` }),
    onSettled: () => refreshAll(),
  })

  const download = async (doc: DocumentItem) => {
    try {
      await startDownload(queryClient, doc.id)
    } catch (e) {
      toast({ tone: 'error', message: `${doc.display_name}: ${errorMessage(e)}` })
    }
  }

  const actionsFor = (doc: DocumentItem): RowAction[] =>
    view === 'trash'
      ? [
          {
            label: 'Restore',
            icon: <ArchiveRestore className="h-4 w-4" aria-hidden />,
            onSelect: () => restore.mutate(doc),
          },
          {
            label: 'Delete permanently',
            icon: <Trash2 className="h-4 w-4" aria-hidden />,
            destructive: true,
            onSelect: () => setPending({ kind: 'purge', doc }),
          },
        ]
      : [
          { label: 'Download', icon: <Download className="h-4 w-4" aria-hidden />, onSelect: () => download(doc) },
          {
            label: 'Move to trash',
            icon: <Trash2 className="h-4 w-4" aria-hidden />,
            destructive: true,
            onSelect: () => setPending({ kind: 'delete', doc }),
          },
        ]

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-[2.125rem] font-semibold leading-tight tracking-tight text-ink">Documents</h1>
        <p className="mt-1.5 text-[0.9375rem] text-ink-muted">
          Every document is an object in your simulated S3 bucket; its versions are object versions.
        </p>
      </div>

      <Tabs
        label="Documents view"
        tabs={[
          { id: 'active', label: 'Documents' },
          { id: 'trash', label: 'Trash' },
        ]}
        active={view}
        onChange={(v) => setParams(v === 'trash' ? { view: 'trash' } : {}, { replace: true })}
      />

      {view === 'active' && <UploadDropzone onFiles={onFiles} uploading={uploading} queued={queued} />}

      <section aria-label={view === 'trash' ? 'Trash' : 'Document list'} className="record">
        <Filters view={view} query={query} setParam={setParam} />
        {docs.isPending && <TableSkeleton />}
        {docs.isError && (
          <div className="p-5 sm:p-6">
            <ErrorState
              title="The document list could not be loaded"
              message={errorMessage(docs.error)}
              onRetry={() => docs.refetch()}
              retrying={docs.isFetching}
            />
          </div>
        )}
        {docs.data && docs.data.items.length === 0 && (
          <div className="p-5 sm:p-6">
            {filtered ? (
              <EmptyState title="No documents match">
                <span>Try another search or filter. </span>
                <button
                  type="button"
                  className="font-medium text-accent-strong underline-offset-4 hover:underline"
                  onClick={() => setParam({ q: null, type: null, class: null })}
                >
                  Clear search and filters
                </button>
              </EmptyState>
            ) : view === 'trash' ? (
              <EmptyState title="The trash is empty">
                Documents you move to the trash stay here, hidden by a simulated delete marker, until you restore or
                permanently delete them.
              </EmptyState>
            ) : (
              <EmptyState title="Upload your first document">
                Drop a file above or choose one. It is stored as an object in your simulated S3 bucket.
              </EmptyState>
            )}
          </div>
        )}
        {docs.data && docs.data.items.length > 0 && (
          <div className={docs.isPlaceholderData ? 'opacity-60' : ''}>
            <DocumentTable items={docs.data.items} view={view} actionsFor={actionsFor} />
            <Pagination
              page={docs.data.page}
              pageSize={docs.data.page_size}
              total={docs.data.total}
              onPage={(p) => setParam({ page: String(p) }, true)}
            />
          </div>
        )}
      </section>

      <ConfirmDialog
        open={conflict !== null}
        title="A document with this name already exists"
        confirmLabel="Upload as new version"
        pending={conflictPending}
        onConfirm={uploadAsNewVersion}
        onCancel={cancelConflict}
      >
        <p>
          <span className="font-medium text-ink">{conflict?.file.name}</span> has different content from the document
          of the same name. Upload it as that document's next version? Earlier versions are kept.
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        open={pending?.kind === 'delete'}
        title="Move to trash?"
        confirmLabel="Move to trash"
        destructive
        pending={softDelete.isPending}
        onConfirm={() => pending && softDelete.mutate(pending.doc)}
        onCancel={() => setPending(null)}
      >
        <p>
          <span className="font-medium text-ink">{pending?.doc.display_name}</span> moves to the trash (S3 delete
          marker). Its data and versions are kept, and you can restore it.
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        open={pending?.kind === 'purge'}
        title="Delete permanently?"
        confirmLabel="Delete permanently"
        destructive
        requireText={pending?.kind === 'purge' ? pending.doc.display_name : undefined}
        pending={purge.isPending}
        onConfirm={() => pending && purge.mutate(pending.doc)}
        onCancel={() => setPending(null)}
      >
        <p>
          Every stored version and delete marker of{' '}
          <span className="font-medium text-ink">{pending?.doc.display_name}</span> is removed from the simulated S3
          bucket, with its access history. This cannot be undone.
        </p>
      </ConfirmDialog>
    </div>
  )
}

function Filters({
  view,
  query,
  setParam,
}: {
  view: 'active' | 'trash'
  query: DocumentQuery
  setParam: (changes: Record<string, string | null>, keepPage?: boolean) => void
}) {
  const current = query.q ?? ''
  const [text, setText] = useState(current)
  const [synced, setSynced] = useState(current)
  if (current !== synced) {
    // The URL changed elsewhere (e.g. "Clear search and filters"): follow it.
    setSynced(current)
    setText(current)
  }
  useEffect(() => {
    if (text === current) return
    const timer = window.setTimeout(() => setParam({ q: text.trim() || null }), 300)
    return () => window.clearTimeout(timer)
  }, [text, current, setParam])

  const select =
    'w-full rounded-[var(--radius-record)] border border-rule-strong bg-panel px-2.5 py-2 text-sm text-ink outline-none focus:border-accent-strong sm:w-auto'

  return (
    <div className="flex flex-col gap-3 border-b border-rule px-5 py-4 sm:px-6 lg:flex-row lg:items-center">
      <label className="relative flex-1">
        <span className="sr-only">Search documents</span>
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" aria-hidden />
        <input
          type="search"
          value={text}
          maxLength={200}
          onChange={(e) => setText(e.target.value)}
          placeholder={view === 'trash' ? 'Search the trash' : 'Search names and extracted text'}
          className="w-full rounded-[var(--radius-record)] border border-rule-strong bg-panel py-2 pl-9 pr-9 text-sm text-ink placeholder:text-ink-faint outline-none focus:border-accent-strong focus:ring-2 focus:ring-accent/25"
        />
        {text && (
          <button
            type="button"
            aria-label="Clear search"
            onClick={() => setText('')}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-[var(--radius-record)] p-1 text-ink-faint hover:text-ink"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        )}
      </label>
      <div className="grid grid-cols-2 gap-3 sm:flex">
        {view === 'active' && (
          <>
            <label>
              <span className="sr-only">File type</span>
              <select className={select} value={query.type ?? ''} onChange={(e) => setParam({ type: e.target.value || null })}>
                <option value="">All types</option>
                {TYPE_FILTERS.map((t) => (
                  <option key={t} value={t}>
                    {t.toUpperCase()}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="sr-only">Storage class</span>
              <select
                className={select}
                value={query.storage_class ?? ''}
                onChange={(e) => setParam({ class: e.target.value || null })}
              >
                <option value="">All classes</option>
                {STORAGE_CLASSES.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.id}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
        <label className="col-span-2 sm:col-span-1">
          <span className="sr-only">Sort</span>
          <select className={select} value={query.sort} onChange={(e) => setParam({ sort: e.target.value === '-updated' ? null : e.target.value })}>
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  )
}

function TableSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading documents" className="divide-y divide-rule">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="flex items-center gap-6 px-5 py-4 sm:px-6">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="hidden h-4 w-16 md:block" />
          <Skeleton className="hidden h-4 w-20 md:block" />
          <Skeleton className="ml-auto h-4 w-24" />
        </div>
      ))}
    </div>
  )
}
