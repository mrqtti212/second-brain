import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from '../components/Sidebar/Sidebar'
import { Topbar } from '../components/Topbar/Topbar'
import styles from './AppLayout.module.css'

export function AppLayout() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className={styles.shell}>
      <Sidebar open={menuOpen} onNavigate={() => setMenuOpen(false)} />
      {menuOpen && <div className={styles.scrim} onClick={() => setMenuOpen(false)} aria-hidden />}

      <div className={styles.main}>
        <Topbar onMenu={() => setMenuOpen(true)} />
        <main className={styles.content}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
