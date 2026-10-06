import type { DocumentItem } from '../../api/types'
import { FieldList } from '../../components/FieldList'
import { ProcessingBadge } from '../../components/ProcessingBadge'
import { SourceBadge } from '../../components/SourceBadge'
import { StorageClassBadge } from '../../components/StorageClassBadge'
import { formatBytes, formatCount } from '../../utils/format'
import { formatDateTime, typeLabel } from '../../utils/vocab'
import { DetailPanel } from './Panel'

/** Doc 06.5 Overview: CloudVault's record of the document, from GET /documents/{id}. */
export function OverviewTab({ doc }: { doc: DocumentItem }) {
  const v = doc.current_version
  const p = doc.processing
  return (
    <DetailPanel title="Overview" aside={<SourceBadge source="CloudVault" />}>
      <FieldList
        fields={[
          { label: 'Name', value: doc.display_name },
          { label: 'Status', value: doc.status === 'DELETED' ? 'In the trash' : 'Active' },
          {
            label: 'Current version',
            value: v ? (
              <>
                v{v.version_number}
                {v.origin === 'RESTORE' && <span className="text-ink-muted"> (restored)</span>}
                {v.state === 'S3_MISSING' && <span className="font-medium text-alert"> · missing from storage</span>}
              </>
            ) : (
              '–'
            ),
          },
          { label: 'Versions', value: <span data-figure>{formatCount(doc.version_count)}</span> },
          { label: 'Size', value: v ? <span data-figure>{formatBytes(v.size_bytes)}</span> : '–' },
          { label: 'Type', value: v ? `${typeLabel(v.content_type)} (${v.content_type})` : '–' },
          { label: 'Storage class', value: v ? <StorageClassBadge storageClass={v.storage_class} /> : '–' },
          {
            label: 'Processing',
            value: (
              <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <ProcessingBadge processing={p} />
                {p?.page_count != null && <span data-figure className="text-ink-muted">{formatCount(p.page_count)} {p.page_count === 1 ? 'page' : 'pages'}</span>}
                {p?.word_count != null && <span data-figure className="text-ink-muted">{formatCount(p.word_count)} {p.word_count === 1 ? 'word' : 'words'}</span>}
              </span>
            ),
          },
          { label: 'Created', value: formatDateTime(doc.created_at) },
          { label: 'Updated', value: formatDateTime(doc.updated_at) },
          ...(doc.deleted_at ? [{ label: 'Moved to trash', value: formatDateTime(doc.deleted_at) }] : []),
        ]}
      />
    </DetailPanel>
  )
}
