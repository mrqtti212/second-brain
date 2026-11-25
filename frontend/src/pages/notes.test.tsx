import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mocks } from '../test/apiMock'
import { category, note, page, project, tagPython, tagWeb } from '../test/fixtures'
import { renderApp } from '../test/render'

vi.mock('../services/api', async (importOriginal) => ({ ...(await importOriginal<object>()), ...(await import('../test/apiMock')).mocks }))

beforeEach(() => {
  mocks.api.health.mockResolvedValue({ status: 'ok', database: 'ok' })
  mocks.documentsApi.list.mockResolvedValue({ items: [], total: 0, limit: 4, offset: 0 })
  mocks.categoriesApi.list.mockResolvedValue([category])
  mocks.projectsApi.list.mockResolvedValue([project])
  mocks.tagsApi.list.mockResolvedValue([tagPython, tagWeb])
  mocks.api.getNote.mockResolvedValue(note)
  mocks.api.search.mockResolvedValue(page([]))
})

describe('Criar nota', () => {
  it('envia título, conteúdo e organização, e só mostra sucesso após a resposta da API', async () => {
    const user = userEvent.setup()
    let resolveCreate: (n: typeof note) => void = () => {}
    mocks.api.createNote.mockReturnValue(new Promise((r) => (resolveCreate = r)))
    const { router } = renderApp('/notes/new')

    await user.type(screen.getByLabelText('Título'), '  Nova ideia ')
    await user.type(screen.getByLabelText('Conteúdo'), 'Texto')
    await screen.findByRole('option', { name: 'Estudos' })
    await user.selectOptions(screen.getByLabelText('Categoria'), 'c1')
    await user.selectOptions(screen.getByLabelText('Projeto'), 'p1')
    await user.click(await screen.findByRole('button', { name: '#web' }))
    await user.click(screen.getByRole('button', { name: 'Criar nota' }))

    expect(mocks.api.createNote).toHaveBeenCalledWith({
      title: 'Nova ideia',
      content: 'Texto',
      category_id: 'c1',
      project_id: 'p1',
      tag_ids: ['t2'],
    })
    // enquanto a API não responde: botão ocupado e nenhuma mensagem de sucesso
    expect(screen.getByRole('button', { name: 'Salvando…' })).toBeDisabled()
    expect(screen.queryByText('Nota criada.')).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/notes/new')

    resolveCreate({ ...note, id: 'n9', title: 'Nova ideia' })
    expect(await screen.findByText('Nota criada.')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/notes/n9')
  })

  it('valida título obrigatório sem chamar a API', async () => {
    const user = userEvent.setup()
    renderApp('/notes/new')
    await user.type(screen.getByLabelText('Título'), '   ')
    await user.click(screen.getByRole('button', { name: 'Criar nota' }))
    expect(await screen.findByText('Informe um título.')).toBeInTheDocument()
    expect(mocks.api.createNote).not.toHaveBeenCalled()
  })

  it('exibe o erro do servidor e não mostra sucesso', async () => {
    const { ApiError } = await import('../services/api')
    const user = userEvent.setup()
    mocks.api.createNote.mockRejectedValue(new ApiError('Categoria não encontrada.', 422))
    const { router } = renderApp('/notes/new')
    await user.type(screen.getByLabelText('Título'), 'x')
    await user.click(screen.getByRole('button', { name: 'Criar nota' }))

    expect(await screen.findByText('Categoria não encontrada.')).toBeInTheDocument()
    expect(screen.queryByText('Nota criada.')).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/notes/new')
    expect(screen.getByRole('button', { name: 'Criar nota' })).toBeEnabled() // pode tentar de novo
  })

  it('cancelar volta para a biblioteca sem salvar', async () => {
    const user = userEvent.setup()
    const { router } = renderApp('/notes/new')
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(router.state.location.pathname).toBe('/library')
    expect(mocks.api.createNote).not.toHaveBeenCalled()
  })
})

describe('Editar nota', () => {
  it('carrega a nota e preserva categoria, projeto e etiquetas ao alterar só o título', async () => {
    const user = userEvent.setup()
    mocks.api.updateNote.mockResolvedValue({ ...note, title: 'Título novo' })
    const { router } = renderApp('/notes/n1/edit')

    const title = await screen.findByLabelText('Título')
    expect(title).toHaveValue('Guia de Python')
    expect(screen.getByLabelText('Conteúdo')).toHaveValue('Conteúdo da nota')
    await waitFor(() => expect(screen.getByLabelText('Categoria')).toHaveValue('c1'))
    expect(screen.getByRole('button', { name: '#python' })).toHaveAttribute('aria-pressed', 'true')

    await user.clear(title)
    await user.type(title, 'Título novo')
    await user.click(screen.getByRole('button', { name: 'Salvar alterações' }))

    await waitFor(() =>
      expect(mocks.api.updateNote).toHaveBeenCalledWith('n1', {
        title: 'Título novo',
        content: 'Conteúdo da nota',
        category_id: 'c1',
        project_id: 'p1',
        tag_ids: ['t1'],
      }),
    )
    expect(await screen.findByText('Alterações salvas.')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/notes/n1')
  })

  it('associa e desassocia categoria, projeto e etiquetas', async () => {
    const user = userEvent.setup()
    mocks.api.updateNote.mockResolvedValue(note)
    renderApp('/notes/n1/edit')
    await screen.findByLabelText('Título')
    await waitFor(() => expect(screen.getByLabelText('Categoria')).toHaveValue('c1'))

    await user.selectOptions(screen.getByLabelText('Categoria'), '') // desassocia
    await user.selectOptions(screen.getByLabelText('Projeto'), '')
    await user.click(screen.getByRole('button', { name: '#python' })) // remove
    await user.click(screen.getByRole('button', { name: '#web' })) // adiciona
    await user.click(screen.getByRole('button', { name: 'Salvar alterações' }))

    await waitFor(() =>
      expect(mocks.api.updateNote).toHaveBeenCalledWith('n1', expect.objectContaining({ category_id: null, project_id: null, tag_ids: ['t2'] })),
    )
  })

  it('cancelar não salva e volta para a nota', async () => {
    const user = userEvent.setup()
    const { router } = renderApp('/notes/n1/edit')
    await user.type(await screen.findByLabelText('Título'), ' alterado')
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(mocks.api.updateNote).not.toHaveBeenCalled()
    expect(router.state.location.pathname).toBe('/notes/n1')
  })

  it('mostra erro quando a nota não existe', async () => {
    const { ApiError } = await import('../services/api')
    mocks.api.getNote.mockRejectedValue(new ApiError('Nota não encontrada.', 404))
    renderApp('/notes/zzz/edit')
    expect(await screen.findByText('Nota não encontrada.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Título')).not.toBeInTheDocument()
  })
})

describe('Visualizar e excluir nota', () => {
  it('mostra conteúdo, organização e datas', async () => {
    renderApp('/notes/n1')
    expect(await screen.findByRole('heading', { name: 'Guia de Python' })).toBeInTheDocument()
    expect(screen.getByText('Conteúdo da nota')).toBeInTheDocument()
    expect(screen.getByText('#python')).toBeInTheDocument()
    expect(screen.getByText(/Criada em/)).toBeInTheDocument()
    expect(screen.getByText(/Atualizada em/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Editar/ })).toHaveAttribute('href', '/notes/n1/edit')
  })

  it('pede confirmação, cancelar não exclui', async () => {
    const user = userEvent.setup()
    renderApp('/notes/n1')
    await user.click(await screen.findByRole('button', { name: /Excluir/ }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('Excluir nota?')
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(mocks.api.deleteNote).not.toHaveBeenCalled()
  })

  it('confirmar exclui via API e volta para a biblioteca', async () => {
    const user = userEvent.setup()
    mocks.api.deleteNote.mockResolvedValue(undefined)
    const { router } = renderApp('/notes/n1')
    await user.click(await screen.findByRole('button', { name: /Excluir/ }))
    await user.click(screen.getByRole('button', { name: 'Excluir nota' }))
    await waitFor(() => expect(mocks.api.deleteNote).toHaveBeenCalledWith('n1'))
    expect(await screen.findByText('Nota excluída.')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/library')
  })

  it('falha na exclusão mantém o diálogo e mostra o erro', async () => {
    const user = userEvent.setup()
    mocks.api.deleteNote.mockRejectedValue(new Error('Falha ao excluir.'))
    const { router } = renderApp('/notes/n1')
    await user.click(await screen.findByRole('button', { name: /Excluir/ }))
    await user.click(screen.getByRole('button', { name: 'Excluir nota' }))
    expect(await screen.findByText('Falha ao excluir.')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/notes/n1')
  })
})
