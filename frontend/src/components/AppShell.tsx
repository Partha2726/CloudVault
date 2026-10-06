import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Archive, LogOut } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../auth/useAuth'

type Me = { id: string; email: string }

const NAV: { to: string; label: string }[] = [
  { to: '/', label: 'Dashboard' },
  { to: '/documents', label: 'Documents' },
  { to: '/optimization', label: 'Optimization' },
  { to: '/about', label: 'About' },
]

export function AppShell() {
  const { logout } = useAuth()
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/auth/me') })

  return (
    <div className="min-h-screen">
      <header className="bg-shell text-shell-ink">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 px-4 sm:h-14 sm:flex-nowrap sm:gap-8 sm:px-6">
          <div className="flex h-14 items-center gap-2.5 sm:h-auto">
            <Archive className="h-5 w-5 text-shell-muted" strokeWidth={1.75} aria-hidden />
            <span className="text-[0.9375rem] font-semibold tracking-tight">CloudVault</span>
            <span className="hidden rounded-[var(--radius-record)] border border-shell-raised px-1.5 py-0.5 text-xs font-semibold uppercase tracking-[0.08em] text-shell-muted md:inline">
              Simulated S3
            </span>
          </div>
          <nav aria-label="Main" className="order-last -mx-4 flex h-11 w-[calc(100%+2rem)] items-stretch overflow-x-auto border-t border-shell-raised px-1 sm:order-none sm:mx-0 sm:h-auto sm:w-auto sm:flex-1 sm:self-stretch sm:border-t-0 sm:px-0">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `flex items-center border-b-2 px-3 text-sm font-medium transition-colors ${
                    isActive
                      ? 'border-shell-ink text-shell-ink'
                      : 'border-transparent text-shell-muted hover:text-shell-ink'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <span className="hidden max-w-[16rem] truncate text-sm text-shell-muted sm:inline">{me.data?.email}</span>
          <button
            type="button"
            onClick={logout}
            className="ml-auto flex items-center gap-1.5 rounded-[var(--radius-record)] px-2 py-1.5 text-sm sm:ml-0 text-shell-muted hover:bg-shell-raised hover:text-shell-ink focus-visible:outline-shell-ink"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">Log out</span>
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 pb-16 pt-8 sm:px-6 sm:pt-10">
        <Outlet />
      </main>
    </div>
  )
}
