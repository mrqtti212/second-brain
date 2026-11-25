import type { DocumentStatus } from '../../types/library'
import { Badge } from '../Badge/Badge'

interface StatusBadgeProps {
  status: DocumentStatus
  hasText: boolean
}

/** Estado de processamento de um documento, em linguagem do usuário. */
export function StatusBadge({ status, hasText }: StatusBadgeProps) {
  if (status === 'failed') return <Badge tone="danger">Falhou</Badge>
  if (status === 'pending') return <Badge>Aguardando processamento</Badge>
  if (status === 'processing') return <Badge tone="accent">Processando…</Badge>
  return hasText ? <Badge tone="success">Concluído</Badge> : <Badge tone="warning">Sem texto extraível</Badge>
}
