import type { SearchResult } from '../../types/library'
import type { DocumentListItem } from '../../types/note'

// DADOS DE DEMONSTRAÇÃO TEMPORÁRIOS.
// Nenhum destes itens existe no backend. Notas de exemplo só aparecem no
// dashboard quando o backend está offline; documentos serão removidos na Fase 3.

export const DEMO_DOCUMENTS: DocumentListItem[] = [
  { id: 'demo-1', name: 'Planejamento trimestral.pdf', kind: 'PDF', size: '1,2 MB' },
  { id: 'demo-2', name: 'Anotações de leitura.md', kind: 'MD', size: '18 KB' },
  { id: 'demo-3', name: 'Contrato de serviço.docx', kind: 'DOCX', size: '240 KB' },
]

export const DEMO_NOTES: SearchResult[] = [
  {
    type: 'note',
    id: 'demo-note-1',
    title: 'Ideias para o projeto',
    snippet: 'Exemplo de nota de demonstração exibido enquanto o backend está offline.',
    updated_at: '2026-11-20T12:00:00Z',
    category: null,
    project: null,
    tags: [],
    score: null,
  },
  {
    type: 'note',
    id: 'demo-note-2',
    title: 'Resumo da reunião',
    snippet: 'Outro exemplo temporário. Inicie o backend para ver as notas reais.',
    updated_at: '2026-11-18T09:30:00Z',
    category: null,
    project: null,
    tags: [],
    score: null,
  },
]
