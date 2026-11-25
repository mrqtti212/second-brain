import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mocks } from '../test/apiMock'
import { category, chunkList, documentContent, documentItem, documentPage, project, tagPython, tagWeb } from '../test/fixtures'
import { renderApp } from '../test/render'

vi.mock('../services/api', async (importOriginal) => ({ ...(await importOriginal<object>()), ...(await import('../test/apiMock')).mocks }))

const MB = 1024 * 1024
const pdf = (name = 'relatorio.pdf', size = 1000) => new File([new Uint8Array(size)], name, { type: 'application/pdf' })

beforeEach(() => {
  mocks.api.health.mockResolvedValue({ status: 'ok', database: 'ok' })
  mocks.categoriesApi.list.mockResolvedValue([category])
  mocks.projectsApi.list.mockResolvedValue([project])
  mocks.tagsApi.list.mockResolvedValue([tagPython, tagWeb])
  mocks.documentsApi.limits.mockResolvedValue({ max_upload_bytes: 5 * MB, max_pages: 500 })
  mocks.documentsApi.list.mockResolvedValue(documentPage([documentItem]))
  mocks.documentsApi.get.mockResolvedValue(documentItem)
  mocks.documentsApi.content.mockResolvedValue(documentContent)
  mocks.documentsApi.chunks.mockResolvedValue(chunkList)
})

describe('Importar PDF', () => {
  async function pick(user: ReturnType<typeof userEvent.setup>, file: File) {
    const input = await screen.findByLabelText('Arquivo PDF')
    await user.upload(input, file)
  }

  it('rejeita formato diferente de PDF antes de enviar', async () => {
    const user = userEvent.setup({ applyAccept: false })
    renderApp('/documents/new')
    await pick(user, new File(['x'], 'foto.png', { type: 'image/png' }))
    expect(await screen.findByText('Formato não suportado. Selecione um arquivo PDF.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Importar documento' }))
    expect(mocks.documentsApi.upload).not.toHaveBeenCalled()
  })

  it('rejeita arquivo vazio e arquivo acima do limite', async () => {
    const user = userEvent.setup()
    renderApp('/documents/new')
    await screen.findByText('Tamanho máximo: 5,0 MB.')

    await pick(user, pdf('vazio.pdf', 0))
    expect(await screen.findByText('O arquivo está vazio.')).toBeInTheDocument()

    await pick(user, pdf('grande.pdf', 6 * MB))
    expect(await screen.findByText('O arquivo tem 6,0 MB; o limite é 5,0 MB.')).toBeInTheDocument()
    expect(mocks.documentsApi.upload).not.toHaveBeenCalled()
  })

  it('exige a escolha de um arquivo', async () => {
    const user = userEvent.setup()
    renderApp('/documents/new')
    await user.click(await screen.findByRole('button', { name: 'Importar documento' }))
    expect(await screen.findByText('Selecione um arquivo PDF.')).toBeInTheDocument()
    expect(mocks.documentsApi.upload).not.toHaveBeenCalled()
  })

  it('envia arquivo e metadados, bloqueia envio duplicado e só mostra sucesso após a API responder', async () => {
    const user = userEvent.setup()
    let finish: (d: typeof documentItem) => void = () => {}
    mocks.documentsApi.upload.mockReturnValue(new Promise((r) => (finish = r)))
    const { router } = renderApp('/documents/new')

    await pick(user, pdf('relatorio.pdf'))
    await user.type(screen.getByLabelText('Título (opcional)'), '  Meu relatório ')
    await screen.findByRole('option', { name: 'Estudos' })
    await user.selectOptions(screen.getByLabelText('Categoria'), 'c1')
    await user.selectOptions(screen.getByLabelText('Projeto'), 'p1')
    await user.click(await screen.findByRole('button', { name: '#web' }))

    const submit = screen.getByRole('button', { name: 'Importar documento' })
    await user.click(submit)
    await user.click(screen.getByRole('button', { name: 'Enviando…' })) // segundo clique
    await user.keyboard('{Enter}')

    expect(mocks.documentsApi.upload).toHaveBeenCalledTimes(1)
    const form = mocks.documentsApi.upload.mock.calls[0][0] as FormData
    expect((form.get('file') as File).name).toBe('relatorio.pdf')
    expect(form.get('title')).toBe('Meu relatório')
    expect(form.get('category_id')).toBe('c1')
    expect(form.get('project_id')).toBe('p1')
    expect(form.getAll('tag_ids')).toEqual(['t2'])

    // em andamento: botão travado, campos desabilitados, sem sucesso, sem navegação
    expect(screen.getByRole('button', { name: 'Enviando…' })).toBeDisabled()
    expect(screen.getByLabelText('Título (opcional)')).toBeDisabled()
    expect(screen.queryByText('Documento recebido. O texto está sendo extraído em segundo plano.')).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/documents/new')

    finish({ ...documentItem, id: 'd9' })
    expect(await screen.findByText('Documento recebido. O texto está sendo extraído em segundo plano.')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/documents/d9')
  })

  it('mostra o erro do servidor, mantém o arquivo e libera novo envio', async () => {
    const { ApiError } = await import('../services/api')
    const user = userEvent.setup()
    mocks.documentsApi.upload.mockRejectedValueOnce(new ApiError('O PDF está corrompido ou não pôde ser lido.', 422))
    const { router } = renderApp('/documents/new')
    await pick(user, pdf())
    await user.click(screen.getByRole('button', { name: 'Importar documento' }))

    expect(await screen.findByText('O PDF está corrompido ou não pôde ser lido.')).toBeInTheDocument()
    expect(screen.queryByText('Documento recebido. O texto está sendo extraído em segundo plano.')).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/documents/new')

    mocks.documentsApi.upload.mockResolvedValueOnce({ ...documentItem, id: 'd2' })
    await user.click(screen.getByRole('button', { name: 'Importar documento' }))
    expect(await screen.findByText('Documento recebido. O texto está sendo extraído em segundo plano.')).toBeInTheDocument()
    expect(mocks.documentsApi.upload).toHaveBeenCalledTimes(2)
  })

  it('cancelar volta para a lista sem enviar', async () => {
    const user = userEvent.setup()
    const { router } = renderApp('/documents/new')
    await user.click(await screen.findByRole('button', { name: 'Cancelar' }))
    expect(router.state.location.pathname).toBe('/documents')
    expect(mocks.documentsApi.upload).not.toHaveBeenCalled()
  })
})

