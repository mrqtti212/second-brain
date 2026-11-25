import { Brain, FolderOpen, LayoutDashboard, Library, Tags } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useBackend } from '../../features/backend/backend-context'
import { Badge } from '../Badge/Badge'
import styles from './Sidebar.module.css'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/library', label: 'Biblioteca', icon: Library },
  { to: '/organize', label: 'Organizar', icon: Tags },
  { to: '/documents', label: 'Documentos', icon: FolderOpen },
]

interface SidebarProps {
  open: boolean
  onNavigate: () => void
}

export function Sidebar({ open, onNavigate }: SidebarProps) {
  const { backend, health } = useBackend()

  const status =
    backend === 'online' ? (
      <Badge tone={health?.database === 'ok' ? 'success' : 'warning'}>
        API online · banco {health?.database === 'ok' ? 'ok' : 'indisponível'}
      </Badge>
    ) : backend === 'offline' ? (
      <Badge tone="danger">API offline</Badge>
    ) : (
      <Badge>Verificando API…</Badge>
    )

  return (
    <aside className={`${styles.sidebar} ${open ? styles.open : ''}`} aria-label="Navegação principal">
      <div className={styles.logo}>
        <span className={styles.logoMark}>
          <Brain size={18} aria-hidden />
        </span>
        <span className={styles.logoText}>Second Brain</span>
      </div>

      <nav className={styles.nav}>
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) => `${styles.link} ${isActive ? styles.active : ''}`}
          >
            <Icon size={18} aria-hidden />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className={styles.footer}>{status}</div>
    </aside>
  )
}
