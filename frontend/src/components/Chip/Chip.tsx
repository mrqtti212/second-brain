import type { ButtonHTMLAttributes } from 'react'
import styles from './Chip.module.css'

interface ChipProps {
  label: string
  color?: string | null
}

/** Rótulo com bolinha de cor (categoria, etiqueta). */
export function Chip({ label, color }: ChipProps) {
  return (
    <span className={styles.chip}>
      {color && <span className={styles.dot} style={{ background: color }} aria-hidden />}
      {label}
    </span>
  )
}

interface ToggleChipProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children' | 'color'> {
  label: string
  color?: string | null
  pressed: boolean
}

/** Chip alternável por teclado (seleção de etiquetas). */
export function ToggleChip({ label, color, pressed, className, ...rest }: ToggleChipProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      className={`${styles.chip} ${styles.toggle} ${pressed ? styles.on : ''} ${className ?? ''}`}
      {...rest}
    >
      {color && <span className={styles.dot} style={{ background: color }} aria-hidden />}
      {label}
    </button>
  )
}
