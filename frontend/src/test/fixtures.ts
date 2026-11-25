import type { Category, DocumentChunk, DocumentChunkList, DocumentContent, DocumentItem, DocumentListPage, Note, Project, SearchPage, SearchResult, Tag } from '../types/library'

const date = '2026-11-20T12:00:00Z'

export const category: Category = { id: 'c1', name: 'Estudos', color: '#6d7cff', description: null, created_at: date, notes_count: 1, documents_count: 0 }
export const project: Project = { id: 'p1', name: 'Tese', description: 'Doutorado', created_at: date, notes_count: 1, documents_count: 0 }
export const tagPython: Tag = { id: 't1', name: 'python', color: null, created_at: date, notes_count: 1, documents_count: 0 }
export const tagWeb: Tag = { id: 't2', name: 'web', color: '#4fc38a', created_at: date, notes_count: 0, documents_count: 0 }

export const note: Note = {
  id: 'n1',
  title: 'Guia de Python',
  content: 'Conteúdo da nota',
  category: { id: category.id, name: category.name, color: category.color },
  project: { id: project.id, name: project.name },
  tags: [{ id: tagPython.id, name: tagPython.name, color: null }],
  created_at: date,
  updated_at: date,
}

export function result(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    type: 'note',
    id: note.id,
    title: note.title,
    snippet: 'trecho python destacado',
    updated_at: date,
    category: note.category,
    project: note.project,
    tags: note.tags,
    score: null,
    ...overrides,
  }
}

export function page(items: SearchResult[], total = items.length, offset = 0): SearchPage {
  return { items, total, limit: 12, offset }
}

export const documentItem: DocumentItem = {
  id: 'd1',
  title: 'Contrato de serviço',
  original_filename: 'contrato.pdf',
  content_type: 'application/pdf',
  size_bytes: 2048,
  sha256: 'a'.repeat(64),
  page_count: 2,
  chunk_count: 3,
  status: 'completed',
  has_text: true,
  error_message: null,
  category: note.category,
  project: note.project,
  tags: note.tags,
  created_at: date,
  updated_at: date,
}

export const documentContent: DocumentContent = {
  id: 'd1',
  title: documentItem.title,
  status: 'completed',
  has_text: true,
  page_count: 2,
  pages: [
    { page_number: 1, text: 'Texto da primeira página' },
    { page_number: 2, text: 'Cláusula de rescisão' },
  ],
}

export function documentPage(items: DocumentItem[], total = items.length): DocumentListPage {
  return { items, total, limit: 12, offset: 0 }
}

export function documentResult(overrides: Partial<SearchResult> = {}): SearchResult {
  return result({
    type: 'document',
    id: 'd1',
    title: documentItem.title,
    snippet: 'cláusula de \ue000rescisão\ue001',
    status: 'completed',
    page_count: 2,
    has_text: true,
    ...overrides,
  })
}

export const chunkList: DocumentChunkList = {
  total: 3,
  limit: 20,
  offset: 0,
  items: [
    { id: 'k0', chunk_index: 0, page_number: 1, content: 'Primeiro trecho da página um.', character_count: 29, start_offset: 0, end_offset: 29 },
    { id: 'k1', chunk_index: 1, page_number: 1, content: 'Segundo trecho, ainda na página um.', character_count: 35, start_offset: 20, end_offset: 55 },
    { id: 'k2', chunk_index: 2, page_number: 2, content: 'Terceiro trecho, já na página dois.', character_count: 35, start_offset: 0, end_offset: 35 },
  ] satisfies DocumentChunk[],
}
