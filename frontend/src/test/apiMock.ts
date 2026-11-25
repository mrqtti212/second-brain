import { vi } from 'vitest'

/** Substitui apenas a camada HTTP; ApiError continua real. */
const resourceMock = () => ({ list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() })

export const mocks = {
  api: {
    health: vi.fn(),
    getNote: vi.fn(),
    createNote: vi.fn(),
    updateNote: vi.fn(),
    deleteNote: vi.fn(),
    search: vi.fn(),
  },
  documentsApi: {
    limits: vi.fn(),
    list: vi.fn(),
    get: vi.fn(),
    update: vi.fn(),
    reprocess: vi.fn(),
    chunks: vi.fn(),
    content: vi.fn(),
    upload: vi.fn(),
    remove: vi.fn(),
    // Função pura: não deve ser zerada pelos resets dos mocks.
    fileUrl: (id: string) => `/api/documents/${id}/file`,
  },
  categoriesApi: resourceMock(),
  projectsApi: resourceMock(),
  tagsApi: resourceMock(),
}
