import { useEffect, useRef, useState } from 'react'
import { Button } from '../Button/Button'
import styles from './ConfirmDialog.module.css'

interface ConfirmDialogProps {
  title: string
  message: string
  confirmLabel: string
  onCancel: () => void
  /** Executa a ação. O diálogo só fecha se não lançar erro. */
  onConfirm: () => Promise<void>
}

export function ConfirmDialog({ title, message, confirmLabel, onCancel, onConfirm }: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    cancelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onCancel()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  async function confirm() {
    setBusy(true)
    setError(null)
    try {
      await onConfirm()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível concluir a ação.')
      setBusy(false)
    }
  }

  return (
    <div className={styles.overlay} onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className={styles.dialog} role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message">
        <h2 id="confirm-title">{title}</h2>
        <p id="confirm-message">{message}</p>
        {error && <p className={styles.error} role="alert">{error}</p>}
        <div className={styles.actions}>
          <button ref={cancelRef} type="button" className={styles.cancel} onClick={onCancel} disabled={busy}>
            Cancelar
          </button>
          <Button variant="primary" className={styles.danger} onClick={confirm} disabled={busy}>
            {busy ? 'Aguarde…' : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
