import { Search } from 'lucide-react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { Button, LinkButton } from '../components/Button/Button'
import { ToggleChip } from '../components/Chip/Chip'
import { SelectField, TextField } from '../components/Field/Field'
import { NoteCard } from '../components/NoteCard/NoteCard'
import { EmptyState, ErrorState, LoadingState } from '../components/StateBlock/StateBlock'
import { useTaxonomy } from '../features/organization/useTaxonomy'
import { useAsync } from '../hooks/useAsync'
import { useDebouncedParam } from '../hooks/useDebouncedParam'
import { api } from '../services/api'
import type { ContentType } from '../types/library'
import styles from './Page.module.css'

const PAGE_SIZE = 12

export function LibraryPage() {
  const [params, setParams] = useSearchParams()
  const notice = (useLocation().state as { notice?: string } | null)?.notice
  const q = params.get('q') ?? ''
  const category = params.get('category') ?? ''
  const project = params.get('project') ?? ''
  const tags = params.getAll('tag')
  const page = Math.max(1, Number(params.get('page')) || 1)

  const rawType = params.get('type')
  const type: ContentType | undefined = rawType === 'note' || rawType === 'document' ? rawType : undefined
  const search = useDebouncedParam('q')

  const taxonomy = useTaxonomy()
  const results = useAsync(
    () =>
      api.search({
        q: q.trim() || undefined,
        type,
        category_id: category || undefined,
        project_id: project || undefined,
        tag_id: tags,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }),
    params.toString(),
  )

  /** Altera parâmetros da URL; qualquer mudança de filtro volta para a página 1. */
  function update(change: (next: URLSearchParams) => void, keepPage = false) {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        change(next)
        if (!keepPage) next.delete('page')
        return next
      },
      { replace: true },
    )
  }
  const setOrDelete = (key: string, value: string) => (next: URLSearchParams) =>
    value ? next.set(key, value) : next.delete(key)

  function toggleTag(id: string) {
    update((next) => {
      const current = next.getAll('tag')
      next.delete('tag')
      ;(current.includes(id) ? current.filter((t) => t !== id) : [...current, id]).forEach((t) => next.append('tag', t))
    })
  }

  function clearFilters() {
    search.reset()
    setParams({}, { replace: true })
  }

  const hasFilters = Boolean(q || type || category || project || tags.length)
  const { data, error, loading } = results
  const total = data?.total ?? 0
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <div className={styles.headerRow}>
        <header className={styles.header}>
          <h1>Biblioteca</h1>
          <p>Pesquise e filtre notas e documentos.</p>
        </header>
        <LinkButton to="/documents/new">Importar PDF</LinkButton>
      </div>

      {notice && <p className={styles.banner} role="status">{notice}</p>}

      <form role="search" onSubmit={(e) => e.preventDefault()} className={styles.filters}>
        <TextField
          label="Buscar"
          type="search"
          value={search.input}
          onChange={(e) => search.onChange(e.target.value)}
          placeholder="Título, conteúdo, etiquetas…"
          maxLength={200}
        />
        <SelectField
          label="Categoria"
          emptyLabel="Todas as categorias"
          value={category}
          onChange={(e) => update(setOrDelete('category', e.target.value))}
          options={taxonomy.categories.map((c) => ({ value: c.id, label: c.name }))}
        />
        <SelectField
          label="Projeto"
          emptyLabel="Todos os projetos"
          value={project}
          onChange={(e) => update(setOrDelete('project', e.target.value))}
          options={taxonomy.projects.map((p) => ({ value: p.id, label: p.name }))}
        />
      </form>

      <fieldset className={styles.segmented} aria-label="Tipo de conteúdo">
        {([['', 'Tudo'], ['note', 'Notas'], ['document', 'Documentos']] as const).map(([value, label]) => (
          <label key={value}>
            <input
              type="radio"
              name="type"
              value={value}
              checked={(type ?? '') === value}
              onChange={() => update(setOrDelete('type', value))}
            />
            {label}
          </label>
        ))}
      </fieldset>

      {taxonomy.error && (
        <ErrorState message={`Não foi possível carregar os filtros: ${taxonomy.error.message}`} onRetry={taxonomy.reload} />
      )}

      {taxonomy.tags.length > 0 && (
        <fieldset className={styles.tagRow}>
          <legend>Etiquetas</legend>
          {taxonomy.tags.map((tag) => (
            <ToggleChip key={tag.id} label={`#${tag.name}`} color={tag.color} pressed={tags.includes(tag.id)} onClick={() => toggleTag(tag.id)} />
          ))}
        </fieldset>
      )}

      <div className={styles.summary} aria-live="polite">
        {data && !error && (
          <>
            {total} {total === 1 ? 'resultado' : 'resultados'}
            {q.trim() && <> para “{q.trim()}”</>}
            {hasFilters && (
              <>
                {' · '}
                <Button variant="ghost" onClick={clearFilters}>Limpar filtros</Button>
              </>
            )}
          </>
        )}
      </div>

      {error ? (
        <ErrorState message={error.message} onRetry={results.reload} />
      ) : loading && !data ? (
        <LoadingState />
      ) : data && data.items.length === 0 ? (
        <EmptyState>
          <Search size={16} aria-hidden />
          {hasFilters ? 'Nada encontrado com esses critérios.' : 'Sua biblioteca está vazia. Crie uma nota ou importe um PDF.'}
        </EmptyState>
      ) : (
        <div className={styles.cards} aria-busy={loading}>
          {data?.items.map((item) => <NoteCard key={`${item.type}-${item.id}`} note={item} />)}
        </div>
      )}

      {data && total > PAGE_SIZE && (
        <nav className={styles.pager} aria-label="Paginação">
          <Button disabled={page <= 1} onClick={() => update((n) => n.set('page', String(page - 1)), true)}>Anterior</Button>
          <span>Página {page} de {lastPage}</span>
          <Button disabled={page >= lastPage} onClick={() => update((n) => n.set('page', String(page + 1)), true)}>Próxima</Button>
        </nav>
      )}
    </>
  )
}
