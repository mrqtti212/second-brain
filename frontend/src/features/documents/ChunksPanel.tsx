import { useState } from 'react'
import { Button } from '../../components/Button/Button'
import { Badge } from '../../components/Badge/Badge'
import { ErrorState, LoadingState } from '../../components/StateBlock/StateBlock'
import { useAsync } from '../../hooks/useAsync'
import styles from '../../pages/Page.module.css'
import { documentsApi } from '../../services/api'
import { isInProgress, type DocumentItem } from '../../types/library'

const PAGE_SIZE = 20

/** Trechos gerados do documento, cada um com a página de origem. Carrega só quando aberto. */
export function ChunksPanel({ document }: { document: DocumentItem }) {
  const [open, setOpen] = useState(false)
  const [offset, setOffset] = useState(0)
  const total = document.chunk_count

  return (
    <section aria-labelledby="chunks-heading" className={styles.chunkSection}>
      <div className={styles.sectionHead}>
        <h2 id="chunks-heading">Trechos ({total})</h2>
        {total > 0 && (
          <Button aria-expanded={open} aria-controls="chunks-list" onClick={() => setOpen((v) => !v)}>
            {open ? 'Ocultar trechos' : 'Mostrar trechos'}
          </Button>
        )}
      </div>
      <p className={styles.muted}>
        O texto de cada página é dividido em trechos com sobreposição, que servirão de base para recuperação por IA em uma
        próxima fase. Ainda não há embeddings nem busca semântica.
      </p>

      {total === 0 && <EmptyChunks document={document} />}
      {total > 0 && open && <ChunkList id={document.id} version={`${document.chunk_count}-${document.updated_at}`} offset={offset} onOffset={setOffset} />}
    </section>
  )
}

function EmptyChunks({ document }: { document: DocumentItem }) {
  if (isInProgress(document.status)) {
    return <p className={styles.muted} role="status">Os trechos serão gerados quando o processamento terminar.</p>
  }
  if (document.status === 'failed') {
    return <p className={styles.muted}>Sem trechos: o processamento falhou. Reprocesse o documento para gerá-los.</p>
  }
  if (document.status === 'completed' && document.has_text) {
    return (
      <p className={styles.warning} role="status">
        Nenhum trecho gerado. As páginas têm pouco texto útil ou o documento foi importado antes da segmentação (nesse caso,
        rode <code>python -m app.cli rebuild-chunks --missing-only</code> no backend).
      </p>
    )
  }
  return <p className={styles.muted}>Sem trechos: o documento não tem texto extraído.</p>
}

function ChunkList({ id, version, offset, onOffset }: { id: string; version: string; offset: number; onOffset: (n: number) => void }) {
  // `version` muda quando o documento é reprocessado: a lista aberta é recarregada.
  const { data, error, loading, reload } = useAsync(
    () => documentsApi.chunks(id, { limit: PAGE_SIZE, offset }),
    `chunks-${id}-${offset}-${version}`,
  )

  if (error) return <ErrorState message={error.message} onRetry={reload} />
  if (!data) return <LoadingState label="Carregando trechos…" />

  const last = Math.max(1, Math.ceil(data.total / PAGE_SIZE))
  const current = Math.floor(offset / PAGE_SIZE) + 1
  return (
    <div id="chunks-list" aria-busy={loading}>
      {data.items.map((chunk) => (
        <article key={chunk.id} className={styles.chunk} aria-label={`Trecho ${chunk.chunk_index + 1}`}>
          <header className={styles.chunkHead}>
            <strong>Trecho {chunk.chunk_index + 1}</strong>
            <Badge tone="accent">Página {chunk.page_number}</Badge>
            <span className={styles.muted}>{chunk.character_count} caracteres</span>
          </header>
          <div className={styles.noteBody}>{chunk.content}</div>
        </article>
      ))}
      {data.total > PAGE_SIZE && (
        <nav className={styles.pager} aria-label="Paginação dos trechos">
          <Button disabled={current <= 1} onClick={() => onOffset(offset - PAGE_SIZE)}>Anterior</Button>
          <span>Página {current} de {last}</span>
          <Button disabled={current >= last} onClick={() => onOffset(offset + PAGE_SIZE)}>Próxima</Button>
        </nav>
      )}
    </div>
  )
}
