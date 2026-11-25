import { Link } from 'react-router-dom'
import styles from './Page.module.css'

export function NotFoundPage() {
  return (
    <>
      <header className={styles.header}>
        <h1>Página não encontrada</h1>
        <p>
          <Link className={styles.link} to="/">Voltar ao dashboard</Link>
        </p>
      </header>
    </>
  )
}
