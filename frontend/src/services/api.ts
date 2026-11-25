import type {
  Category,
  DocumentChunkList,
  DocumentContent,
  DocumentItem,
  DocumentListPage,
  DocumentListParams,
  DocumentMetadataInput,
  DuplicateDocumentInfo,
  Note,
  NoteInput,
  OrganizationInput,
  Project,
  SearchPage,
  SearchParams,
  Tag,
  UploadLimits,
} from '../types/library'
import type { HealthStatus } from '../types/note'

// Vazio usa o proxy do Vite (/api -> backend). Pode apontar para outra origem.
const BASE_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number
  /** Corpo JSON da resposta de erro, quando houver (ex.: `existing_document` no 409). */
  readonly body: Record<string, unknown> | null

  constructor(message: string, status: number, body: Record<string, unknown> | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }

  /** Quando o servidor recusou o upload porque o mesmo arquivo (SHA-256) já existe. */
  get duplicateOf(): DuplicateDocumentInfo | null {
    if (this.status !== 409 || this.body?.code !== 'duplicate_document') return null
    return (this.body.existing_document as DuplicateDocumentInfo | undefined) ?? null
  }

  /** Sem resposta do servidor (backend desligado, rede). */
  get isOffline(): boolean {
    return this.status === 0
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    // Em envios FormData o navegador define o Content-Type (com o boundary).
    const isForm = init?.body instanceof FormData
    response = await fetch(`${BASE_URL}/api${path}`, {
      ...init,
      headers: { ...(isForm ? {} : { 'Content-Type': 'application/json' }), ...init?.headers },
    })
  } catch {
    throw new ApiError('Não foi possível conectar ao backend.', 0)
  }

  if (!response.ok) {
    let detail = `Erro ${response.status}`
    let parsed: Record<string, unknown> | null = null
    try {
      const body = await response.json()
      parsed = body && typeof body === 'object' ? body : null
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) {
        const first = body.detail[0]
        detail = first?.msg ? `Dados inválidos: ${first.msg}` : 'Dados inválidos.'
      }
    } catch {
      /* resposta sem corpo JSON */
    }
    throw new ApiError(detail, response.status, parsed)
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

const json = (body: unknown) => JSON.stringify(body)

function resource<T>(path: string) {
  return {
    list: () => request<T[]>(path),
    create: (input: OrganizationInput) => request<T>(path, { method: 'POST', body: json(input) }),
    update: (id: string, input: Partial<OrganizationInput>) =>
      request<T>(`${path}/${id}`, { method: 'PATCH', body: json(input) }),
    remove: (id: string) => request<void>(`${path}/${id}`, { method: 'DELETE' }),
  }
}

export const categoriesApi = resource<Category>('/categories')
export const projectsApi = resource<Project>('/projects')
export const tagsApi = resource<Tag>('/tags')

export const api = {
  health: () => request<HealthStatus>('/health'),

  getNote: (id: string) => request<Note>(`/notes/${id}`),
  createNote: (input: NoteInput) => request<Note>('/notes', { method: 'POST', body: json(input) }),
  updateNote: (id: string, input: Partial<NoteInput>) =>
    request<Note>(`/notes/${id}`, { method: 'PATCH', body: json(input) }),
  deleteNote: (id: string) => request<void>(`/notes/${id}`, { method: 'DELETE' }),

  search: (params: SearchParams = {}) => {
    const query = new URLSearchParams()
    if (params.q) query.set('q', params.q)
    if (params.type) query.set('type', params.type)
    if (params.category_id) query.set('category_id', params.category_id)
    if (params.project_id) query.set('project_id', params.project_id)
    params.tag_id?.forEach((id) => query.append('tag_id', id))
    if (params.limit !== undefined) query.set('limit', String(params.limit))
    if (params.offset !== undefined) query.set('offset', String(params.offset))
    const qs = query.toString()
    return request<SearchPage>(`/search${qs ? `?${qs}` : ''}`)
  },
}

export const documentsApi = {
  limits: () => request<UploadLimits>('/documents/limits'),
  list: (params: DocumentListParams = {}) => {
    const query = new URLSearchParams()
    if (params.q) query.set('q', params.q)
    if (params.status) query.set('status', params.status)
    if (params.category_id) query.set('category_id', params.category_id)
    if (params.project_id) query.set('project_id', params.project_id)
    params.tag_id?.forEach((id) => query.append('tag_id', id))
    if (params.limit !== undefined) query.set('limit', String(params.limit))
    if (params.offset !== undefined) query.set('offset', String(params.offset))
    const qs = query.toString()
    return request<DocumentListPage>(`/documents${qs ? `?${qs}` : ''}`)
  },
  get: (id: string) => request<DocumentItem>(`/documents/${id}`),
  update: (id: string, input: Partial<DocumentMetadataInput>) =>
    request<DocumentItem>(`/documents/${id}`, { method: 'PATCH', body: json(input) }),
  /** Pede novo processamento a partir do PDF original (202). 409 se já estiver na fila ou em processamento. */
  reprocess: (id: string) => request<DocumentItem>(`/documents/${id}/reprocess`, { method: 'POST' }),
  chunks: (id: string, params: { limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams()
    if (params.limit !== undefined) query.set('limit', String(params.limit))
    if (params.offset !== undefined) query.set('offset', String(params.offset))
    const qs = query.toString()
    return request<DocumentChunkList>(`/documents/${id}/chunks${qs ? `?${qs}` : ''}`)
  },
  content: (id: string) => request<DocumentContent>(`/documents/${id}/content`),
  upload: (form: FormData) => request<DocumentItem>('/documents', { method: 'POST', body: form }),
  remove: (id: string) => request<void>(`/documents/${id}`, { method: 'DELETE' }),
  /** URL para baixar o PDF original (usada em um link, não em fetch). */
  fileUrl: (id: string) => `${BASE_URL}/api/documents/${id}/file`,
}
