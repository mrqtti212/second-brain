import { useMemo, type ReactNode } from 'react'
import { useAsync } from '../../hooks/useAsync'
import { api } from '../../services/api'
import { BackendContext, type BackendContextValue } from './backend-context'

/** Consulta /api/health uma vez e informa o estado do backend à interface. */
export function BackendProvider({ children }: { children: ReactNode }) {
  const { data, error, loading } = useAsync(api.health, 'health')

  const value = useMemo<BackendContextValue>(
    () => ({
      health: data ?? null,
      backend: loading ? 'checking' : error ? 'offline' : 'online',
    }),
    [data, error, loading],
  )
  return <BackendContext.Provider value={value}>{children}</BackendContext.Provider>
}
