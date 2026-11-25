import { useNavigate, useParams } from 'react-router-dom'
import { ErrorState, LoadingState } from '../components/StateBlock/StateBlock'
import { NoteForm } from '../features/library/NoteForm'
import { EMPTY_NOTE, noteToInput } from '../features/library/noteInput'
import { useAsync } from '../hooks/useAsync'
import { api } from '../services/api'
import styles from './Page.module.css'

export function NoteEditorPage() {
  const { id } = useParams()
  return id ? <EditNote id={id} /> : <NewNote />
}

function NewNote() {
  const navigate = useNavigate()
  return (
    <>
      <header className={styles.header}>
        <h1>Nova nota</h1>
        <p>Escreva e organize. A nota só aparece na biblioteca depois de salva.</p>
      </header>
      <NoteForm
        initial={EMPTY_NOTE}
        submitLabel="Criar nota"
        cancelTo="/library"
        onSubmit={async (input) => {
          const note = await api.createNote(input)
          navigate(`/notes/${note.id}`, { state: { notice: 'Nota criada.' } })
        }}
      />
    </>
  )
}

function EditNote({ id }: { id: string }) {
  const navigate = useNavigate()
  const { data: note, error, loading, reload } = useAsync(() => api.getNote(id), `note-${id}`)

  if (error) return <ErrorState message={error.message} onRetry={reload} />
  if (loading || !note) return <LoadingState />

  return (
    <>
      <header className={styles.header}>
        <h1>Editar nota</h1>
        <p>As alterações só são aplicadas quando você salva.</p>
      </header>
      <NoteForm
        key={note.id}
        initial={noteToInput(note)}
        submitLabel="Salvar alterações"
        cancelTo={`/notes/${id}`}
        onSubmit={async (input) => {
          await api.updateNote(id, input)
          navigate(`/notes/${id}`, { state: { notice: 'Alterações salvas.' } })
        }}
      />
    </>
  )
}
