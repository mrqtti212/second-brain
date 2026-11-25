import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { appRoutes } from '../routes'

/** Renderiza a aplicação inteira (layout + rotas) em uma URL. */
export function renderApp(path: string) {
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] })
  const view = render(<RouterProvider router={router} />)
  return { router, ...view }
}
