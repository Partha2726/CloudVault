// Response shapes from doc 05.4 / 05.5.

export type StorageClass = 'STANDARD' | 'STANDARD_IA' | 'GLACIER_IR'
export type JobStatus = 'PENDING' | 'SUCCEEDED' | 'FAILED' | 'SKIPPED'

export type DashboardSummary = {
  document_count: number
  current_bytes: number
  total_bytes_all_versions: number
  accesses_30d: number
  bytes_by_class: Record<StorageClass, number>
  open_recommendations: number
  jobs_by_status: Record<JobStatus, number>
}

export type DocumentStatus = 'ACTIVE' | 'DELETED'

export type CurrentVersion = {
  version_number: number
  size_bytes: number
  content_type: string
  storage_class: StorageClass
  created_at: string
  origin: 'UPLOAD' | 'RESTORE'
  state: 'ACTIVE' | 'S3_MISSING'
}

export type ProcessingSummary = {
  status: JobStatus
  page_count: number | null
  word_count: number | null
  stalled: boolean
}

export type DocumentItem = {
  id: string
  display_name: string
  status: DocumentStatus
  current_version: CurrentVersion | null
  version_count: number
  processing: ProcessingSummary | null
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export type Page<T> = { items: T[]; total: number; page: number; page_size: number }

export type DuplicateDocument = { duplicate: true; document: DocumentItem }

export type VersionItem = {
  version_number: number
  size_bytes: number
  content_type: string
  sha256: string
  storage_class: StorageClass
  origin: 'UPLOAD' | 'RESTORE'
  restored_from_version: number | null
  state: 'ACTIVE' | 'S3_MISSING'
  is_current: boolean
  created_at: string
}

export type DownloadLink = { url: string; expires_in: number }

export type AccessLogItem = { accessed_at: string; version_number: number; event_type: string }

export type S3Info = {
  bucket: string
  key: string
  version_id: string
  etag: string
  content_length: number
  content_type: string
  last_modified: string
  storage_class: StorageClass
  metadata: Record<string, string>
  tags: Record<string, string>
  source: string
}

export type ProcessingItem = {
  version_number: number
  status: JobStatus
  attempts: number
  error_code: string | null
  page_count: number | null
  word_count: number | null
  stalled: boolean
}

// ---- recommendations (T14, doc 05.4) ----

export type RecommendationStatus = 'OPEN' | 'APPLIED' | 'DISMISSED' | 'STALE'

export type Recommendation = {
  id: string
  document_id: string
  display_name: string
  version_number: number
  current_class: StorageClass
  recommended_class: StorageClass
  rule_id: string
  reason: string
  signals: Record<string, number>
  estimate: null // doc 07.5: no pricing format is specified; always null
  status: RecommendationStatus
  created_at: string
}
