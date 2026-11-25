import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from '../layouts/AppLayout'
import { DashboardPage } from '../pages/DashboardPage'
import { DocumentsPage } from '../pages/DocumentsPage'
import { DocumentUploadPage } from '../pages/DocumentUploadPage'
import { DocumentViewPage } from '../pages/DocumentViewPage'
import { LibraryPage } from '../pages/LibraryPage'
import { NoteEditorPage } from '../pages/NoteEditorPage'
import { NoteViewPage } from '../pages/NoteViewPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { OrganizePage } from '../pages/OrganizePage'

export const appRoutes = [
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'library', element: <LibraryPage /> },
      { path: 'notes', element: <Navigate to="/library" replace /> },
      { path: 'notes/new', element: <NoteEditorPage /> },
      { path: 'notes/:id', element: <NoteViewPage /> },
      { path: 'notes/:id/edit', element: <NoteEditorPage /> },
      { path: 'organize', element: <OrganizePage /> },
      { path: 'documents', element: <DocumentsPage /> },
      { path: 'documents/new', element: <DocumentUploadPage /> },
      { path: 'documents/:id', element: <DocumentViewPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

export const router = createBrowserRouter(appRoutes)
