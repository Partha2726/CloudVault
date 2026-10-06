import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Archive, Loader2 } from 'lucide-react'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/useAuth'

export function LoginPage() {
  const { token, login, register } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (token) return <Navigate to="/" replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (mode === 'register' && (password.length < 8 || password.length > 128)) {
      setError('Password must be 8 to 128 characters.')
      return
    }
    setBusy(true)
    try {
      await (mode === 'login' ? login(email, password) : register(email, password))
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="bg-shell text-shell-ink">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-2.5 px-4 sm:px-6">
          <Archive className="h-5 w-5 text-shell-muted" strokeWidth={1.75} aria-hidden />
          <span className="text-[0.9375rem] font-semibold tracking-tight">CloudVault</span>
          <span className="rounded-[var(--radius-record)] border border-shell-raised px-1.5 py-0.5 text-xs font-semibold uppercase tracking-[0.08em] text-shell-muted">
            Simulated S3
          </span>
        </div>
      </header>
      <div className="flex flex-1 items-start justify-center px-4 pt-16 sm:pt-24">
      <div className="record w-full max-w-sm p-8">
        <h1 className="mb-6 text-xl font-semibold tracking-tight">{mode === 'login' ? 'Log in' : 'Create account'}</h1>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <label className="block text-sm">
            <span className="caption mb-1.5 block">Email</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-[var(--radius-record)] border border-rule-strong bg-panel px-3 py-2 text-ink outline-none focus:border-accent-strong focus-visible:outline-none focus:ring-2 focus:ring-accent/25"
            />
          </label>
          <label className="block text-sm">
            <span className="caption mb-1.5 block">Password</span>
            <input
              type="password"
              required
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-[var(--radius-record)] border border-rule-strong bg-panel px-3 py-2 text-ink outline-none focus:border-accent-strong focus-visible:outline-none focus:ring-2 focus:ring-accent/25"
            />
          </label>
          {error && (
            <p role="alert" className="text-sm text-alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-record)] bg-shell px-3 py-2.5 text-sm font-semibold text-shell-ink hover:bg-shell-raised disabled:opacity-60"
          >
            {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
            {mode === 'login' ? 'Log in' : 'Create account'}
          </button>
        </form>
        <button
          type="button"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError(null)
          }}
          className="mt-5 text-sm font-medium text-accent-strong underline-offset-4 hover:underline"
        >
          {mode === 'login' ? 'No account? Register' : 'Have an account? Log in'}
        </button>
      </div>
      </div>
    </div>
  )
}
