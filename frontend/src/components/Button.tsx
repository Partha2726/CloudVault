import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Loader2 } from 'lucide-react'

type Variant = 'primary' | 'secondary' | 'danger' | 'quiet'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-shell text-shell-ink hover:bg-shell-raised border border-shell',
  secondary: 'bg-panel text-ink border border-rule-strong hover:border-accent hover:bg-ground',
  danger: 'bg-alert text-white border border-alert hover:brightness-95',
  quiet: 'bg-transparent text-ink-muted border border-transparent hover:bg-ground hover:text-ink',
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  pending?: boolean
  icon?: ReactNode
  size?: 'sm' | 'md'
}

/** Square-cornered record button. `pending` disables it and shows a spinner in place of the icon. */
export function Button({
  variant = 'secondary',
  pending = false,
  icon,
  size = 'md',
  className = '',
  disabled,
  children,
  ...rest
}: ButtonProps) {
  const sizing = size === 'sm' ? 'px-2.5 py-1 text-[0.8125rem]' : 'px-3.5 py-2 text-sm'
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || pending}
      className={`inline-flex items-center justify-center gap-2 rounded-[var(--radius-record)] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${sizing} ${VARIANTS[variant]} ${className}`}
    >
      {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  )
}
