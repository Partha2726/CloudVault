import type { ReactNode } from 'react'

export type Field = { label: string; value: ReactNode; mono?: boolean }

/** Record fields as caption + value rows; two columns on wide screens, stacked on phones. */
export function FieldList({ fields }: { fields: Field[] }) {
  return (
    <dl className="divide-y divide-rule">
      {fields.map((f) => (
        <div key={f.label} className="grid gap-1 px-5 py-3 sm:grid-cols-[12rem_1fr] sm:gap-6 sm:px-6">
          <dt className="caption pt-0.5">{f.label}</dt>
          <dd className={`min-w-0 break-words text-sm text-ink ${f.mono ? 'font-mono text-[0.8125rem]' : ''}`}>{f.value}</dd>
        </div>
      ))}
    </dl>
  )
}
