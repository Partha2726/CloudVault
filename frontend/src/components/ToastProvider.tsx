import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { CircleAlert, CircleCheck, Info, X } from 'lucide-react'
import { ToastContext, type ToastInput, type ToastTone } from './toast-context'

type Toast = { id: number; message: string; tone: ToastTone }

const ICONS = { info: Info, success: CircleCheck, error: CircleAlert }
const DURATION = { info: 5000, success: 5000, error: 9000 }

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), [])
  const push = useCallback(({ message, tone = 'info' }: ToastInput) => {
    setToasts((all) => [...all.slice(-3), { id: nextId++, message, tone }])
  }, [])

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-stretch gap-2 sm:inset-x-auto sm:right-6 sm:w-96"
      >
        {toasts.map((t) => (
          <ToastRow key={t.id} toast={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

function ToastRow({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(toast.id), DURATION[toast.tone])
    return () => window.clearTimeout(timer)
  }, [toast, onDismiss])
  const Icon = ICONS[toast.tone]
  const tone = toast.tone === 'error' ? 'text-alert' : toast.tone === 'success' ? 'text-ok' : 'text-accent'
  return (
    <div role={toast.tone === 'error' ? 'alert' : 'status'} className="record pointer-events-auto flex items-start gap-3 px-4 py-3 text-sm text-ink">
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone}`} aria-hidden />
      <p className="flex-1">{toast.message}</p>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss"
        className="rounded-[var(--radius-record)] p-0.5 text-ink-faint hover:bg-ground hover:text-ink"
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </div>
  )
}
