import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mocks } from '../test/apiMock'
import { category, chunkList, documentContent, documentItem, documentPage, project, tagPython, tagWeb } from '../test/fixtures'
import { renderApp } from '../test/render'
import type { DocumentItem } from '../types/library'

vi.mock('../services/api', async (importOriginal) => ({ ...(await importOriginal<object>()), ...(await import('../test/apiMock')).mocks }))

const POLL = 2000
const pending: DocumentItem = { ...documentItem, status: 'pending', chunk_count: 0, has_text: false, updated_at: '2026-11-20T12:00:01Z' }
const processing: DocumentItem = { ...pending, status: 'processing', updated_at: '2026-11-20T12:00:02Z' }
const completed: DocumentItem = { ...documentItem, updated_at: '2026-11-20T12:00:03Z' }
const failed: DocumentItem = { ...documentItem, status: 'failed', chunk_count: 0, has_text: false, error_message: 'Não foi possível extrair o texto do PDF (RuntimeError).' }
const emptyContent = { ...documentContent, pages: [], has_text: false, status: 'pending' as const }

const tick = (ms = POLL) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  mocks.api.health.mockResolvedValue({ status: 'ok', database: 'ok' })
  mocks.categoriesApi.list.mockResolvedValue([category])
  mocks.projectsApi.list.mockResolvedValue([project])
  mocks.tagsApi.list.mockResolvedValue([tagPython, tagWeb])
  mocks.documentsApi.limits.mockResolvedValue({ max_upload_bytes: 5 * 1024 * 1024, max_pages: 500 })
  mocks.documentsApi.content.mockResolvedValue(documentContent)
  mocks.documentsApi.chunks.mockResolvedValue(chunkList)
})
afterEach(() => vi.useRealTimers())

const userWithTimers = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

