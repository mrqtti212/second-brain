import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mocks } from '../test/apiMock'
import { category, documentResult, page, project, result, tagPython, tagWeb } from '../test/fixtures'
import { renderApp } from '../test/render'

vi.mock('../services/api', async (importOriginal) => ({ ...(await importOriginal<object>()), ...(await import('../test/apiMock')).mocks }))

beforeEach(() => {
  mocks.api.health.mockResolvedValue({ status: 'ok', database: 'ok' })
  mocks.documentsApi.list.mockResolvedValue({ items: [], total: 0, limit: 4, offset: 0 })
  mocks.categoriesApi.list.mockResolvedValue([category])
  mocks.projectsApi.list.mockResolvedValue([project])
  mocks.tagsApi.list.mockResolvedValue([tagPython, tagWeb])
  mocks.api.search.mockResolvedValue(page([result()]))
})

describe('Biblioteca', () => {
  it('mostra carregamento e depois as notas vindas da API', async () => {
    renderApp('/library')
    expect(screen.getByRole('status')).toHaveTextContent('Carregando')
    expect(await screen.findByRole('link', { name: 'Guia de Python' })).toHaveAttribute('href', '/notes/n1')
    expect(screen.getByText('1 resultado')).toBeInTheDocument()
    // indicadores de categoria, projeto e etiqueta, e termo destacado
    const card = screen.getByRole('article')
    expect(within(card).getByText('Estudos')).toBeInTheDocument()
    expect(within(card).getByText('Projeto: Tese')).toBeInTheDocument()
    expect(within(card).getByText('#python')).toBeInTheDocument()
    expect(card.querySelector('mark')).toHaveTextContent('python')
  })

  it('mostra notas e documentos juntos, identificados, com link para cada tipo', async () => {
    mocks.api.search.mockResolvedValue(page([result(), documentResult()]))
    renderApp('/library')
    expect(await screen.findByRole('link', { name: 'Contrato de serviço' })).toHaveAttribute('href', '/documents/d1')
    expect(screen.getByRole('link', { name: 'Guia de Python' })).toHaveAttribute('href', '/notes/n1')
    const cards = screen.getAllByRole('article')
    expect(within(cards[0]).getByText('Nota')).toBeInTheDocument()
    expect(within(cards[1]).getByText('Documento PDF')).toBeInTheDocument()
    expect(within(cards[1]).getByText('Concluído')).toBeInTheDocument()
    expect(within(cards[1]).getByText(/2 páginas/)).toBeInTheDocument()
    expect(cards[1].querySelector('mark')).toHaveTextContent('rescisão')
  })

  it('filtra por tipo de conteúdo no servidor', async () => {
    const user = userEvent.setup()
    renderApp('/library')
    await screen.findByRole('link', { name: 'Guia de Python' })

    await user.click(screen.getByRole('radio', { name: 'Documentos' }))
    await waitFor(() => expect(mocks.api.search).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'document' })))
    await user.click(screen.getByRole('radio', { name: 'Notas' }))
    await waitFor(() => expect(mocks.api.search).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'note' })))
    await user.click(screen.getByRole('radio', { name: 'Tudo' }))
    await waitFor(() => expect(mocks.api.search).toHaveBeenLastCalledWith(expect.objectContaining({ type: undefined })))
  })

  it('tem atalho para importar PDF', async () => {
    renderApp('/library')
    expect(await screen.findByRole('link', { name: 'Importar PDF' })).toHaveAttribute('href', '/documents/new')
  })

  it('busca no servidor com o termo digitado', async () => {
    const user = userEvent.setup()
    renderApp('/library')
    await screen.findByRole('link', { name: 'Guia de Python' })

    mocks.api.search.mockResolvedValue(page([result({ title: 'Receita' })]))
    await user.type(screen.getByRole('searchbox', { name: 'Buscar' }), 'bolo')

    await waitFor(() => expect(mocks.api.search).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'bolo', offset: 0 })))
    expect(await screen.findByRole('link', { name: 'Receita' })).toBeInTheDocument()
    expect(screen.getByText(/para “bolo”/)).toBeInTheDocument()
  })

  it('envia filtros de categoria, projeto e etiquetas para a API', async () => {
    const user = userEvent.setup()
    renderApp('/library')
    await screen.findByRole('link', { name: 'Guia de Python' })

    await user.selectOptions(screen.getByLabelText('Categoria'), 'c1')
    await user.selectOptions(screen.getByLabelText('Projeto'), 'p1')
    await user.click(screen.getByRole('button', { name: '#python' }))
    await user.click(screen.getByRole('button', { name: '#web' }))

    await waitFor(() =>
      expect(mocks.api.search).toHaveBeenLastCalledWith(
        expect.objectContaining({ category_id: 'c1', project_id: 'p1', tag_id: ['t1', 't2'] }),
      ),
    )
    expect(screen.getByRole('button', { name: '#python' })).toHaveAttribute('aria-pressed', 'true')

    // limpar filtros volta à listagem completa
    await user.click(screen.getByRole('button', { name: 'Limpar filtros' }))
    await waitFor(() => expect(mocks.api.search).toHaveBeenLastCalledWith(expect.objectContaining({ category_id: undefined, tag_id: [] })))
  })

  it('aplica filtros presentes na URL', async () => {
    renderApp('/library?q=python&category=c1&tag=t1')
    await screen.findByRole('link', { name: 'Guia de Python' })
    expect(mocks.api.search).toHaveBeenCalledWith(expect.objectContaining({ q: 'python', category_id: 'c1', tag_id: ['t1'] }))
    expect(screen.getByLabelText('Categoria')).toHaveValue('c1')
  })

  it('mostra estado vazio com filtros e com biblioteca vazia', async () => {
    mocks.api.search.mockResolvedValue(page([]))
    renderApp('/library?q=nada')
    expect(await screen.findByText('Nada encontrado com esses critérios.')).toBeInTheDocument()
  })

  it('mostra biblioteca vazia sem filtros', async () => {
    mocks.api.search.mockResolvedValue(page([]))
    renderApp('/library')
    expect(await screen.findByText('Sua biblioteca está vazia. Crie uma nota ou importe um PDF.')).toBeInTheDocument()
  })

  it('mostra erro de comunicação e permite tentar de novo', async () => {
    const { ApiError } = await import('../services/api')
    const user = userEvent.setup()
    mocks.api.search.mockRejectedValueOnce(new ApiError('Não foi possível conectar ao backend.', 0))
    renderApp('/library')

    const alert = await screen.findByText('Não foi possível conectar ao backend.', { selector: 'span' })
    expect(alert).toBeInTheDocument()
    // nenhum dado de demonstração na biblioteca
    expect(screen.queryByText(/demonstração/i)).not.toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'Tentar novamente' })[0])
    expect(await screen.findByRole('link', { name: 'Guia de Python' })).toBeInTheDocument()
  })

  it('pagina pelo servidor', async () => {
    const user = userEvent.setup()
    mocks.api.search.mockResolvedValue(page([result()], 30))
    renderApp('/library')
    await screen.findByText('Página 1 de 3')
    expect(screen.getByRole('button', { name: 'Anterior' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Próxima' }))
    await waitFor(() => expect(mocks.api.search).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 12, limit: 12 })))
    expect(await screen.findByText('Página 2 de 3')).toBeInTheDocument()
  })
})
