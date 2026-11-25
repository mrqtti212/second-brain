import { Upload } from 'lucide-react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { Button, LinkButton } from '../components/Button/Button'
import { ToggleChip } from '../components/Chip/Chip'
import { DocumentCard } from '../components/DocumentCard/DocumentCard'
import { SelectField, TextField } from '../components/Field/Field'
import { EmptyState, ErrorState, LoadingState } from '../components/StateBlock/StateBlock'
import { useTaxonomy } from '../features/organization/useTaxonomy'
import { useAsync } from '../hooks/useAsync'
import { useDebouncedParam } from '../hooks/useDebouncedParam'
import { usePolling } from '../hooks/usePolling'
import { documentsApi } from '../services/api'
import { isInProgress } from '../types/library'
import styles from './Page.module.css'

const PAGE_SIZE = 12

export function DocumentsPage() {
  const [params, setParams] = useSearchParams()
  const notice = (useLocation().state as { notice?: string } | null)?.notice
  const q = params.get('q') ?? ''
  const category = params.get('category') ?? ''
  const project = params.get('project') ?? ''
  const tags = params.getAll('tag')
  const page = Math.max(1, Number(params.get('page')) || 1)

  const search = useDebouncedParam('q')
  const taxonomy = useTaxonomy()
  const results = useAsync(
    () =>
      documentsApi.list({
        q: q || undefined,
        category_id: category || undefined,
        project_id: project || undefined,
        tag_id: tags,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }),
    params.toString(),
  )

  // Enquanto algum documento da lista ainda está na fila ou em processamento, a lista se atualiza sozinha.
  usePolling({
    active: Boolean(results.data?.items.some((d) => isInProgress(d.status))),
    onTick: results.reload,
    hasError: Boolean(results.error),
    intervalMs: 3000,
  })

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

  const hasFilters = Boolean(q || category || project || tags.length)
  const { data, error, loading } = results
  const total = data?.total ?? 0
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <div className={styles.headerRow}>
        <header className={styles.header}>
          <h1>Documentos</h1>
          <p>PDFs importados, com o texto extraído guardado no banco.</p>
        </header>
        <LinkButton variant="primary" to="/documents/new"><Upload size={15} aria-hidden /> Importar PDF</LinkButton>
      </div>

      {notice && <p className={styles.banner} role="status">{notice}</p>}

      <form role="search" onSubmit={(e) => e.preventDefault()} className={styles.filters}>
        <TextField
          label="Buscar pelo nome"
          type="search"
          value={search.input}
          onChange={(e) => search.onChange(e.target.value)}
          placeholder="Nome ou título do documento"
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
            {total} {total === 1 ? 'documento' : 'documentos'}
            {hasFilters && (
              <>
                {' · '}
                <Button variant="ghost" onClick={() => { search.reset(); setParams({}, { replace: true }) }}>Limpar filtros</Button>
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
        <EmptyState>{hasFilters ? 'Nenhum documento encontrado com esses critérios.' : 'Nenhum documento importado ainda. Use “Importar PDF” para começar.'}</EmptyState>
      ) : (
        <div className={styles.cards} aria-busy={loading}>
          {data?.items.map((doc) => <DocumentCard key={doc.id} document={doc} />)}
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
