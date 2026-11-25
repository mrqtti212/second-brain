export interface CategorySummary {
  id: string
  name: string
  color: string | null
}
export interface ProjectSummary {
  id: string
  name: string
}
export interface TagSummary {
  id: string
  name: string
  color: string | null
}

export interface Category extends CategorySummary {
  description: string | null
  created_at: string
  notes_count: number
  documents_count: number
}
export interface Project extends ProjectSummary {
  description: string | null
  created_at: string
  notes_count: number
  documents_count: number
}
export interface Tag extends TagSummary {
  created_at: string
  notes_count: number
  documents_count: number
}

export interface Note {
  id: string
  title: string
  content: string
  category: CategorySummary | null
  project: ProjectSummary | null
  tags: TagSummary[]
  created_at: string
  updated_at: string
}

/** Corpo de criação/edição de nota. */
export interface NoteInput {
  title: string
  content: string
  category_id: string | null
  project_id: string | null
  tag_ids: string[]
}

export type ContentType = 'note' | 'document'

export interface SearchResult {
  type: ContentType
  id: string
  title: string
  snippet: string
  updated_at: string
  category: CategorySummary | null
  project: ProjectSummary | null
  tags: TagSummary[]
  score: number | null
  /** Apenas documentos. */
  status?: DocumentStatus | null
  page_count?: number | null
  has_text?: boolean | null
}

export interface SearchPage {
  items: SearchResult[]
  total: number
  limit: number
  offset: number
}

export interface SearchParams {
  q?: string
  type?: ContentType
  category_id?: string
  project_id?: string
  tag_id?: string[]
  limit?: number
  offset?: number
}

/** Campos editáveis de categoria, projeto e etiqueta. */
export interface OrganizationInput {
  name: string
  description?: string | null
  color?: string | null
}

export type DocumentStatus = 'pending' | 'processing' | 'completed' | 'failed'

/** Estados em que o processamento ainda vai mudar sozinho. */
export const isInProgress = (status: DocumentStatus | undefined): boolean => status === 'pending' || status === 'processing'

export interface DocumentItem {
  id: string
  title: string
  original_filename: string
  content_type: string
  size_bytes: number
  sha256: string
  page_count: number | null
  chunk_count: number
  status: DocumentStatus
  has_text: boolean
  error_message: string | null
  category: CategorySummary | null
  project: ProjectSummary | null
  tags: TagSummary[]
  created_at: string
  updated_at: string
}

export interface DocumentPageText {
  page_number: number
  text: string
}

export interface DocumentContent {
  id: string
  title: string
  status: DocumentStatus
  has_text: boolean
  page_count: number | null
  pages: DocumentPageText[]
}

export interface DocumentListPage {
  items: DocumentItem[]
  total: number
  limit: number
  offset: number
}

export interface DocumentListParams {
  q?: string
  status?: DocumentStatus
  category_id?: string
  project_id?: string
  tag_id?: string[]
  limit?: number
  offset?: number
}

export interface UploadLimits {
  max_upload_bytes: number
  max_pages: number
}

/** Trecho de uma página, gerado na importação. */
export interface DocumentChunk {
  id: string
  chunk_index: number
  page_number: number
  content: string
  character_count: number
  start_offset: number
  end_offset: number
}

export interface DocumentChunkList {
  items: DocumentChunk[]
  total: number
  limit: number
  offset: number
}

/** Campos editáveis de um documento (PATCH). */
export interface DocumentMetadataInput {
  title: string
  category_id: string | null
  project_id: string | null
  tag_ids: string[]
}

/** Resumo do documento já existente, devolvido no 409 de duplicidade. */
export interface DuplicateDocumentInfo {
  id: string
  title: string
  original_filename: string
  created_at: string
}