describe('Lista de documentos', () => {
  it('mostra carregamento e depois documentos reais com estado, páginas e data', async () => {
    renderApp('/documents')
    expect(screen.getByRole('status')).toHaveTextContent('Carregando')
    expect(await screen.findByRole('link', { name: 'Contrato de serviço' })).toHaveAttribute('href', '/documents/d1')
    const card = screen.getByRole('article')
    expect(within(card).getByText('Concluído')).toBeInTheDocument()
    expect(within(card).getByText(/contrato\.pdf · 2 KB · 2 páginas/)).toBeInTheDocument()
    expect(within(card).getByText(/Importado em/)).toBeInTheDocument()
    expect(screen.getByText('1 documento')).toBeInTheDocument()
    expect(screen.queryByText(/demonstração/i)).not.toBeInTheDocument()
  })

  it('identifica documentos com falha e sem texto', async () => {
    mocks.documentsApi.list.mockResolvedValue(
      documentPage([
        { ...documentItem, id: 'a', title: 'Quebrado', status: 'failed', has_text: false },
        { ...documentItem, id: 'b', title: 'Escaneado', has_text: false },
      ]),
    )
    renderApp('/documents')
    expect(await screen.findByText('Falhou')).toBeInTheDocument()
    expect(screen.getByText('Sem texto extraível')).toBeInTheDocument()
  })

  it('busca pelo nome e filtra no servidor', async () => {
    const user = userEvent.setup()
    renderApp('/documents')
    await screen.findByRole('link', { name: 'Contrato de serviço' })

    await user.type(screen.getByRole('searchbox', { name: 'Buscar pelo nome' }), 'fatura')
    await waitFor(() => expect(mocks.documentsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'fatura', offset: 0 })))
    await user.selectOptions(screen.getByLabelText('Categoria'), 'c1')
    await user.click(screen.getByRole('button', { name: '#python' }))
    await waitFor(() =>
      expect(mocks.documentsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'fatura', category_id: 'c1', tag_id: ['t1'] })),
    )
  })

  it('mostra estado vazio, erro com nova tentativa e paginação', async () => {
    const { ApiError } = await import('../services/api')
    const user = userEvent.setup()
    mocks.documentsApi.list.mockResolvedValueOnce(documentPage([]))
    const { unmount } = renderApp('/documents')
    expect(await screen.findByText(/Nenhum documento importado ainda/)).toBeInTheDocument()
    unmount()

    mocks.documentsApi.list.mockRejectedValueOnce(new ApiError('Erro 500', 500))
    renderApp('/documents')
    expect(await screen.findByText('Erro 500')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Tentar novamente' }))
    expect(await screen.findByRole('link', { name: 'Contrato de serviço' })).toBeInTheDocument()
  })

  it('pagina pelo servidor', async () => {
    const user = userEvent.setup()
    mocks.documentsApi.list.mockResolvedValue(documentPage([documentItem], 30))
    renderApp('/documents')
    await screen.findByText('Página 1 de 3')
    await user.click(screen.getByRole('button', { name: 'Próxima' }))
    await waitFor(() => expect(mocks.documentsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 12 })))
  })
})

