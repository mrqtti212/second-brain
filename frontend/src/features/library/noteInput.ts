import type { Note, NoteInput } from '../../types/library'

export const EMPTY_NOTE: NoteInput = { title: '', content: '', category_id: null, project_id: null, tag_ids: [] }

export function noteToInput(note: Note): NoteInput {
  return {
    title: note.title,
    content: note.content,
    category_id: note.category?.id ?? null,
    project_id: note.project?.id ?? null,
    tag_ids: note.tags.map((t) => t.id),
  }
}
