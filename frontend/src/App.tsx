import { RouterProvider } from 'react-router-dom'
import { BackendProvider } from './features/backend/BackendProvider'
import { router } from './routes'

export default function App() {
  return (
    <BackendProvider>
      <RouterProvider router={router} />
    </BackendProvider>
  )
}
