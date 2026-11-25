import { Plus, Search, Upload } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button, LinkButton } from '../components/Button/Button'
import { NoteCard } from '../components/NoteCard/NoteCard'
import { EmptyState, ErrorState, LoadingState } from '../components/StateBlock/StateBlock'
import { useBackend } from '../features/backend/backend-context'
import { useAsync } from '../hooks/useAsync'
import { usePolling } from '../hooks/usePolling'
import { api, documentsApi } from '../services/api'
import styles from './Page.module.css'

interface Summary {
  notes: number
  documents: number
  pending: number
  processing: number
  failed: number
}

/** Contagens reais, vindas da API (nenhuma é calculada no navegador nem simulada). */
async function fetchSummary(): Promise<Summary> {
  const [notes, documents, pending, processing, failed] = await Promise.all([
    api.search({ type: 'note', limit: 1 }),
    documentsApi.list({ limit: 1 }),
    documentsApi.list({ status: 'pending', limit: 1 }),
    documentsApi.list({ status: 'processing', limit: 1 }),
    documentsApi.list({ status: 'failed', limit: 1 }),
  ])
  return {
    notes: notes.total,
    documents: documents.total,
    pending: pending.total,
    processing: processing.total,
    failed: failed.total,
  }
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

export function DashboardPage() {
  const { backend, health } = useBackend()

  return (
    <>
      <header className={styles.header}>
        <h1>Bem-vindo ao seu Second Brain</h1>
        <p>Um lugar para guardar, organizar e reencontrar o que você sabe.</p>
      </header>

      {backend === 'checking' ? (
        <LoadingState label="Verificando a API…" />
      ) : backend === 'offline' ? (
        <section className={styles.section} aria-labelledby="offline-heading">
          <h2 id="offline-heading">Não foi possível conectar ao backend</h2>
          <p className={styles.muted}>
            A API não respondeu, então não há dados para mostrar. Inicie o aplicativo com <code>./scripts/run-app.sh</code>{' '}
            (ou a API, em <code>backend/</code>, com <code>uvicorn app.main:app --port 8000</code>) e recarregue.
          </p>
          <Button onClick={() => window.location.reload()}>Tentar novamente</Button>
        </section>
      ) : health?.database !== 'ok' ? (
        <section className={styles.section} aria-labelledby="db-heading">
          <h2 id="db-heading">A API está no ar, mas o banco de dados está indisponível</h2>
          <p className={styles.muted}>
            Suba o PostgreSQL com pgvector (<code>docker compose up -d db</code>) e confirme que as migrations foram aplicadas
            (<code>alembic upgrade head</code>, em <code>backend/</code>). Depois, recarregue.
          </p>
          <Button onClick={() => window.location.reload()}>Tentar novamente</Button>
        </section>
      ) : (
        <DashboardContent />
      )}
    </>
  )
}

function DashboardContent() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const summary = useAsync(fetchSummary, 'dashboard-summary')
  const recent = useAsync(() => api.search({ limit: 6 }), 'dashboard-recent')

  const inProgress = (summary.data?.pending ?? 0) + (summary.data?.processing ?? 0)
  // Enquanto houver PDF na fila ou sendo processado, os números e a lista se atualizam sozinhos.
  usePolling({
    active: inProgress > 0,
    onTick: () => {
      summary.reload()
      recent.reload()
    },
    hasError: Boolean(summary.error || recent.error),
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    const q = query.trim()
    navigate(q ? `/library?q=${encodeURIComponent(q)}` : '/library')
  }

  const isEmpty = summary.data !== undefined && summary.data.notes === 0 && summary.data.documents === 0
  // Só decide entre "comece aqui" e "recentes" depois de saber quantos itens existem (evita piscar o estado errado).
  const ready = summary.data !== undefined || summary.error !== undefined

  return (
    <div className={styles.stack}>
      <section className={styles.hero} aria-label="Buscar e adicionar">
        <form className={styles.heroSearch} onSubmit={submit} role="search">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="O que você quer reencontrar?"
            aria-label="Buscar na biblioteca"
          />
          <Button type="submit" variant="primary">
            <Search size={15} aria-hidden /> Buscar
          </Button>
        </form>
        <div className={styles.heroActions}>
          <LinkButton to="/notes/new">
            <Plus size={15} aria-hidden /> Nova nota
          </LinkButton>
          <LinkButton to="/documents/new">
            <Upload size={15} aria-hidden /> Importar PDF
          </LinkButton>
        </div>
      </section>

      {summary.error && !summary.data ? (
        <ErrorState message={summary.error.message} onRetry={summary.reload} />
      ) : summary.data ? (
        <>
          <div className={styles.stats}>
            <Link className={styles.stat} to="/library?type=note">
              <strong>{summary.data.notes}</strong>
              <span>{summary.data.notes === 1 ? 'nota' : 'notas'}</span>
            </Link>
            <Link className={styles.stat} to="/documents">
              <strong>{summary.data.documents}</strong>
              <span>{summary.data.documents === 1 ? 'documento PDF' : 'documentos PDF'}</span>
            </Link>
          </div>

          {inProgress > 0 && (
            <p className={styles.notice} role="status">
              <span>
                {plural(inProgress, 'PDF está', 'PDFs estão')} sendo processado{inProgress === 1 ? '' : 's'}. Os números e a lista
                abaixo se atualizam sozinhos.
              </span>
              <Link className={styles.link} to="/documents">Ver documentos</Link>
            </p>
          )}
          {summary.data.failed > 0 && (
            <div className={styles.danger} role="alert">
              <span>
                {plural(summary.data.failed, 'documento falhou', 'documentos falharam')} no processamento. O arquivo original foi
                preservado e pode ser reprocessado na página do documento.
              </span>{' '}
              <Link className={styles.link} to="/documents">Abrir documentos</Link>
            </div>
          )}
        </>
      ) : (
        <LoadingState />
      )}

      {!ready ? null : isEmpty ? (
        <section className={styles.section} aria-labelledby="start-heading">
          <h2 id="start-heading">Comece guardando algo</h2>
          <p className={styles.muted}>
            Sua biblioteca está vazia. Crie uma nota ou importe um PDF; depois organize com categorias, projetos e etiquetas e
            reencontre tudo pela busca.
          </p>
        </section>
      ) : (
        <section className={styles.section} aria-labelledby="recent-heading">
          <div className={styles.sectionHead}>
            <h2 id="recent-heading">Atualizados recentemente</h2>
            <Link className={styles.link} to="/library">Abrir biblioteca</Link>
          </div>
          {recent.error && !recent.data ? (
            <ErrorState message={recent.error.message} onRetry={recent.reload} />
          ) : !recent.data ? (
            <LoadingState />
          ) : recent.data.items.length === 0 ? (
            <EmptyState>Nada por aqui ainda.</EmptyState>
          ) : (
            <div className={styles.cards}>
              {recent.data.items.map((item) => (
                <NoteCard key={`${item.type}-${item.id}`} note={item} />
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
