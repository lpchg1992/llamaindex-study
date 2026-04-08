type ToastOptions = {
  title?: string
  description?: string
  type?: 'default' | 'success' | 'error' | 'warning' | 'info'
}

export function toast(options: ToastOptions) {
  const event = new CustomEvent('toast', { detail: options })
  window.dispatchEvent(event)
}

toast.success = (title: string) => toast({ title, type: 'success' })
toast.error = (title: string) => toast({ title, type: 'error' })
toast.warning = (title: string) => toast({ title, type: 'warning' })
toast.info = (title: string) => toast({ title, type: 'info' })