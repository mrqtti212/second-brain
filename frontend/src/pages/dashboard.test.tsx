import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mocks } from '../test/apiMock'
import { category, documentPage, documentResult, page, project, result, tagPython, tagWeb } from '../test/fixtures'
import { renderApp } from '../test/render'

vi.mock('../services/api', async (importOriginal) => ({ ...(await importOriginal<object>()), ...(await import('../test/apiMock')).mocks }))

const POLL = 2000
const tick = (ms = POLL) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

interface Counts { notes?: number; documents?: number; pending?: number; processing?: number; failed?: number }

/** A API de mentira responde contagens por tipo e por estado, como a real. */
function mockCounts({ notes = 0, documents = 0, pending = 0, processing = 0, failed = 0 }: Counts, recent = [result(), documentResult()]) {
  mocks.api.search.mockImplementation(async (params: { type?: string } = {}) =>
    params.type === 'note' ? page([], notes) : page(recent),
  )
  const byStatus = { pending, processing, failed } as Record<string, number>
  mocks.documentsApi.list.mockImplementation(async (params: { status?: string } = {}) =>
    documentPage([], params.status ? byStatus[params.status] ?? 0 : documents),
  )
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  mocks.api.health.mockResolvedValue({ status: 'ok', database: 'ok' })
  mocks.categoriesApi.list.mockResolvedValue([category])
  mocks.projectsApi.list.mockResolvedValue([project])
  mocks.tagsApi.list.mockResolvedValue([tagPython, tagWeb])
})
afterEach(() => vi.useRealTimers())

