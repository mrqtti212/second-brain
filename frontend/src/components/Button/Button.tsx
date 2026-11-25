import type { ButtonHTMLAttributes } from 'react'
import { Link, type LinkProps } from 'react-router-dom'
import styles from './Button.module.css'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
}

export function Button({ variant = 'secondary', className, type = 'button', ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={[styles.button, styles[variant], className].filter(Boolean).join(' ')}
      {...rest}
    />
  )
}

interface LinkButtonProps extends LinkProps {
  variant?: ButtonProps['variant']
}

/** Link de navegação com a aparência de um botão. */
export function LinkButton({ variant = 'secondary', className, ...rest }: LinkButtonProps) {
  return <Link className={[styles.button, styles[variant], className].filter(Boolean).join(' ')} {...rest} />
}
