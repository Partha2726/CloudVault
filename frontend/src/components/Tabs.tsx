type Tab<T extends string> = { id: T; label: string }

/** Underlined record tabs. Selection lives in the caller (usually the URL). */
export function Tabs<T extends string>({
  label,
  tabs,
  active,
  onChange,
}: {
  label: string
  tabs: Tab<T>[]
  active: T
  onChange: (id: T) => void
}) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-x-1 border-b border-rule-strong sm:flex-nowrap sm:overflow-x-auto">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={active === t.id}
          onClick={() => onChange(t.id)}
          className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${
            active === t.id ? 'border-shell text-ink' : 'border-transparent text-ink-muted hover:text-ink'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}
