import { Menu, Plus, Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Button, LinkButton } from '../Button/Button'
import styles from './Topbar.module.css'

interface TopbarProps {
  onMenu: () => void
}

export function Topbar({ onMenu }: TopbarProps) {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()
  // A biblioteca tem seu próprio campo de busca.
  const inLibrary = useLocation().pathname.startsWith('/library')

  function submit(event: FormEvent) {
    event.preventDefault()
    const q = query.trim()
    navigate(q ? `/library?q=${encodeURIComponent(q)}` : '/library')
  }

  return (
    <header className={styles.topbar}>
      <Button variant="ghost" className={styles.menu} onClick={onMenu} aria-label="Abrir menu">
        <Menu size={18} aria-hidden />
      </Button>

      {inLibrary ? (
        <div className={styles.spacer} />
      ) : (
        <form className={styles.search} onSubmit={submit} role="search">
          <Search size={16} aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar na biblioteca…"
            aria-label="Buscar na biblioteca"
          />
        </form>
      )}

      <LinkButton variant="primary" to="/notes/new">
        <Plus size={16} aria-hidden />
        <span className={styles.newLabel}>Nova nota</span>
      </LinkButton>
    </header>
  )
}
