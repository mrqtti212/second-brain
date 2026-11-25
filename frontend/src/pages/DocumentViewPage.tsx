import { Download, Pencil, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { Button } from '../components/Button/Button'
import { Chip } from '../components/Chip/Chip'
import { ConfirmDialog } from '../components/ConfirmDialog/ConfirmDialog'
import { ErrorState, LoadingState } from '../components/StateBlock/StateBlock'
import { StatusBadge } from '../components/StatusBadge/StatusBadge'
import { ChunksPanel } from '../features/documents/ChunksPanel'
import { DocumentMetadataForm } from '../features/documents/DocumentMetadataForm'
import { useAsync } from '../hooks/useAsync'
import { usePolling } from '../hooks/usePolling'
import { ApiError, documentsApi } from '../services/api'
import { isInProgress, type DocumentItem } from '../types/library'
import { formatBytes, formatDateTime } from '../utils/format'
import styles from './Page.module.css'
import buttonStyles from '../components/Button/Button.module.css'

export function DocumentViewPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const notice = (useLocation().state as { notice?: string } | null)?.notice
  const doc = useAsync(() => documentsApi.get(id), `document-${id}`)
  const [confirming, setConfirming] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  const [reprocessing, setReprocessing] = useState(false)
  const [reprocessError, setReprocessError] = useState<string | null>(null)
  const reprocessInFlight = useRef(false) // trava síncrona: cliques repetidos não enviam novos pedidos

  // Enquanto o documento está na fila ou sendo processado, o estado é consultado de tempos em tempos.
  // O polling para sozinho no estado terminal, ao desmontar, e pausa após falhas seguidas.
  const polling = usePolling({
    active: isInProgress(doc.data?.status),
    onTick: doc.reload,
    hasError: Boolean(doc.error),
  })

  if (doc.error && !doc.data) return <ErrorState message={doc.error.message} onRetry={doc.reload} />
  const document = doc.data
  if (!document) return <LoadingState />

  async function reprocess() {
    if (reprocessInFlight.current) return
    reprocessInFlight.current = true
    setReprocessing(true)
    setReprocessError(null)
    setSaved(null)
    try {
      await documentsApi.reprocess(id)
      setSaved('Reprocessamento solicitado. O documento voltou para a fila.')
    } catch (err) {
      setReprocessError(err instanceof Error ? err.message : 'Não foi possível solicitar o reprocessamento.')
      // 409: o estado mudou por outro caminho (já na fila, ou arquivo ausente). Mostra o estado real.
      if (err instanceof ApiError && err.status === 409) setSaved(null)
    } finally {
      reprocessInFlight.current = false
      setReprocessing(false)
      polling.resume()
      doc.reload()
    }
  }

  return (
    <article>
      {(saved ?? notice) && <p className={styles.banner} role="status">{saved ?? notice}</p>}

      <div className={styles.headerRow}>
        <header className={styles.header}>
          <p><Link className={styles.link} to="/documents">← Documentos</Link></p>
          <h1>{document.title}</h1>
        </header>
        <div className={styles.actions}>
          {/* Link comum: o navegador baixa o arquivo direto da API. */}
          <a className={`${buttonStyles.button} ${buttonStyles.secondary}`} href={documentsApi.fileUrl(document.id)} download>
            <Download size={15} aria-hidden /> Baixar original
          </a>
          <Button onClick={() => { setSaved(null); setEditing(true) }} disabled={editing}><Pencil size={15} aria-hidden /> Editar informações</Button>
          <Button variant="danger" onClick={() => setConfirming(true)}><Trash2 size={15} aria-hidden /> Excluir</Button>
        </div>
      </div>

      {editing && (
        <div className={styles.editBox}>
          <DocumentMetadataForm
            document={document}
            onCancel={() => setEditing(false)}
            onSave={async (input) => {
              await documentsApi.update(document.id, input)
              doc.reload()
              setEditing(false)
              setSaved('Informações atualizadas.')
            }}
          />
        </div>
      )}

      <div className={styles.noteMeta}>
        <StatusBadge status={document.status} hasText={document.has_text} />
        {document.category && <Chip label={document.category.name} color={document.category.color} />}
        {document.project && <Chip label={`Projeto: ${document.project.name}`} />}
        {document.tags.map((t) => <Chip key={t.id} label={`#${t.name}`} color={t.color} />)}
      </div>

      <dl className={styles.metaGrid}>
        <div><dt>Arquivo</dt><dd>{document.original_filename}</dd></div>
        <div><dt>Tamanho</dt><dd>{formatBytes(document.size_bytes)}</dd></div>
        <div><dt>Páginas</dt><dd>{document.page_count ?? '—'}</dd></div>
        <div><dt>Trechos</dt><dd>{document.chunk_count}</dd></div>
        <div><dt>Importado em</dt><dd><time dateTime={document.created_at}>{formatDateTime(document.created_at)}</time></dd></div>
      </dl>

      {doc.error && (
        <p className={styles.warning} role="alert">
          {polling.paused ? 'Atualização automática pausada: ' : 'Não foi possível atualizar o estado: '}
          {doc.error.message}{' '}
          <Button variant="ghost" onClick={() => { polling.resume(); doc.reload() }}>Atualizar agora</Button>
        </p>
      )}
      {reprocessError && <p className={styles.formError} role="alert">{reprocessError}</p>}
      {document.status === 'failed' && (
        <div className={styles.danger} role="alert">
          <p>O processamento falhou. {document.error_message ?? ''} O arquivo original foi preservado e pode ser baixado.</p>
          <Button onClick={reprocess} disabled={reprocessing}>{reprocessing ? 'Solicitando…' : 'Reprocessar'}</Button>
        </div>
      )}
      {document.status === 'pending' && (
        <p className={styles.warning} role="status">
          Aguardando processamento. O texto e os trechos serão gerados em segundo plano; esta página se atualiza sozinha.
        </p>
      )}
      {document.status === 'processing' && (
        <p className={styles.warning} role="status">
          Processando: extraindo o texto e gerando os trechos. Esta página se atualiza sozinha.
        </p>
      )}
      {document.status === 'completed' && !document.has_text && (
        <p className={styles.warning} role="status">
          Este PDF não tem texto extraível (provavelmente é digitalizado). O OCR ainda não está disponível, então ele não aparece na busca pelo conteúdo.
        </p>
      )}

      <ExtractedContent document={document} />

      <ChunksPanel document={document} />

      {confirming && (
        <ConfirmDialog
          title="Excluir documento?"
          message={`“${document.title}” e o arquivo PDF original serão excluídos permanentemente. Categorias, projetos e etiquetas são mantidos.`}
          confirmLabel="Excluir documento"
          onCancel={() => setConfirming(false)}
          onConfirm={async () => {
            await documentsApi.remove(document.id)
            navigate('/documents', { replace: true, state: { notice: 'Documento excluído.' } })
          }}
        />
      )}
    </article>
  )
}

/** Texto extraído por página. É recarregado quando o documento muda (ex.: processamento concluído). */
function ExtractedContent({ document }: { document: DocumentItem }) {
  const content = useAsync(
    () => documentsApi.content(document.id),
    `document-content-${document.id}-${document.status}-${document.updated_at}`,
  )
  return (
    <section aria-labelledby="content-heading">
      <h2 id="content-heading">Conteúdo extraído</h2>
      {content.error ? (
        <ErrorState message={content.error.message} onRetry={content.reload} />
      ) : !content.data ? (
        <LoadingState label="Carregando conteúdo…" />
      ) : content.data.pages.length === 0 ? (
        <p className={styles.muted}>
          {isInProgress(document.status) ? 'O texto aparecerá aqui quando o processamento terminar.' : 'Nenhum texto foi extraído.'}
        </p>
      ) : (
        content.data.pages.map((page) => (
          <section key={page.page_number} className={styles.pageBlock} aria-label={`Página ${page.page_number}`}>
            <h3>Página {page.page_number}</h3>
            <div className={styles.noteBody}>{page.text || <span className={styles.muted}>(sem texto nesta página)</span>}</div>
          </section>
        ))
      )}
    </section>
  )
}
