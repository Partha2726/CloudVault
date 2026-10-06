// Thin fetch wrapper (doc 06.1): attaches the JWT, parses the standard error body,
// and sends the user to login on 401.

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')
const TOKEN_KEY = 'cloudvault.token'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export const tokenStore = {
  get: (): string | null => {
    try {
      return sessionStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  set: (token: string) => {
    try {
      sessionStorage.setItem(TOKEN_KEY, token)
    } catch {
      // sessionStorage unavailable; the session lasts only until reload
    }
  },
  clear: () => {
    try {
      sessionStorage.removeItem(TOKEN_KEY)
    } catch {
      // ignore
    }
  },
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'DELETE'
  body?: unknown
  query?: Record<string, string | number | boolean | undefined>
  redirectOn401?: boolean
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, redirectOn401 = true } = opts
  const url = new URL(`${BASE_URL}/api${path}`)
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== '') url.searchParams.set(k, String(v))
  }

  const headers: Record<string, string> = {}
  const token = tokenStore.get()
  if (token) headers.Authorization = `Bearer ${token}`

  let payload: BodyInit | undefined
  if (body instanceof FormData) {
    payload = body
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  let res: Response
  try {
    res = await fetch(url, { method, headers, body: payload })
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Cannot reach the CloudVault API')
  }

  if (res.status === 401 && redirectOn401) {
    tokenStore.clear()
    if (window.location.pathname !== '/login') window.location.assign('/login')
  }
  if (res.status === 204) return undefined as T

  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const err = data?.error
    throw new ApiError(res.status, err?.code ?? 'UNKNOWN', err?.message ?? `Request failed (${res.status})`, err?.details ?? {})
  }
  return data as T
}
