export interface HealthStatus {
  status: string
  database: 'ok' | 'unavailable'
}

/** Item exibido na lista compacta de documentos (reais ou de demonstração). */
export interface DocumentListItem {
  id: string
  name: string
  kind: 'PDF' | 'DOCX' | 'MD'
  size: string
  /** Quando presente, o item é um link para o documento real. */
  href?: string
}