describe('Documento em processamento', () => {
  it('mostra que está aguardando, sem oferecer reprocessamento, e explica o que falta', async () => {
    mocks.documentsApi.get.mockResolvedValue(pending)
    mocks.documentsApi.content.mockResolvedValue(emptyContent)
    renderApp('/documents/d1')
    expect(await screen.findByText(/Aguardando processamento\. O texto e os trechos serão gerados em segundo plano/)).toBeInTheDocument()
    expect(screen.getByText('Aguardando processamento', { selector: 'span' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reprocessar' })).not.toBeInTheDocument()
    expect(await screen.findByText('O texto aparecerá aqui quando o processamento terminar.')).toBeInTheDocument()
    expect(screen.getByText('Os trechos serão gerados quando o processamento terminar.')).toBeInTheDocument()
    expect(screen.queryByText('Concluído')).not.toBeInTheDocument() // não anuncia conclusão antes da hora
  })

  it('acompanha pending -> processing -> completed e atualiza páginas e trechos ao concluir', async () => {
    mocks.documentsApi.get.mockResolvedValueOnce(pending).mockResolvedValueOnce(processing).mockResolvedValue(completed)
    mocks.documentsApi.content.mockResolvedValueOnce(emptyContent).mockResolvedValueOnce(emptyContent).mockResolvedValue(documentContent)
    renderApp('/documents/d1')

    expect(await screen.findByText(/Aguardando processamento\./)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Trechos (0)' })).toBeInTheDocument()

    await tick()
    expect(await screen.findByText(/Processando: extraindo o texto/)).toBeInTheDocument()
    expect(screen.queryByText('Concluído')).not.toBeInTheDocument()

    await tick()
    expect(await screen.findByText('Concluído', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Trechos (3)' })).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Página 2' })).toHaveTextContent('Cláusula de rescisão')
    expect(screen.queryByText(/Aguardando processamento\./)).not.toBeInTheDocument()
  })

  it('para de consultar ao chegar a um estado terminal', async () => {
    mocks.documentsApi.get.mockResolvedValueOnce(processing).mockResolvedValue(completed)
    renderApp('/documents/d1')
    await screen.findByText(/Processando: extraindo o texto/)
    await tick()
    await screen.findByText('Concluído', { selector: 'span' })
    const calls = mocks.documentsApi.get.mock.calls.length
    await tick(POLL * 10)
    expect(mocks.documentsApi.get.mock.calls.length).toBe(calls) // sem polling desnecessário
  })

  it('não faz polling para documento já concluído ou com falha', async () => {
    mocks.documentsApi.get.mockResolvedValue(completed)
    const { unmount } = renderApp('/documents/d1')
    await screen.findByRole('heading', { name: 'Contrato de serviço' })
    await tick(POLL * 5)
    expect(mocks.documentsApi.get).toHaveBeenCalledTimes(1)
    unmount()

    mocks.documentsApi.get.mockClear()
    mocks.documentsApi.get.mockResolvedValue(failed)
    renderApp('/documents/d1')
    await screen.findByText(/O processamento falhou/)
    await tick(POLL * 5)
    expect(mocks.documentsApi.get).toHaveBeenCalledTimes(1)
  })

  it('limpa o timer ao sair da página', async () => {
    mocks.documentsApi.get.mockResolvedValue(pending)
    const { unmount } = renderApp('/documents/d1')
    await screen.findByText(/Aguardando processamento\./)
    await tick()
    const calls = mocks.documentsApi.get.mock.calls.length
    expect(calls).toBeGreaterThan(1) // estava consultando
    unmount()
    await tick(POLL * 10)
    expect(mocks.documentsApi.get.mock.calls.length).toBe(calls) // nenhuma consulta depois de desmontar
    expect(vi.getTimerCount()).toBe(0)
  })

  it('recarrega a lista de trechos aberta quando o reprocessamento termina', async () => {
    const user = userWithTimers()
    const newChunks = { ...chunkList, total: 5, items: [{ ...chunkList.items[0], id: 'n0', content: 'Trecho da NOVA versão.' }] }
    mocks.documentsApi.get.mockResolvedValueOnce({ ...processing, chunk_count: 3 }).mockResolvedValue({ ...completed, chunk_count: 5 })
    mocks.documentsApi.chunks.mockResolvedValueOnce(chunkList).mockResolvedValue(newChunks)
    renderApp('/documents/d1')

    await user.click(await screen.findByRole('button', { name: 'Mostrar trechos' }))
    expect(await screen.findByText('Primeiro trecho da página um.')).toBeInTheDocument() // versão anterior ainda visível

    await tick()
    expect(await screen.findByRole('heading', { name: 'Trechos (5)' })).toBeInTheDocument()
    expect(await screen.findByText('Trecho da NOVA versão.')).toBeInTheDocument()
    expect(screen.queryByText('Primeiro trecho da página um.')).not.toBeInTheDocument()
  })
})

describe('Falha e reprocessamento', () => {
  it('mostra a falha com a mensagem e oferece reprocessar, mantendo o download', async () => {
    mocks.documentsApi.get.mockResolvedValue(failed)
    mocks.documentsApi.content.mockResolvedValue({ ...documentContent, pages: [], status: 'failed', has_text: false })
    renderApp('/documents/d1')
    expect(await screen.findByText(/O processamento falhou\. Não foi possível extrair o texto do PDF \(RuntimeError\)\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reprocessar' })).toBeEnabled()
    expect(screen.getByRole('link', { name: /Baixar original/ })).toHaveAttribute('href', '/api/documents/d1/file')
    expect(screen.getByText('Falhou', { selector: 'span' })).toBeInTheDocument()
  })

  it('mostra o conteúdo da versão anterior mesmo com a nova tentativa falha', async () => {
    mocks.documentsApi.get.mockResolvedValue({ ...failed, chunk_count: 3, error_message: 'Não foi possível extrair o texto do PDF (RuntimeError). A versão anterior foi mantida.' })
    renderApp('/documents/d1')
    expect(await screen.findByText(/A versão anterior foi mantida\./)).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Página 1' })).toHaveTextContent('Texto da primeira página')
    expect(screen.getByRole('heading', { name: 'Trechos (3)' })).toBeInTheDocument()
  })

  it('solicita o reprocessamento uma única vez, bloqueia cliques repetidos e passa a acompanhar o estado', async () => {
    const user = userWithTimers()
    let accept: (d: DocumentItem) => void = () => {}
    mocks.documentsApi.get.mockResolvedValueOnce(failed).mockResolvedValueOnce(pending).mockResolvedValue(completed)
    mocks.documentsApi.reprocess.mockReturnValue(new Promise<DocumentItem>((r) => (accept = r)))
    renderApp('/documents/d1')

    const button = await screen.findByRole('button', { name: 'Reprocessar' })
    await user.click(button)
    await user.click(screen.getByRole('button', { name: 'Solicitando…' }))
    await user.keyboard('{Enter}')
    expect(mocks.documentsApi.reprocess).toHaveBeenCalledTimes(1)
    expect(mocks.documentsApi.reprocess).toHaveBeenCalledWith('d1')
    expect(screen.getByRole('button', { name: 'Solicitando…' })).toBeDisabled()

    accept(pending)
    expect(await screen.findByText(/Reprocessamento solicitado/)).toBeInTheDocument()
    expect(await screen.findByText(/Aguardando processamento\./)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reprocessar' })).not.toBeInTheDocument()

    await tick()
    expect(await screen.findByText('Concluído', { selector: 'span' })).toBeInTheDocument()
    expect(mocks.documentsApi.reprocess).toHaveBeenCalledTimes(1)
  })

  it('mostra o 409 da API (já em processamento) e libera nova tentativa', async () => {
    const { ApiError } = await import('../services/api')
    const user = userWithTimers()
    mocks.documentsApi.get.mockResolvedValue(failed)
    mocks.documentsApi.reprocess.mockRejectedValue(
      new ApiError('O documento já está aguardando ou em processamento.', 409, { code: 'already_processing', status: 'processing' }),
    )
    renderApp('/documents/d1')
    await user.click(await screen.findByRole('button', { name: 'Reprocessar' }))
    expect(await screen.findByText('O documento já está aguardando ou em processamento.')).toBeInTheDocument()
    expect(screen.queryByText(/Reprocessamento solicitado/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reprocessar' })).toBeEnabled()
  })

  it('mostra erro de rede ao solicitar e permite tentar de novo', async () => {
    const { ApiError } = await import('../services/api')
    const user = userWithTimers()
    mocks.documentsApi.get.mockResolvedValue(failed)
    mocks.documentsApi.reprocess.mockRejectedValueOnce(new ApiError('Não foi possível conectar ao backend.', 0))
    renderApp('/documents/d1')
    await user.click(await screen.findByRole('button', { name: 'Reprocessar' }))
    expect(await screen.findByText('Não foi possível conectar ao backend.', { selector: 'p' })).toBeInTheDocument()

    mocks.documentsApi.reprocess.mockResolvedValueOnce(pending)
    await user.click(screen.getByRole('button', { name: 'Reprocessar' }))
    await vi.waitFor(() => expect(mocks.documentsApi.reprocess).toHaveBeenCalledTimes(2))
  })

  it('arquivo original ausente: mostra a mensagem segura da API', async () => {
    const { ApiError } = await import('../services/api')
    const user = userWithTimers()
    mocks.documentsApi.get.mockResolvedValue(failed)
    mocks.documentsApi.reprocess.mockRejectedValue(
      new ApiError('O arquivo original deste documento não foi encontrado no armazenamento; não é possível reprocessar.', 409, { code: 'original_file_missing' }),
    )
    renderApp('/documents/d1')
    await user.click(await screen.findByRole('button', { name: 'Reprocessar' }))
    expect(await screen.findByText(/não foi encontrado no armazenamento/)).toBeInTheDocument()
  })
})

describe('Erros de rede durante o acompanhamento', () => {
  it('mantém a página, avisa e continua tentando; ao voltar, atualiza', async () => {
    const { ApiError } = await import('../services/api')
    mocks.documentsApi.get
      .mockResolvedValueOnce(pending)
      .mockRejectedValueOnce(new ApiError('Não foi possível conectar ao backend.', 0))
      .mockResolvedValue(completed)
    renderApp('/documents/d1')
    await screen.findByText(/Aguardando processamento\./)

    await tick()
    expect(await screen.findByText(/Não foi possível atualizar o estado: Não foi possível conectar/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Contrato de serviço' })).toBeInTheDocument() // a página não some

    await tick(POLL * 2)
    expect(await screen.findByText('Concluído', { selector: 'span' })).toBeInTheDocument()
    expect(screen.queryByText(/Não foi possível atualizar o estado/)).not.toBeInTheDocument()
  })

  it('pausa após falhas seguidas e retoma pelo botão', async () => {
    const { ApiError } = await import('../services/api')
    const user = userWithTimers()
    mocks.documentsApi.get.mockResolvedValueOnce(pending).mockRejectedValue(new ApiError('Não foi possível conectar ao backend.', 0))
    renderApp('/documents/d1')
    await screen.findByText(/Aguardando processamento\./)

    for (let i = 0; i < 8; i++) await tick() // um ciclo por vez, como no navegador
    expect(await screen.findByText(/Atualização automática pausada/)).toBeInTheDocument()
    const calls = mocks.documentsApi.get.mock.calls.length
    await tick(POLL * 10)
    expect(mocks.documentsApi.get.mock.calls.length).toBe(calls) // pausado: não bate mais no servidor

    mocks.documentsApi.get.mockReset()
    mocks.documentsApi.get.mockResolvedValue(completed)
    await user.click(screen.getByRole('button', { name: 'Atualizar agora' }))
    expect(await screen.findByText('Concluído', { selector: 'span' })).toBeInTheDocument()
  })
})

describe('Lista e importação', () => {
  it('atualiza a lista sozinha enquanto houver documento em processamento e para depois', async () => {
    mocks.documentsApi.list.mockResolvedValueOnce(documentPage([pending])).mockResolvedValue(documentPage([completed]))
    renderApp('/documents')
    const card = await screen.findByRole('article')
    expect(within(card).getByText('Aguardando processamento')).toBeInTheDocument()

    await tick(3000)
    expect(await screen.findByText('Concluído', { selector: 'span' })).toBeInTheDocument()
    const calls = mocks.documentsApi.list.mock.calls.length
    await tick(30000)
    expect(mocks.documentsApi.list.mock.calls.length).toBe(calls)
  })

  it('não faz polling na lista quando todos os documentos estão em estado terminal', async () => {
    mocks.documentsApi.list.mockResolvedValue(documentPage([completed, failed]))
    renderApp('/documents')
    await screen.findByText('Falhou', { selector: 'span' })
    await tick(30000)
    expect(mocks.documentsApi.list).toHaveBeenCalledTimes(1)
  })

  it('após o upload, abre o documento aceito mostrando que o processamento está em andamento', async () => {
    const user = userWithTimers()
    mocks.documentsApi.upload.mockResolvedValue({ ...pending, id: 'd9' })
    mocks.documentsApi.get.mockResolvedValue({ ...pending, id: 'd9' })
    const { router } = renderApp('/documents/new')
    await user.upload(await screen.findByLabelText('Arquivo PDF'), new File([new Uint8Array(100)], 'novo.pdf', { type: 'application/pdf' }))
    await user.click(screen.getByRole('button', { name: 'Importar documento' }))

    expect(await screen.findByText('Documento recebido. O texto está sendo extraído em segundo plano.')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/documents/d9')
    expect(await screen.findByText(/Aguardando processamento\./)).toBeInTheDocument()
  })
})
