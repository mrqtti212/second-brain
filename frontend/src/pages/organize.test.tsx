import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mocks } from '../test/apiMock'
import { category, project, tagPython } from '../test/fixtures'
import { renderApp } from '../test/render'

vi.mock('../services/api', async (importOriginal) => ({ ...(await importOriginal<object>()), ...(await import('../test/apiMock')).mocks }))

beforeEach(() => {
  mocks.api.health.mockResolvedValue({ status: 'ok', database: 'ok' })
  mocks.documentsApi.list.mockResolvedValue({ items: [], total: 0, limit: 4, offset: 0 })
  mocks.categoriesApi.list.mockResolvedValue([category])
  mocks.projectsApi.list.mockResolvedValue([project])
  mocks.tagsApi.list.mockResolvedValue([tagPython])
})

const section = (name: string) => screen.getByRole('region', { name })

describe('Organizar', () => {
  it('lista categorias, projetos e etiquetas reais com contagem de notas', async () => {
    renderApp('/organize')
    expect(await screen.findByText('Estudos')).toBeInTheDocument()
    expect(screen.getByText('Tese')).toBeInTheDocument()
    expect(screen.getByText('python')).toBeInTheDocument()
    expect(within(section('Categorias')).getByText('1 nota')).toBeInTheDocument()
  })

  it('cria categoria com cor e recarrega a lista', async () => {
    const user = userEvent.setup()
    mocks.categoriesApi.create.mockResolvedValue({ ...category, id: 'c2', name: 'Trabalho' })
    renderApp('/organize')
    await screen.findByText('Estudos')

    await user.click(screen.getByRole('button', { name: 'Nova categoria' }))
    const form = screen.getByRole('form', { name: 'Nova categoria' })
    await user.type(within(form).getByLabelText('Nome'), 'Trabalho')
    await user.click(within(form).getByLabelText('Verde'))
    await user.click(within(form).getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(mocks.categoriesApi.create).toHaveBeenCalledWith({ name: 'Trabalho', description: null, color: '#4fc38a' }))
    expect(await screen.findByText('Categoria criada.')).toBeInTheDocument()
    expect(mocks.categoriesApi.list).toHaveBeenCalledTimes(2) // recarregou
  })

  it('não afirma "Nenhuma categoria criada." junto do sucesso enquanto a lista recarrega', async () => {
    const user = userEvent.setup()
    const created = { ...category, id: 'c2', name: 'Trabalho' }
    let reloaded: (items: typeof created[]) => void = () => {}
    mocks.categoriesApi.list
      .mockResolvedValueOnce([]) // carga inicial: lista vazia
      .mockReturnValueOnce(new Promise((resolve) => (reloaded = resolve))) // recarga após criar: ainda pendente
    mocks.categoriesApi.create.mockResolvedValue(created)
    renderApp('/organize')
    expect(await screen.findByText('Nenhuma categoria criada.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Nova categoria' }))
    const form = screen.getByRole('form', { name: 'Nova categoria' })
    await user.type(within(form).getByLabelText('Nome'), 'Trabalho')
    await user.click(within(form).getByRole('button', { name: 'Salvar' }))

    // sucesso confirmado pela API, lista ainda recarregando: o aviso de lista vazia já seria falso
    expect(await screen.findByText('Categoria criada.')).toBeInTheDocument()
    expect(screen.queryByText('Nenhuma categoria criada.')).not.toBeInTheDocument()

    reloaded([created])
    expect(await screen.findByText('Trabalho')).toBeInTheDocument()
    expect(screen.queryByText('Nenhuma categoria criada.')).not.toBeInTheDocument()
  })

  it('mostra conflito de nome duplicado e mantém o formulário', async () => {
    const { ApiError } = await import('../services/api')
    const user = userEvent.setup()
    mocks.tagsApi.create.mockRejectedValue(new ApiError('Já existe uma etiqueta com este nome.', 409))
    renderApp('/organize')
    await screen.findByText('python')

    await user.click(screen.getByRole('button', { name: 'Nova etiqueta' }))
    const form = screen.getByRole('form', { name: 'Nova etiqueta' })
    await user.type(within(form).getByLabelText('Nome'), 'Python')
    await user.click(within(form).getByRole('button', { name: 'Salvar' }))

    expect(await within(form).findByText('Já existe uma etiqueta com este nome.')).toBeInTheDocument()
    expect(screen.queryByText('Etiqueta criada.')).not.toBeInTheDocument()
  })

  it('valida nome obrigatório', async () => {
    const user = userEvent.setup()
    renderApp('/organize')
    await screen.findByText('Tese')
    await user.click(screen.getByRole('button', { name: 'Novo projeto' }))
    await user.click(within(screen.getByRole('form', { name: 'Novo projeto' })).getByRole('button', { name: 'Salvar' }))
    expect(await screen.findByText('Informe um nome.')).toBeInTheDocument()
    expect(mocks.projectsApi.create).not.toHaveBeenCalled()
  })

  it('edita um projeto', async () => {
    const user = userEvent.setup()
    mocks.projectsApi.update.mockResolvedValue({ ...project, name: 'Tese final' })
    renderApp('/organize')
    await user.click(await screen.findByRole('button', { name: 'Editar projeto Tese' }))
    const form = screen.getByRole('form', { name: /Editar projeto Tese/ })
    const name = within(form).getByLabelText('Nome')
    expect(name).toHaveValue('Tese')
    await user.clear(name)
    await user.type(name, 'Tese final')
    await user.click(within(form).getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(mocks.projectsApi.update).toHaveBeenCalledWith('p1', { name: 'Tese final', description: 'Doutorado' }))
    expect(await screen.findByText('Projeto salvo.')).toBeInTheDocument()
  })

  it('exclui etiqueta somente após confirmação e informa que as notas são mantidas', async () => {
    const user = userEvent.setup()
    mocks.tagsApi.remove.mockResolvedValue(undefined)
    renderApp('/organize')
    await user.click(await screen.findByRole('button', { name: 'Excluir etiqueta python' }))

    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent('As notas continuam existindo')
    await user.click(within(dialog).getByRole('button', { name: 'Cancelar' }))
    expect(mocks.tagsApi.remove).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Excluir etiqueta python' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Excluir etiqueta' }))
    await waitFor(() => expect(mocks.tagsApi.remove).toHaveBeenCalledWith('t1'))
    expect(await screen.findByText('Etiqueta excluída.')).toBeInTheDocument()
  })

  it('mostra estado vazio e erro com tentativa de novo', async () => {
    const { ApiError } = await import('../services/api')
    mocks.projectsApi.list.mockResolvedValue([])
    mocks.tagsApi.list.mockRejectedValueOnce(new ApiError('Erro 500', 500))
    const user = userEvent.setup()
    renderApp('/organize')
    expect(await screen.findByText('Nenhum projeto criado.')).toBeInTheDocument()
    expect(await screen.findByText('Erro 500')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Tentar novamente' }))
    expect(await screen.findByText('python')).toBeInTheDocument()
  })
})
