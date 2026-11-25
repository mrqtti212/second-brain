import { createContext, useContext } from 'react'
import type { HealthStatus } from '../../types/note'

export type BackendState = 'checking' | 'online' | 'offline'

export interface BackendContextValue {
  backend: BackendState
  health: HealthStatus | null
}

export const BackendContext = createContext<BackendContextValue>({ backend: 'checking', health: null })

export function useBackend(): BackendContextValue {
  return useContext(BackendContext)
}
