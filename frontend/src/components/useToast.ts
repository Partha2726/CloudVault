import { useContext } from 'react'
import { ToastContext } from './toast-context'

export function useToast() {
  const push = useContext(ToastContext)
  if (!push) throw new Error('useToast must be used inside ToastProvider')
  return push
}
