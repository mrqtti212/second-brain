import type { ReactNode } from 'react'
import { Button } from '../Button/Button'
import styles from './StateBlock.module.css'

export function LoadingState({ label = 'Carregando…' }: { label?: string }) {
  return (
    <p className={styles.state} role="status">
      <span className={styles.spinner} aria-hidden />
      {label}
    </p>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className={`${styles.state} ${styles.error}`} role="alert">
      <span>{message}</span>
      {onRetry && <Button onClick={onRetry}>Tentar novamente</Button>}
    </div>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className={styles.state}>{children}</p>
}
