import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '../../components/Button/Button'
import { ToggleChip } from '../../components/Chip/Chip'
import { SelectField, TextArea, TextField } from '../../components/Field/Field'
import styles from '../../pages/Page.module.css'
import type { NoteInput } from '../../types/library'
import { useTaxonomy } from '../organization/useTaxonomy'

interface NoteFormProps {
  /** Valores iniciais. Em edição vêm da nota, então campos intocados são reenviados como estão. */
  initial: NoteInput
  submitLabel: string
  cancelTo: string
  onSubmit: (input: NoteInput) => Promise<void>
}

export function NoteForm({ initial, submitLabel, cancelTo, onSubmit }: NoteFormProps) {
  const [values, setValues] = useState<NoteInput>(initial)
  const [titleError, setTitleError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const navigate = useNavigate()
  const taxonomy = useTaxonomy()

  const set = <K extends keyof NoteInput>(key: K, value: NoteInput[K]) => setValues((v) => ({ ...v, [key]: value }))

  function toggleTag(id: string) {
    set('tag_ids', values.tag_ids.includes(id) ? values.tag_ids.filter((t) => t !== id) : [...values.tag_ids, id])
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!values.title.trim()) {
      setTitleError('Informe um título.')
      return
    }
    setTitleError(null)
    setError(null)
    setSaving(true)
    try {
      await onSubmit({ ...values, title: values.title.trim() })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível salvar a nota.')
      setSaving(false)
    }
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      {error && <p className={styles.formError} role="alert">{error}</p>}

      <TextField
        label="Título"
        value={values.title}
        maxLength={255}
        error={titleError}
        onChange={(e) => set('title', e.target.value)}
        autoFocus
      />
      <TextArea label="Conteúdo" rows={12} value={values.content} onChange={(e) => set('content', e.target.value)} />

      <div className={styles.formRow}>
        <SelectField
          label="Categoria"
          emptyLabel="Sem categoria"
          value={values.category_id ?? ''}
          onChange={(e) => set('category_id', e.target.value || null)}
          options={taxonomy.categories.map((c) => ({ value: c.id, label: c.name }))}
        />
        <SelectField
          label="Projeto"
          emptyLabel="Sem projeto"
          value={values.project_id ?? ''}
          onChange={(e) => set('project_id', e.target.value || null)}
          options={taxonomy.projects.map((p) => ({ value: p.id, label: p.name }))}
        />
      </div>

      <fieldset className={styles.tagRow}>
        <legend>Etiquetas</legend>
        {taxonomy.tags.map((tag) => (
          <ToggleChip key={tag.id} label={`#${tag.name}`} color={tag.color} pressed={values.tag_ids.includes(tag.id)} onClick={() => toggleTag(tag.id)} />
        ))}
        {!taxonomy.loading && !taxonomy.error && taxonomy.tags.length === 0 && (
          <span className={styles.muted}>Nenhuma etiqueta criada. <Link className={styles.link} to="/organize">Criar etiquetas</Link></span>
        )}
        {taxonomy.loading && !taxonomy.data && <span className={styles.muted}>Carregando opções…</span>}
        {taxonomy.error && (
          <span className={styles.muted} role="alert">
            Não foi possível carregar as opções ({taxonomy.error.message}).{' '}
            <Button variant="ghost" onClick={taxonomy.reload}>Tentar novamente</Button>
          </span>
        )}
      </fieldset>

      <div className={styles.actions}>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Salvando…' : submitLabel}</Button>
        <Button onClick={() => navigate(cancelTo)} disabled={saving}>Cancelar</Button>
      </div>
    </form>
  )
}
