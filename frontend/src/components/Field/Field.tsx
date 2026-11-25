import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import styles from './Field.module.css'

interface BaseProps {
  label: string
  hint?: ReactNode
  error?: string | null
}

function Wrapper({ label, hint, error, id, children }: BaseProps & { id: string; children: ReactNode }) {
  return (
    <div className={styles.field}>
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && <p className={styles.hint}>{hint}</p>}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

export function TextField({ label, hint, error, ...props }: BaseProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId()
  return (
    <Wrapper label={label} hint={hint} error={error} id={id}>
      <input id={id} aria-invalid={error ? true : undefined} {...props} />
    </Wrapper>
  )
}

export function TextArea({ label, hint, error, ...props }: BaseProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId()
  return (
    <Wrapper label={label} hint={hint} error={error} id={id}>
      <textarea id={id} aria-invalid={error ? true : undefined} {...props} />
    </Wrapper>
  )
}

interface SelectProps extends BaseProps, SelectHTMLAttributes<HTMLSelectElement> {
  options: { value: string; label: string }[]
  emptyLabel: string
}

export function SelectField({ label, hint, error, options, emptyLabel, ...props }: SelectProps) {
  const id = useId()
  return (
    <Wrapper label={label} hint={hint} error={error} id={id}>
      <select id={id} {...props}>
        <option value="">{emptyLabel}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </Wrapper>
  )
}
