import { useState, type FormEvent } from 'react'
import { Button } from '../../components/Button/Button'
import { ToggleChip } from '../../components/Chip/Chip'
import { SelectField, TextField } from '../../components/Field/Field'
import styles from '../../pages/Page.module.css'
import type { DocumentItem, DocumentMetadataInput } from '../../types/library'
import { useTaxonomy } from '../organization/useTaxonomy'

interface DocumentMetadataFormProps {
  document: DocumentItem
  onSave: (input: DocumentMetadataInput) => Promise<void>
  onCancel: () => void
}

/** Edita título, categoria, projeto e etiquetas. O arquivo e o texto extraído não mudam. */
export function DocumentMetadataForm({ document, onSave, onCancel }: DocumentMetadataFormProps) {
  const taxonomy = useTaxonomy()
  const [title, setTitle] = useState(document.title)
  const [categoryId, setCategoryId] = useState(document.category?.id ?? '')
  const [projectId, setProjectId] = useState(document.project?.id ?? '')
  const [tagIds, setTagIds] = useState(document.tags.map((t) => t.id))
  const [titleError, setTitleError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const toggleTag = (id: string) =>
    setTagIds((current) => (current.includes(id) ? current.filter((t) => t !== id) : [...current, id]))

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!title.trim()) {
      setTitleError('Informe um título.')
      return
    }
    setTitleError(null)
    setError(null)
    setSaving(true)
    try {
      await onSave({
        title: title.trim(),
        category_id: categoryId || null,
        project_id: projectId || null,
        tag_ids: tagIds,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível salvar as alterações.')
      setSaving(false)
    }
  }

  return (
    <form className={styles.form} onSubmit={submit} aria-label="Editar informações do documento" noValidate>
      {error && <p className={styles.formError} role="alert">{error}</p>}
      <TextField label="Título" value={title} maxLength={255} error={titleError} onChange={(e) => setTitle(e.target.value)} autoFocus />
      <div className={styles.formRow}>
        <SelectField
          label="Categoria"
          emptyLabel="Sem categoria"
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
          options={taxonomy.categories.map((c) => ({ value: c.id, label: c.name }))}
        />
        <SelectField
          label="Projeto"
          emptyLabel="Sem projeto"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          options={taxonomy.projects.map((p) => ({ value: p.id, label: p.name }))}
        />
      </div>
      <fieldset className={styles.tagRow}>
        <legend>Etiquetas</legend>
        {taxonomy.tags.map((tag) => (
          <ToggleChip key={tag.id} label={`#${tag.name}`} color={tag.color} pressed={tagIds.includes(tag.id)} onClick={() => toggleTag(tag.id)} />
        ))}
        {!taxonomy.loading && !taxonomy.error && taxonomy.tags.length === 0 && <span className={styles.muted}>Nenhuma etiqueta criada.</span>}
        {taxonomy.error && <span className={styles.muted} role="alert">Não foi possível carregar as opções ({taxonomy.error.message}).</span>}
      </fieldset>
      <div className={styles.actions}>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Salvando…' : 'Salvar alterações'}</Button>
        <Button onClick={onCancel} disabled={saving}>Cancelar</Button>
      </div>
    </form>
  )
}
