import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, tokenStore } from '../api/client'
import { AuthContext } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => tokenStore.get())
  const queryClient = useQueryClient()

  const login = useCallback(async (email: string, password: string) => {
    const res = await api<{ access_token: string }>('/auth/login', {
      method: 'POST',
      body: { email, password },
      redirectOn401: false,
    })
    tokenStore.set(res.access_token)
    setToken(res.access_token)
  }, [])

  const register = useCallback(
    async (email: string, password: string) => {
      await api('/auth/register', { method: 'POST', body: { email, password }, redirectOn401: false })
      await login(email, password)
    },
    [login],
  )

  const logout = useCallback(() => {
    tokenStore.clear()
    setToken(null)
    queryClient.clear()
  }, [queryClient])

  const value = useMemo(() => ({ token, login, register, logout }), [token, login, register, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
