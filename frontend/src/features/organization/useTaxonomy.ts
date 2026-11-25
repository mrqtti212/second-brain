import { useAsync } from '../../hooks/useAsync'
import { categoriesApi, projectsApi, tagsApi } from '../../services/api'

/** Carrega categorias, projetos e etiquetas juntos (filtros e editor de notas). */
export function useTaxonomy() {
  const state = useAsync(
    () => Promise.all([categoriesApi.list(), projectsApi.list(), tagsApi.list()]),
    'taxonomy',
  )
  const [categories, projects, tags] = state.data ?? [[], [], []]
  return { categories, projects, tags, ...state }
}
