const dateFormatter = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' })
const dateTimeFormatter = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'long', timeStyle: 'short' })

export const formatDate = (iso: string) => dateFormatter.format(new Date(iso))
export const formatDateTime = (iso: string) => dateTimeFormatter.format(new Date(iso))

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1).replace('.', ',')} MB`
}
