import { Link } from 'react-router-dom'
import { AssistantPanel } from '../components/AssistantPanel/AssistantPanel'
import { Badge } from '../components/Badge/Badge'
import { DocumentList } from '../components/DocumentList/DocumentList'
import { NoteCard } from '../components/NoteCard/NoteCard'
import { EmptyState, ErrorState, LoadingState } from '../components/StateBlock/StateBlock'
import { DEMO_DOCUMENTS, DEMO_NOTES } from '../features/dashboard/demoData'
import { useAsync } from '../hooks/useAsync'
import { api, ApiError, documentsApi } from '../services/api'
import { formatBytes } from '../utils/format'
import styles from './Page.module.css'

export function DashboardPage() {
  const { data, error, loading, reload } = useAsync(() => api.search({ limit: 4 }), 'dashboard-recent')
  const documents = useAsync(() => documentsApi.list({ limit: 4 }), 'dashboard-documents')
  const offline = error instanceof ApiError && error.isOffline
  const docsOffline = documents.error instanceof ApiError && documents.error.isOffline

  return (
    <>
      <header className={styles.header}>
        <h1>Bem-vindo ao seu Second Brain</h1>
        <p>Um lugar para guardar, organizar e reencontrar o que você sabe.</p>
      </header>

      <div className={styles.grid}>
        <div className={`${styles.grid} ${styles.twoCols}`}>
          <section className={styles.section} aria-labelledby="recent-heading">
            <div className={styles.sectionHead}>
              <h2 id="recent-heading">Notas recentes</h2>
              {offline ? <Badge tone="warning">Demonstração temporária</Badge> : <Link className={styles.link} to="/library">Abrir biblioteca</Link>}
            </div>

            {offline ? (
              <>
                <p className={styles.notice}>Backend offline. Os cartões abaixo são exemplos fictícios.</p>
                <div className={styles.cards}>
                  {DEMO_NOTES.map((note) => (
                    <NoteCard key={note.id} note={note} linkable={false} />
                  ))}
                </div>
              </>
            ) : error ? (
              <ErrorState message={error.message} onRetry={reload} />
            ) : loading && !data ? (
              <LoadingState />
            ) : data && data.items.length === 0 ? (
              <EmptyState>Nenhuma nota ainda. Use “Nova nota” para criar a primeira.</EmptyState>
            ) : (
              <div className={styles.cards}>
                {data?.items.map((note) => <NoteCard key={note.id} note={note} />)}
              </div>
            )}
          </section>

          <section className={styles.section} aria-labelledby="docs-heading">
            <div className={styles.sectionHead}>
              <h2 id="docs-heading">Documentos</h2>
              {docsOffline ? <Badge tone="warning">Demonstração temporária</Badge> : <Link className={styles.link} to="/documents">Ver todos</Link>}
            </div>
            {docsOffline ? (
              <>
                <DocumentList documents={DEMO_DOCUMENTS} />
                <p className={styles.muted}>Backend offline. Estes documentos são exemplos fictícios.</p>
              </>
            ) : documents.error ? (
              <ErrorState message={documents.error.message} onRetry={documents.reload} />
            ) : !documents.data ? (
              <LoadingState />
            ) : documents.data.items.length === 0 ? (
              <EmptyState>Nenhum PDF importado ainda. <Link className={styles.link} to="/documents/new">Importar PDF</Link></EmptyState>
            ) : (
              <DocumentList
                documents={documents.data.items.map((d) => ({
                  id: d.id,
                  name: d.title,
                  kind: 'PDF' as const,
                  size: formatBytes(d.size_bytes),
                  href: `/documents/${d.id}`,
                }))}
              />
            )}
          </section>
        </div>

        <AssistantPanel />
      </div>
    </>
  )
}
