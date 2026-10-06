// Shared display vocabulary for the Finding Aid world (DESIGN.md). Values come from the API.
import type { JobStatus, RecommendationStatus, StorageClass } from '../api/types'

// Simulated S3 storage classes (AM-7); descriptions follow the AWS class definitions.
export const STORAGE_CLASSES: { id: StorageClass; description: string; color: string }[] = [
  { id: 'STANDARD', description: 'Frequent access', color: 'var(--color-class-standard)' },
  { id: 'STANDARD_IA', description: 'Infrequent access', color: 'var(--color-class-ia)' },
  { id: 'GLACIER_IR', description: 'Rarely accessed, instant retrieval', color: 'var(--color-class-gir)' },
]

export const JOB_STATUSES: { id: JobStatus; label: string; color: string }[] = [
  { id: 'PENDING', label: 'Pending', color: 'var(--color-accent)' },
  { id: 'SUCCEEDED', label: 'Succeeded', color: 'var(--color-ok)' },
  { id: 'SKIPPED', label: 'Skipped', color: 'var(--color-class-gir)' },
  { id: 'FAILED', label: 'Failed', color: 'var(--color-alert)' },
]

// The backend's `type` filter values (allowed upload extensions, doc 05.3).
export const TYPE_FILTERS = ['pdf', 'docx', 'txt', 'md', 'csv', 'png', 'jpg', 'jpeg'] as const
export const ACCEPTED_EXTENSIONS = '.pdf,.docx,.txt,.md,.csv,.png,.jpg,.jpeg'

const CONTENT_TYPE_LABELS: Record<string, string> = {
  'application/pdf': 'PDF',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word',
  'text/plain': 'Text',
  'text/markdown': 'Markdown',
  'text/csv': 'CSV',
  'image/png': 'PNG',
  'image/jpeg': 'JPEG',
}

export function typeLabel(contentType: string | undefined): string {
  return (contentType && CONTENT_TYPE_LABELS[contentType]) || 'File'
}

const DATE = new Intl.DateTimeFormat('en', { day: 'numeric', month: 'short', year: 'numeric' })
const DATE_TIME = new Intl.DateTimeFormat('en', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

export function formatDate(iso: string): string {
  return DATE.format(new Date(iso))
}

export function formatDateTime(iso: string): string {
  return DATE_TIME.format(new Date(iso))
}

// Job error codes (doc 08.3 plus AM-7 additions) in plain words.
const JOB_ERRORS: Record<string, string> = {
  TOO_LARGE: 'Larger than the 5 MB processing limit',
  NO_EXTRACTION: 'No text extraction for this file type',
  CORRUPT: 'The file is damaged or unreadable',
  ENCRYPTED: 'The PDF is encrypted',
  PARSE_ERROR: 'The file could not be parsed',
  S3_MISSING: 'The stored version no longer exists',
  VERSION_UNAVAILABLE: 'The version is not stored',
}

export function jobErrorLabel(code: string | null): string | null {
  return code ? (JOB_ERRORS[code] ?? code) : null
}

// Recommendation states (T14). Only OPEN can be applied or dismissed; the others are final outcomes.
export const RECOMMENDATION_STATUSES: {
  id: RecommendationStatus
  tab: string
  label: string
  color: string
  hollow?: boolean
}[] = [
  { id: 'OPEN', tab: 'Open', label: 'Open', color: 'var(--color-accent)' },
  { id: 'APPLIED', tab: 'Applied', label: 'Applied', color: 'var(--color-ok)' },
  { id: 'DISMISSED', tab: 'Dismissed', label: 'Dismissed', color: 'var(--color-class-gir)' },
  { id: 'STALE', tab: 'Stale', label: 'Stale', color: 'var(--color-ink-faint)', hollow: true },
]

// Engine signals (doc 07.4) in plain words; download counts are CloudVault's own access log.
export const SIGNAL_LABELS: { key: string; label: string; unit: 'days' | 'downloads' | 'bytes' }[] = [
  { key: 'age_days', label: 'Age', unit: 'days' },
  { key: 'days_in_class', label: 'In class', unit: 'days' },
  { key: 'idle_days', label: 'Idle', unit: 'days' },
  { key: 'a30', label: 'Downloads, 30 days', unit: 'downloads' },
  { key: 'a90', label: 'Downloads, 90 days', unit: 'downloads' },
  { key: 'size_bytes', label: 'Size', unit: 'bytes' },
]
