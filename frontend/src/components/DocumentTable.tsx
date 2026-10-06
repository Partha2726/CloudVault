import { Link } from 'react-router-dom'
import type { DocumentItem } from '../api/types'
import { formatBytes } from '../utils/format'
import { formatDate, typeLabel } from '../utils/vocab'
import { ProcessingBadge } from './ProcessingBadge'
import { RowMenu, type RowAction } from './RowMenu'
import { StorageClassBadge } from './StorageClassBadge'

type DocumentTableProps = {
  items: DocumentItem[]
  view: 'active' | 'trash'
  actionsFor: (doc: DocumentItem) => RowAction[]
}

/** The documents register: a real table on wide screens, ruled rows on phones. */
export function DocumentTable({ items, view, actionsFor }: DocumentTableProps) {
  const trash = view === 'trash'
  return (
    <>
      <table className="hidden w-full text-sm md:table">
        <caption className="sr-only">{trash ? 'Documents in the trash' : 'Documents'}</caption>
        <thead>
          <tr className="border-b border-rule text-left">
            <th scope="col" className="caption px-6 py-2.5 font-semibold">Name</th>
            <th scope="col" className="caption px-3 py-2.5 font-semibold">Type</th>
            <th scope="col" className="caption px-3 py-2.5 text-right font-semibold">Size</th>
            {!trash && <th scope="col" className="caption px-3 py-2.5 font-semibold">Class</th>}
            <th scope="col" className="caption px-3 py-2.5 text-right font-semibold">Versions</th>
            {!trash && <th scope="col" className="caption px-3 py-2.5 font-semibold">Processing</th>}
            <th scope="col" className="caption px-3 py-2.5 font-semibold">{trash ? 'Deleted' : 'Updated'}</th>
            <th scope="col" className="w-12 px-4 py-2.5"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-rule">
          {items.map((doc) => {
            const v = doc.current_version
            return (
              <tr key={doc.id} className="hover:bg-ground/60">
                <th scope="row" className="max-w-[22rem] px-6 py-3 text-left font-medium text-ink">
                  <Link to={`/documents/${doc.id}`} className="block truncate underline-offset-4 hover:underline" title={doc.display_name}>
                    {doc.display_name}
                  </Link>
                </th>
                <td className="px-3 py-3 text-ink-muted">{typeLabel(v?.content_type)}</td>
                <td data-figure className="whitespace-nowrap px-3 py-3 text-right text-ink">
                  {v ? formatBytes(v.size_bytes) : '–'}
                </td>
                {!trash && <td className="px-3 py-3">{v && <StorageClassBadge storageClass={v.storage_class} />}</td>}
                <td data-figure className="px-3 py-3 text-right text-ink">{doc.version_count}</td>
                {!trash && <td className="px-3 py-3"><ProcessingBadge processing={doc.processing} /></td>}
                <td className="whitespace-nowrap px-3 py-3 text-ink-muted">
                  {formatDate(trash && doc.deleted_at ? doc.deleted_at : doc.updated_at)}
                </td>
                <td className="px-4 py-2 text-right">
                  <RowMenu label={`Actions for ${doc.display_name}`} actions={actionsFor(doc)} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <ul className="divide-y divide-rule md:hidden" aria-label={trash ? 'Documents in the trash' : 'Documents'}>
        {items.map((doc) => {
          const v = doc.current_version
          return (
            <li key={doc.id} className="flex items-start gap-3 px-5 py-3.5">
              <div className="min-w-0 flex-1">
                <Link to={`/documents/${doc.id}`} className="block truncate font-medium text-ink underline-offset-4 hover:underline" title={doc.display_name}>
                  {doc.display_name}
                </Link>
                <p data-figure className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.8125rem] text-ink-muted">
                  <span>{typeLabel(v?.content_type)}</span>
                  {v && <span>{formatBytes(v.size_bytes)}</span>}
                  <span>{doc.version_count === 1 ? '1 version' : `${doc.version_count} versions`}</span>
                  <span>{trash && doc.deleted_at ? `Deleted ${formatDate(doc.deleted_at)}` : formatDate(doc.updated_at)}</span>
                </p>
                {!trash && (
                  <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
                    {v && <StorageClassBadge storageClass={v.storage_class} />}
                    <ProcessingBadge processing={doc.processing} />
                  </p>
                )}
              </div>
              <RowMenu label={`Actions for ${doc.display_name}`} actions={actionsFor(doc)} />
            </li>
          )
        })}
      </ul>
    </>
  )
}
