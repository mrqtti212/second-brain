import { FileText } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { DocumentListItem } from '../../types/note'
import { Badge } from '../Badge/Badge'
import styles from './DocumentList.module.css'

export function DocumentList({ documents }: { documents: DocumentListItem[] }) {
  return (
    <ul className={styles.list}>
      {documents.map((doc) => (
        <li key={doc.id} className={styles.item}>
          <span className={styles.icon}>
            <FileText size={16} aria-hidden />
          </span>
          {doc.href ? (
            <Link to={doc.href} className={`${styles.name} ${styles.link}`}>{doc.name}</Link>
          ) : (
            <span className={styles.name}>{doc.name}</span>
          )}
          <Badge>{doc.kind}</Badge>
          <span className={styles.size}>{doc.size}</span>
        </li>
      ))}
    </ul>
  )
}
