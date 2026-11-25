import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { BackendProvider } from '../features/backend/BackendProvider'
import { appRoutes } from '../routes'

/**
 * Renderiza a aplicação inteira (layout + rotas) em uma URL.
 * `withBackend` inclui o `BackendProvider` (consulta /api/health), como no `App.tsx`.
 */
export function renderApp(path: string, { withBackend = false }: { withBackend?: boolean } = {}) {
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] })
  const tree = <RouterProvider router={router} />
  const view = render(withBackend ? <BackendProvider>{tree}</BackendProvider> : tree)
  return { router, ...view }
}
