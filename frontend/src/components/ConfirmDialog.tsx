import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Button } from './Button'

type ConfirmDialogProps = {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  destructive?: boolean
  /** When set, the confirm button stays disabled until this exact text is typed (permanent delete). */
  requireText?: string
  pending?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Native <dialog> (focus trap, Escape to cancel) in the record style. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  destructive = false,
  requireText,
  pending = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const [typed, setTyped] = useState('')
  const titleId = useId()
  const inputId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      setTyped('')
      dialog.showModal()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open])

  const blocked = requireText !== undefined && typed !== requireText

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault()
        if (!pending) onCancel()
      }}
      className="record m-auto w-[min(32rem,calc(100vw-2rem))] p-0 text-ink backdrop:bg-shell/50"
    >
      <form
        method="dialog"
        onSubmit={(e) => {
          e.preventDefault()
          if (!blocked && !pending) onConfirm()
        }}
      >
        <div className="border-b border-rule px-6 py-4">
          <h2 id={titleId} className="text-base font-semibold">
            {title}
          </h2>
        </div>
        <div className="space-y-3 px-6 py-5 text-sm text-ink-muted">
          {children}
          {requireText !== undefined && (
            <label htmlFor={inputId} className="block pt-1">
              <span className="caption mb-1.5 block">Type the file name to confirm</span>
              <input
                id={inputId}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                autoComplete="off"
                spellCheck={false}
                className="w-full rounded-[var(--radius-record)] border border-rule-strong bg-panel px-3 py-2 text-ink outline-none focus:border-accent-strong focus:ring-2 focus:ring-accent/25"
              />
            </label>
          )}
        </div>
        <div className="flex flex-col-reverse gap-2 border-t border-rule px-6 py-4 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onCancel} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" variant={destructive ? 'danger' : 'primary'} pending={pending} disabled={blocked}>
            {confirmLabel}
          </Button>
        </div>
      </form>
    </dialog>
  )
}
