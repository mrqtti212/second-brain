import { Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { Button, LinkButton } from '../components/Button/Button'
import { Chip } from '../components/Chip/Chip'
import { ConfirmDialog } from '../components/ConfirmDialog/ConfirmDialog'
import { ErrorState, LoadingState } from '../components/StateBlock/StateBlock'
import { useAsync } from '../hooks/useAsync'
import { api } from '../services/api'
import styles from './Page.module.css'

const dateTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'long', timeStyle: 'short' })

export function NoteViewPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const notice = (useLocation().state as { notice?: string } | null)?.notice
  const { data: note, error, loading, reload } = useAsync(() => api.getNote(id), `note-${id}`)
  const [confirming, setConfirming] = useState(false)

  if (error) return <ErrorState message={error.message} onRetry={reload} />
  if (loading || !note) return <LoadingState />

  return (
    <article>
      {notice && <p className={styles.banner} role="status">{notice}</p>}

      <div className={styles.headerRow}>
        <header className={styles.header}>
          <p><Link className={styles.link} to="/library">← Biblioteca</Link></p>
          <h1>{note.title}</h1>
        </header>
        <div className={styles.actions}>
          <LinkButton to={`/notes/${note.id}/edit`}><Pencil size={15} aria-hidden /> Editar</LinkButton>
          <Button variant="danger" onClick={() => setConfirming(true)}><Trash2 size={15} aria-hidden /> Excluir</Button>
        </div>
      </div>

      {(note.category || note.project || note.tags.length > 0) && (
        <div className={styles.noteMeta}>
          {note.category && <Chip label={note.category.name} color={note.category.color} />}
          {note.project && <Chip label={`Projeto: ${note.project.name}`} />}
          {note.tags.map((t) => <Chip key={t.id} label={`#${t.name}`} color={t.color} />)}
        </div>
      )}

      <div className={styles.noteBody}>{note.content || <span className={styles.muted}>Esta nota não tem conteúdo.</span>}</div>

      <p className={styles.dates}>
        <span>Criada em <time dateTime={note.created_at}>{dateTime.format(new Date(note.created_at))}</time></span>
        <span>Atualizada em <time dateTime={note.updated_at}>{dateTime.format(new Date(note.updated_at))}</time></span>
      </p>

      {confirming && (
        <ConfirmDialog
          title="Excluir nota?"
          message={`A nota “${note.title}” será excluída permanentemente. Categorias, projetos e etiquetas são mantidos.`}
          confirmLabel="Excluir nota"
          onCancel={() => setConfirming(false)}
          onConfirm={async () => {
            await api.deleteNote(note.id)
            navigate('/library', { replace: true, state: { notice: 'Nota excluída.' } })
          }}
        />
      )}
    </article>
  )
}
