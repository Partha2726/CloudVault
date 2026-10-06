// Thin wrappers over the documents endpoints (doc 05.5). No client-side business rules.
import { api } from './client'
import type {
  AccessLogItem,
  DocumentItem,
  DownloadLink,
  DuplicateDocument,
  Page,
  ProcessingItem,
  S3Info,
  VersionItem,
} from './types'

export type DocumentQuery = {
  q?: string
  status?: 'active' | 'deleted'
  type?: string
  storage_class?: string
  sort?: string
  page?: number
  page_size?: number
}

export const documentKeys = {
  all: ['documents'] as const,
  list: (query: DocumentQuery) => ['documents', query] as const,
}

export function listDocuments(query: DocumentQuery) {
  return api<Page<DocumentItem>>('/documents', { query })
}

function fileBody(file: File): FormData {
  const body = new FormData()
  body.append('file', file, file.name)
  return body
}

/** 201 new document, or 200 `{duplicate: true, document}` when the same name and content already exist. */
export function uploadDocument(file: File) {
  return api<DocumentItem | DuplicateDocument>('/documents', { method: 'POST', body: fileBody(file) })
}

/** 201 new version, or 200 `{duplicate: true}` when the content equals the current version. */
export function uploadVersion(documentId: string, file: File) {
  return api<VersionItem | { duplicate: true }>(`/documents/${documentId}/versions`, {
    method: 'POST',
    body: fileBody(file),
  })
}

export function deleteDocument(documentId: string) {
  return api<void>(`/documents/${documentId}`, { method: 'DELETE' })
}

export function undeleteDocument(documentId: string) {
  return api<DocumentItem>(`/documents/${documentId}/undelete`, { method: 'POST' })
}

export function permanentlyDeleteDocument(documentId: string) {
  return api<void>(`/documents/${documentId}/permanent`, { method: 'DELETE', query: { confirm: true } })
}

export function getDownloadLink(documentId: string, version?: number) {
  return api<DownloadLink>(`/documents/${documentId}/download`, { query: { version } })
}

export function isDuplicate(result: unknown): result is { duplicate: true } {
  return typeof result === 'object' && result !== null && (result as { duplicate?: unknown }).duplicate === true
}

// ---- details (T22) ----

/** Every query for one document lives under this prefix, so one invalidation refreshes all its tabs. */
export const detailKeys = {
  all: (id: string) => ['document', id] as const,
  versions: (id: string) => ['document', id, 'versions'] as const,
  access: (id: string, page: number) => ['document', id, 'access', page] as const,
  s3Info: (id: string, version: number | undefined) => ['document', id, 's3-info', version ?? 'current'] as const,
  processing: (id: string) => ['document', id, 'processing'] as const,
}

export function getDocument(id: string) {
  return api<DocumentItem>(`/documents/${id}`)
}

export function listVersions(id: string) {
  return api<{ items: VersionItem[] }>(`/documents/${id}/versions`)
}

/** Copies version n onto the key as a NEW current version (W6, AM-2). Not idempotent. */
export function restoreVersion(id: string, versionNumber: number) {
  return api<VersionItem>(`/documents/${id}/versions/${versionNumber}/restore`, { method: 'POST' })
}

export function listAccessLogs(id: string, page: number) {
  return api<Page<AccessLogItem>>(`/documents/${id}/access-logs`, { query: { page } })
}

export function getS3Info(id: string, version?: number) {
  return api<S3Info>(`/documents/${id}/s3-info`, { query: { version } })
}

export function listProcessing(id: string) {
  return api<{ items: ProcessingItem[] }>(`/documents/${id}/processing`)
}

export function retryProcessing(id: string, version: number) {
  return api<ProcessingItem>(`/documents/${id}/processing/retry`, { method: 'POST', query: { version } })
}
