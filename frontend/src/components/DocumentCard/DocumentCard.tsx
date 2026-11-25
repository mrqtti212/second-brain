import { FileText } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { DocumentItem } from '../../types/library'
import { formatBytes, formatDate } from '../../utils/format'
import { Chip } from '../Chip/Chip'
import { StatusBadge } from '../StatusBadge/StatusBadge'
import styles from '../NoteCard/NoteCard.module.css'

export function DocumentCard({ document: doc }: { document: DocumentItem }) {
  return (
    <article className={styles.card}>
      <p className={styles.type}>
        <FileText size={13} aria-hidden />
        Documento PDF
        <StatusBadge status={doc.status} hasText={doc.has_text} />
      </p>
      <h3 className={styles.title}>
        <Link to={`/documents/${doc.id}`} className={styles.link}>{doc.title}</Link>
      </h3>
      <p className={styles.excerpt}>
        {doc.original_filename} · {formatBytes(doc.size_bytes)}
        {doc.page_count ? ` · ${doc.page_count} ${doc.page_count === 1 ? 'página' : 'páginas'}` : ''}
      </p>
      {(doc.category || doc.project || doc.tags.length > 0) && (
        <div className={styles.meta}>
          {doc.category && <Chip label={doc.category.name} color={doc.category.color} />}
          {doc.project && <Chip label={`Projeto: ${doc.project.name}`} />}
          {doc.tags.map((tag) => <Chip key={tag.id} label={`#${tag.name}`} color={tag.color} />)}
        </div>
      )}
      <time className={styles.date} dateTime={doc.created_at}>Importado em {formatDate(doc.created_at)}</time>
    </article>
  )
}
