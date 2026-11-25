import { FileText, StickyNote } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { SearchResult } from '../../types/library'
import { formatDate } from '../../utils/format'
import { Chip } from '../Chip/Chip'
import { Highlight } from '../Highlight/Highlight'
import { StatusBadge } from '../StatusBadge/StatusBadge'
import styles from './NoteCard.module.css'

interface NoteCardProps {
  note: SearchResult
  /** Demonstração: sem link para uma nota que não existe no backend. */
  linkable?: boolean
}

/** Cartão de um resultado da biblioteca: nota ou documento. */
export function NoteCard({ note, linkable = true }: NoteCardProps) {
  const isDocument = note.type === 'document'
  const href = isDocument ? `/documents/${note.id}` : `/notes/${note.id}`
  const title = linkable ? (
    <Link to={href} className={styles.link}>
      {note.title}
    </Link>
  ) : (
    note.title
  )
  const TypeIcon = isDocument ? FileText : StickyNote

  return (
    <article className={styles.card}>
      <p className={styles.type}>
        <TypeIcon size={13} aria-hidden />
        {isDocument ? 'Documento PDF' : 'Nota'}
        {isDocument && note.status && <StatusBadge status={note.status} hasText={Boolean(note.has_text)} />}
      </p>
      <h3 className={styles.title}>{title}</h3>
      <p className={styles.excerpt}>
        {note.snippet ? <Highlight text={note.snippet} /> : isDocument ? 'Sem texto para exibir.' : 'Sem conteúdo.'}
      </p>
      {(note.category || note.project || note.tags.length > 0) && (
        <div className={styles.meta}>
          {note.category && <Chip label={note.category.name} color={note.category.color} />}
          {note.project && <Chip label={`Projeto: ${note.project.name}`} />}
          {note.tags.map((tag) => (
            <Chip key={tag.id} label={`#${tag.name}`} color={tag.color} />
          ))}
        </div>
      )}
      <time className={styles.date} dateTime={note.updated_at}>
        {isDocument && note.page_count ? `${note.page_count} ${note.page_count === 1 ? 'página' : 'páginas'} · ` : ''}
        Atualizado em {formatDate(note.updated_at)}
      </time>
    </article>
  )
}
