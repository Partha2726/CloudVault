// Binary units (KiB, MiB, GiB), matching how the 10 MiB upload limit is stated (doc 05.3).
const UNITS = ['B', 'KiB', 'MiB', 'GiB', 'TiB']

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), UNITS.length - 1)
  const value = bytes / 1024 ** exponent
  const digits = exponent === 0 || value >= 100 ? 0 : value >= 10 ? 1 : 2
  return `${value.toFixed(digits)} ${UNITS[exponent]}`
}

export function formatCount(n: number): string {
  return new Intl.NumberFormat('en').format(n)
}

export function formatShare(part: number, total: number): string {
  if (total <= 0) return '0%'
  const share = (part / total) * 100
  if (share > 0 && share < 1) return '<1%'
  return `${Math.round(share)}%`
}