describe('Dashboard com a API online', () => {
  it('mostra contagens e itens recentes que vêm da API, sem dados de exemplo', async () => {
    mockCounts({ notes: 7, documents: 5 })
    renderApp('/', { withBackend: true })

    expect(await screen.findByRole('link', { name: /7\s*notas/ })).toHaveAttribute('href', '/library?type=note')
    expect(screen.getByRole('link', { name: /5\s*documentos PDF/ })).toHaveAttribute('href', '/documents')
    expect(screen.getByRole('heading', { name: 'Atualizados recentemente' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Guia de Python' })).toHaveAttribute('href', '/notes/n1')
    expect(screen.getByRole('link', { name: 'Contrato de serviço' })).toHaveAttribute('href', '/documents/d1')
    expect(screen.queryByText(/demonstração|fictíci|Ideias para o projeto/i)).not.toBeInTheDocument()
  })

  it('pede à API as contagens por tipo e por estado de processamento', async () => {
    mockCounts({ notes: 1, documents: 1 })
    renderApp('/', { withBackend: true })
    await screen.findByRole('heading', { name: 'Atualizados recentemente' })
    expect(mocks.api.search).toHaveBeenCalledWith({ type: 'note', limit: 1 })
    for (const status of ['pending', 'processing', 'failed']) {
      expect(mocks.documentsApi.list).toHaveBeenCalledWith({ status, limit: 1 })
    }
  })

  it('tem busca, "Nova nota" e "Importar PDF" funcionando (links reais)', async () => {
    mockCounts({ notes: 1, documents: 1 })
    renderApp('/', { withBackend: true })
    await screen.findByRole('heading', { name: 'Atualizados recentemente' })
    const newNote = screen.getAllByRole('link', { name: /Nova nota/ })
    expect(newNote).toHaveLength(1) // sem o botão repetido da barra do topo
    expect(newNote[0]).toHaveAttribute('href', '/notes/new')
    expect(screen.getByRole('link', { name: /Importar PDF/ })).toHaveAttribute('href', '/documents/new')
    expect(screen.getAllByRole('search')).toHaveLength(1) // a barra do topo não duplica a busca do dashboard
  })

  it('a busca do dashboard leva à biblioteca com o termo', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    mockCounts({ notes: 1, documents: 1 })
    const { router } = renderApp('/', { withBackend: true })
    await screen.findByRole('heading', { name: 'Atualizados recentemente' })

    await user.type(screen.getByRole('searchbox', { name: 'Buscar na biblioteca' }), 'prazo do contrato')
    await user.click(screen.getByRole('button', { name: 'Buscar' }))

    expect(router.state.location.pathname).toBe('/library')
    expect(router.state.location.search).toBe('?q=prazo%20do%20contrato')
    expect(await screen.findByRole('heading', { name: 'Biblioteca' })).toBeInTheDocument()
  })

  it('biblioteca vazia: convida a começar, sem lista de recentes nem números inventados', async () => {
    mockCounts({ notes: 0, documents: 0 }, [])
    renderApp('/', { withBackend: true })
    expect(await screen.findByRole('heading', { name: 'Comece guardando algo' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Atualizados recentemente' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Importar PDF/ })).toBeInTheDocument()
  })

  it('avisa de PDFs em processamento e de falhas, com números reais', async () => {
    mockCounts({ notes: 1, documents: 4, pending: 1, processing: 1, failed: 2 })
    renderApp('/', { withBackend: true })
    expect(await screen.findByText(/2 PDFs estão sendo processados/)).toBeInTheDocument()
    expect(screen.getByText(/2 documentos falharam no processamento/)).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /Ver documentos|Abrir documentos/ })).toHaveLength(2)
  })

  it('atualiza sozinho enquanto há PDF em processamento e para quando termina', async () => {
    mockCounts({ notes: 1, documents: 1, processing: 1 })
    renderApp('/', { withBackend: true })
    await screen.findByText(/1 PDF está sendo processado/)

    mockCounts({ notes: 1, documents: 1, processing: 0 }) // o processamento terminou
    await tick()
    await tick()
    expect(screen.queryByText(/sendo processado/)).not.toBeInTheDocument()

    const calls = mocks.api.search.mock.calls.length
    await tick(POLL * 5)
    expect(mocks.api.search.mock.calls.length).toBe(calls) // sem polling quando nada está em andamento
  })

  it('mostra o erro real da API (e permite tentar de novo) em vez de dados de exemplo', async () => {
    const { ApiError } = await import('../services/api')
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    mockCounts({ notes: 1, documents: 1 })
    mocks.documentsApi.list.mockRejectedValueOnce(new ApiError('Erro 500', 500))
    renderApp('/', { withBackend: true })
    expect(await screen.findByText('Erro 500', { selector: 'span' })).toBeInTheDocument()
    expect(screen.queryByText(/Ideias para o projeto|fictíci/)).not.toBeInTheDocument()

    mockCounts({ notes: 3, documents: 2 })
    await user.click(screen.getAllByRole('button', { name: 'Tentar novamente' })[0])
    expect(await screen.findByRole('link', { name: /3\s*notas/ })).toBeInTheDocument()
  })
})

describe('Barra do topo', () => {
  it('mantém "Nova nota" nas outras telas e só a oculta no dashboard', async () => {
    mocks.api.search.mockResolvedValue(page([result()]))
    mocks.documentsApi.list.mockResolvedValue(documentPage([]))
    const { unmount } = renderApp('/library', { withBackend: true })
    await screen.findByRole('link', { name: 'Guia de Python' })
    const topbar = () => screen.getAllByRole('banner')[0] // a barra do topo é o primeiro <header> do documento
    const banner = topbar()
    expect(within(banner).getByRole('link', { name: /Nova nota/ })).toHaveAttribute('href', '/notes/new')
    unmount()

    renderApp('/', { withBackend: true })
    await screen.findByRole('heading', { name: 'Atualizados recentemente' })
    expect(within(topbar()).queryByRole('link', { name: /Nova nota/ })).not.toBeInTheDocument()
  })
})

describe('Dashboard sem backend utilizável', () => {
  it('backend offline: explica como iniciar, sem dados de exemplo e sem chamar a API de dados', async () => {
    const { ApiError } = await import('../services/api')
    mocks.api.health.mockRejectedValue(new ApiError('Não foi possível conectar ao backend.', 0))
    renderApp('/', { withBackend: true })
    expect(await screen.findByRole('heading', { name: 'Não foi possível conectar ao backend' })).toBeInTheDocument()
    expect(screen.getByText('./scripts/run-app.sh')).toBeInTheDocument()
    expect(screen.queryByText(/Ideias para o projeto|Planejamento trimestral|fictíci|demonstração/i)).not.toBeInTheDocument()
    expect(mocks.api.search).not.toHaveBeenCalled()
    expect(mocks.documentsApi.list).not.toHaveBeenCalled()
  })

  it('API no ar com banco indisponível: orienta a subir o banco e aplicar as migrations', async () => {
    mocks.api.health.mockResolvedValue({ status: 'ok', database: 'unavailable' })
    renderApp('/', { withBackend: true })
    const heading = await screen.findByRole('heading', { name: /banco de dados está indisponível/ })
    const section = heading.closest('section') as HTMLElement
    expect(within(section).getByText('docker compose up -d db')).toBeInTheDocument()
    expect(within(section).getByText('alembic upgrade head')).toBeInTheDocument()
    expect(mocks.api.search).not.toHaveBeenCalled()
  })
})

describe('Sem recursos de aparência apenas', () => {
  it('não há mais "Assistente IA" no menu nem campo desabilitado em nenhuma tela', async () => {
    mockCounts({ notes: 1, documents: 1 })
    renderApp('/', { withBackend: true })
    await screen.findByRole('heading', { name: 'Atualizados recentemente' })
    expect(screen.queryByRole('link', { name: /Assistente/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/Em breve/)).not.toBeInTheDocument()
    expect(document.querySelectorAll('input:disabled, button:disabled').length).toBe(0)
  })

  it('a rota antiga do assistente não existe mais', async () => {
    mockCounts({ notes: 1, documents: 1 })
    renderApp('/assistant', { withBackend: true })
    expect(await screen.findByRole('heading', { name: 'Página não encontrada' })).toBeInTheDocument()
  })
})
