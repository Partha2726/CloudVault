import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { MoreHorizontal } from 'lucide-react'

export type RowAction = {
  label: string
  icon?: ReactNode
  onSelect: () => void
  destructive?: boolean
  disabled?: boolean
}

/** A row's action menu: closes on outside click, Escape, or after a choice. */
export function RowMenu({ label, actions }: { label: string; actions: RowAction[] }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((v) => !v)}
        className="rounded-[var(--radius-record)] p-1.5 text-ink-muted hover:bg-ground hover:text-ink"
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden />
      </button>
      {open && (
        <div id={menuId} role="menu" className="record absolute right-0 top-full z-20 mt-1 min-w-[12rem] py-1">
          {actions.map((a) => (
            <button
              key={a.label}
              type="button"
              role="menuitem"
              disabled={a.disabled}
              onClick={() => {
                setOpen(false)
                a.onSelect()
              }}
              className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm hover:bg-ground disabled:opacity-50 ${
                a.destructive ? 'text-alert' : 'text-ink'
              }`}
            >
              {a.icon}
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