describe('Visualização do documento', () => {
  it('mostra metadados, organização e o texto extraído página a página', async () => {
    renderApp('/documents/d1')
    expect(await screen.findByRole('heading', { name: 'Contrato de serviço' })).toBeInTheDocument()
    expect(screen.getByText('contrato.pdf')).toBeInTheDocument()
    expect(screen.getByText('2 KB')).toBeInTheDocument()
    expect(screen.getByText('Estudos')).toBeInTheDocument()

    const first = await screen.findByRole('region', { name: 'Página 1' })
    expect(within(first).getByText('Texto da primeira página')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Página 2' })).getByText('Cláusula de rescisão')).toBeInTheDocument()
  })

  it('oferece o download do original pela API', async () => {
    renderApp('/documents/d1')
    const link = await screen.findByRole('link', { name: /Baixar original/ })
    expect(link).toHaveAttribute('href', '/api/documents/d1/file')
    expect(link).toHaveAttribute('download')
  })

  it('explica quando o PDF não tem texto extraível (sem tratar como erro)', async () => {
    mocks.documentsApi.get.mockResolvedValue({ ...documentItem, has_text: false })
    mocks.documentsApi.content.mockResolvedValue({ ...documentContent, has_text: false, pages: [{ page_number: 1, text: '' }] })
    renderApp('/documents/d1')
    expect(await screen.findByText(/não tem texto extraível/)).toBeInTheDocument()
    expect(await screen.findByText('(sem texto nesta página)')).toBeInTheDocument()
    expect(screen.queryByText(/O processamento falhou/)).not.toBeInTheDocument()
  })

  it('mostra falha de processamento e mantém o download disponível', async () => {
    mocks.documentsApi.get.mockResolvedValue({ ...documentItem, status: 'failed', has_text: false, error_message: 'Falha de leitura (RuntimeError).' })
    mocks.documentsApi.content.mockResolvedValue({ ...documentContent, status: 'failed', has_text: false, pages: [] })
    renderApp('/documents/d1')
    expect(await screen.findByText(/O processamento falhou\. Falha de leitura \(RuntimeError\)\./)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Baixar original/ })).toBeInTheDocument()
    expect(await screen.findByText('Nenhum texto foi extraído.')).toBeInTheDocument()
  })

  it('indica processamento em andamento', async () => {
    mocks.documentsApi.get.mockResolvedValue({ ...documentItem, status: 'processing' })
    renderApp('/documents/d1')
    expect(await screen.findByText(/Processando: extraindo o texto e gerando os trechos/)).toBeInTheDocument()
    expect(screen.getByText('Processando…', { selector: 'span' })).toBeInTheDocument()
  })

  it('mostra erro quando o documento não existe e quando o conteúdo falha', async () => {
    const { ApiError } = await import('../services/api')
    mocks.documentsApi.get.mockRejectedValueOnce(new ApiError('Documento não encontrado.', 404))
    const { unmount } = renderApp('/documents/zzz')
    expect(await screen.findByText('Documento não encontrado.')).toBeInTheDocument()
    unmount()

    mocks.documentsApi.content.mockRejectedValueOnce(new ApiError('Erro 500', 500))
    renderApp('/documents/d1')
    expect(await screen.findByText('Erro 500')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Contrato de serviço' })).toBeInTheDocument() // metadados seguem visíveis
  })

  it('exclusão pede confirmação; cancelar não exclui', async () => {
    const user = userEvent.setup()
    renderApp('/documents/d1')
    await user.click(await screen.findByRole('button', { name: /Excluir/ }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('Excluir documento?')
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(mocks.documentsApi.remove).not.toHaveBeenCalled()
  })

  it('confirmar exclui via API e só então mostra o sucesso na lista', async () => {
    const user = userEvent.setup()
    let finish: () => void = () => {}
    mocks.documentsApi.remove.mockReturnValue(new Promise<void>((r) => (finish = r)))
    const { router } = renderApp('/documents/d1')
    await user.click(await screen.findByRole('button', { name: /Excluir/ }))
    await user.click(screen.getByRole('button', { name: 'Excluir documento' }))

    expect(mocks.documentsApi.remove).toHaveBeenCalledWith('d1')
    expect(screen.queryByText('Documento excluído.')).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/documents/d1')

    finish()
    expect(await screen.findByText('Documento excluído.')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/documents')
  })

  it('falha na exclusão mantém o diálogo com o erro e não navega', async () => {
    const user = userEvent.setup()
    mocks.documentsApi.remove.mockRejectedValue(new Error('Não foi possível remover o arquivo do documento.'))
    const { router } = renderApp('/documents/d1')
    await user.click(await screen.findByRole('button', { name: /Excluir/ }))
    await user.click(screen.getByRole('button', { name: 'Excluir documento' }))
    expect(await screen.findByText('Não foi possível remover o arquivo do documento.')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/documents/d1')
  })
})


describe('Trechos do documento', () => {
  it('mostra a quantidade de páginas e de trechos nos metadados', async () => {
    renderApp('/documents/d1')
    await screen.findByRole('heading', { name: 'Contrato de serviço' })
    const meta = screen.getByText('Trechos', { selector: 'dt' }).parentElement as HTMLElement
    expect(within(meta).getByText('3')).toBeInTheDocument()
    expect(within(screen.getByText('Páginas', { selector: 'dt' }).parentElement as HTMLElement).getByText('2')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Trechos (3)' })).toBeInTheDocument()
  })

  it('só carrega os trechos quando o usuário pede, e mostra a página de origem de cada um', async () => {
    const user = userEvent.setup()
    renderApp('/documents/d1')
    await screen.findByRole('heading', { name: 'Trechos (3)' })
    expect(mocks.documentsApi.chunks).not.toHaveBeenCalled()

    const toggle = screen.getByRole('button', { name: 'Mostrar trechos' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)

    const first = await screen.findByRole('article', { name: 'Trecho 1' })
    expect(within(first).getByText('Primeiro trecho da página um.')).toBeInTheDocument()
    expect(within(first).getByText('Página 1')).toBeInTheDocument()
    expect(within(first).getByText('29 caracteres')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'Trecho 2' })).getByText('Página 1')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'Trecho 3' })).getByText('Página 2')).toBeInTheDocument()
    expect(mocks.documentsApi.chunks).toHaveBeenCalledWith('d1', { limit: 20, offset: 0 })
    expect(screen.getByRole('button', { name: 'Ocultar trechos' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('mantém o texto extraído por página ao lado dos trechos', async () => {
    renderApp('/documents/d1')
    expect(await screen.findByRole('region', { name: 'Página 1' })).toHaveTextContent('Texto da primeira página')
    expect(screen.getByRole('region', { name: 'Página 2' })).toHaveTextContent('Cláusula de rescisão')
  })

  it('pagina os trechos pelo servidor', async () => {
    const user = userEvent.setup()
    mocks.documentsApi.get.mockResolvedValue({ ...documentItem, chunk_count: 45 })
    mocks.documentsApi.chunks.mockResolvedValue({ ...chunkList, total: 45 })
    renderApp('/documents/d1')
    await user.click(await screen.findByRole('button', { name: 'Mostrar trechos' }))
    await screen.findByText('Página 1 de 3')
    await user.click(screen.getByRole('button', { name: 'Próxima' }))
    await waitFor(() => expect(mocks.documentsApi.chunks).toHaveBeenLastCalledWith('d1', { limit: 20, offset: 20 }))
  })

  it('mostra erro ao carregar trechos, com nova tentativa', async () => {
    const { ApiError } = await import('../services/api')
    const user = userEvent.setup()
    mocks.documentsApi.chunks.mockRejectedValueOnce(new ApiError('Erro 500', 500))
    renderApp('/documents/d1')
    await user.click(await screen.findByRole('button', { name: 'Mostrar trechos' }))
    expect(await screen.findByText('Erro 500')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Tentar novamente' }))
    expect(await screen.findByRole('article', { name: 'Trecho 1' })).toBeInTheDocument()
  })

  it('explica a ausência de trechos conforme o caso', async () => {
    mocks.documentsApi.get.mockResolvedValueOnce({ ...documentItem, chunk_count: 0 })
    const { unmount } = renderApp('/documents/d1')
    expect(await screen.findByText(/Nenhum trecho gerado/)).toBeInTheDocument()
    expect(screen.getByText(/rebuild-chunks/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mostrar trechos' })).not.toBeInTheDocument()
    unmount()

    mocks.documentsApi.get.mockResolvedValueOnce({ ...documentItem, chunk_count: 0, has_text: false })
    renderApp('/documents/d1')
    expect(await screen.findByText(/o documento não tem texto extraído/)).toBeInTheDocument()
  })
})

describe('Edição dos metadados do documento', () => {
  async function openEditor(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole('button', { name: /Editar informações/ }))
    return screen.getByRole('form', { name: 'Editar informações do documento' })
  }

  it('abre com os valores atuais e envia título, categoria, projeto e etiquetas', async () => {
    const user = userEvent.setup()
    mocks.documentsApi.update.mockResolvedValue({ ...documentItem, title: 'Novo título' })
    renderApp('/documents/d1')
    const form = await openEditor(user)
    expect(within(form).getByLabelText('Título')).toHaveValue('Contrato de serviço')
    await waitFor(() => expect(within(form).getByLabelText('Categoria')).toHaveValue('c1'))
    expect(within(form).getByLabelText('Projeto')).toHaveValue('p1')
    expect(within(form).getByRole('button', { name: '#python' })).toHaveAttribute('aria-pressed', 'true')

    const title = within(form).getByLabelText('Título')
    await user.clear(title)
    await user.type(title, '  Novo título ')
    await user.click(within(form).getByRole('button', { name: '#web' }))
    await user.click(within(form).getByRole('button', { name: 'Salvar alterações' }))

    await waitFor(() =>
      expect(mocks.documentsApi.update).toHaveBeenCalledWith('d1', {
        title: 'Novo título',
        category_id: 'c1',
        project_id: 'p1',
        tag_ids: ['t1', 't2'],
      }),
    )
    expect(await screen.findByText('Informações atualizadas.')).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Editar informações do documento' })).not.toBeInTheDocument()
    expect(mocks.documentsApi.get).toHaveBeenCalledTimes(2) // recarregou os dados, sem novo upload
  })

  it('remove categoria, projeto e etiquetas', async () => {
    const user = userEvent.setup()
    mocks.documentsApi.update.mockResolvedValue(documentItem)
    renderApp('/documents/d1')
    const form = await openEditor(user)
    await waitFor(() => expect(within(form).getByLabelText('Categoria')).toHaveValue('c1'))
    await user.selectOptions(within(form).getByLabelText('Categoria'), '')
    await user.selectOptions(within(form).getByLabelText('Projeto'), '')
    await user.click(within(form).getByRole('button', { name: '#python' }))
    await user.click(within(form).getByRole('button', { name: 'Salvar alterações' }))
    await waitFor(() =>
      expect(mocks.documentsApi.update).toHaveBeenCalledWith('d1', expect.objectContaining({ category_id: null, project_id: null, tag_ids: [] })),
    )
  })

  it('valida título vazio sem chamar a API', async () => {
    const user = userEvent.setup()
    renderApp('/documents/d1')
    const form = await openEditor(user)
    await user.clear(within(form).getByLabelText('Título'))
    await user.click(within(form).getByRole('button', { name: 'Salvar alterações' }))
    expect(await within(form).findByText('Informe um título.')).toBeInTheDocument()
    expect(mocks.documentsApi.update).not.toHaveBeenCalled()
  })

  it('mostra o erro do servidor, mantém o formulário aberto e não anuncia sucesso', async () => {
    const { ApiError } = await import('../services/api')
    const user = userEvent.setup()
    mocks.documentsApi.update.mockRejectedValue(new ApiError('Categoria não encontrada.', 422))
    renderApp('/documents/d1')
    const form = await openEditor(user)
    await user.click(within(form).getByRole('button', { name: 'Salvar alterações' }))
    expect(await within(form).findByText('Categoria não encontrada.')).toBeInTheDocument()
    expect(screen.queryByText('Informações atualizadas.')).not.toBeInTheDocument()
    expect(within(form).getByRole('button', { name: 'Salvar alterações' })).toBeEnabled()
  })

  it('só anuncia sucesso depois que a API responde', async () => {
    const user = userEvent.setup()
    let finish: (d: typeof documentItem) => void = () => {}
    mocks.documentsApi.update.mockReturnValue(new Promise((r) => (finish = r)))
    renderApp('/documents/d1')
    const form = await openEditor(user)
    await user.click(within(form).getByRole('button', { name: 'Salvar alterações' }))
    expect(screen.getByRole('button', { name: 'Salvando…' })).toBeDisabled()
    expect(screen.queryByText('Informações atualizadas.')).not.toBeInTheDocument()
    finish(documentItem)
    expect(await screen.findByText('Informações atualizadas.')).toBeInTheDocument()
  })

  it('cancelar fecha o formulário sem salvar', async () => {
    const user = userEvent.setup()
    renderApp('/documents/d1')
    const form = await openEditor(user)
    await user.type(within(form).getByLabelText('Título'), ' alterado')
    await user.click(within(form).getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('form', { name: 'Editar informações do documento' })).not.toBeInTheDocument()
    expect(mocks.documentsApi.update).not.toHaveBeenCalled()
    expect(screen.getByRole('heading', { name: 'Contrato de serviço' })).toBeInTheDocument()
  })
})

describe('Importação de arquivo duplicado', () => {
  const duplicateError = async () => {
    const { ApiError } = await import('../services/api')
    return new ApiError('Este arquivo já foi importado.', 409, {
      detail: 'Este arquivo já foi importado.',
      code: 'duplicate_document',
      existing_document: { id: 'd1', title: 'Contrato de serviço', original_filename: 'contrato.pdf', created_at: '2026-11-20T12:00:00Z' },
    })
  }

  it('informa a duplicidade, não conta como importação e oferece o documento existente', async () => {
    const user = userEvent.setup()
    mocks.documentsApi.upload.mockRejectedValue(await duplicateError())
    const { router } = renderApp('/documents/new')
    await user.upload(await screen.findByLabelText('Arquivo PDF'), pdf('copia.pdf'))
    await user.click(screen.getByRole('button', { name: 'Importar documento' }))

    const alert = await screen.findByText(/Este arquivo já foi importado/, { selector: 'strong' })
    expect(alert.parentElement).toHaveTextContent('“Contrato de serviço” (contrato.pdf)')
    expect(alert.parentElement).toHaveTextContent('Nada foi importado de novo')
    expect(screen.queryByText('Documento recebido. O texto está sendo extraído em segundo plano.')).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/documents/new') // não navega sozinho
    expect(screen.getByRole('button', { name: 'Importar documento' })).toBeEnabled()
  })

  it('o link leva ao documento já existente', async () => {
    const user = userEvent.setup()
    mocks.documentsApi.upload.mockRejectedValue(await duplicateError())
    const { router } = renderApp('/documents/new')
    await user.upload(await screen.findByLabelText('Arquivo PDF'), pdf('copia.pdf'))
    await user.click(screen.getByRole('button', { name: 'Importar documento' }))

    await user.click(await screen.findByRole('link', { name: 'Abrir o documento existente' }))
    expect(router.state.location.pathname).toBe('/documents/d1')
    expect(await screen.findByRole('heading', { name: 'Contrato de serviço' })).toBeInTheDocument()
    expect(screen.queryByText('Documento recebido. O texto está sendo extraído em segundo plano.')).not.toBeInTheDocument()
  })

  it('escolher outro arquivo limpa o aviso de duplicidade', async () => {
    const user = userEvent.setup()
    mocks.documentsApi.upload.mockRejectedValue(await duplicateError())
    renderApp('/documents/new')
    const input = await screen.findByLabelText('Arquivo PDF')
    await user.upload(input, pdf('copia.pdf'))
    await user.click(screen.getByRole('button', { name: 'Importar documento' }))
    await screen.findByRole('link', { name: 'Abrir o documento existente' })
    await user.upload(input, pdf('outro.pdf'))
    expect(screen.queryByRole('link', { name: 'Abrir o documento existente' })).not.toBeInTheDocument()
  })

  it('um 409 que não é de duplicidade continua sendo um erro comum', async () => {
    const { ApiError } = await import('../services/api')
    const user = userEvent.setup()
    mocks.documentsApi.upload.mockRejectedValue(new ApiError('Conflito qualquer.', 409, { detail: 'Conflito qualquer.' }))
    renderApp('/documents/new')
    await user.upload(await screen.findByLabelText('Arquivo PDF'), pdf())
    await user.click(screen.getByRole('button', { name: 'Importar documento' }))
    expect(await screen.findByText('Conflito qualquer.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Abrir o documento existente' })).not.toBeInTheDocument()
  })
})
