import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Button } from '../../components/Button/Button'
import { ColorPicker } from '../../components/ColorPicker/ColorPicker'
import { ConfirmDialog } from '../../components/ConfirmDialog/ConfirmDialog'
import { TextArea, TextField } from '../../components/Field/Field'
import { EmptyState, ErrorState, LoadingState } from '../../components/StateBlock/StateBlock'
import { useAsync } from '../../hooks/useAsync'
import styles from '../../pages/Page.module.css'
import type { OrganizationInput } from '../../types/library'
import local from './ResourceManager.module.css'

interface Item {
  id: string
  name: string
  description?: string | null
  color?: string | null
  notes_count: number
  documents_count: number
}

interface ResourceApi<T> {
  list: () => Promise<T[]>
  create: (input: OrganizationInput) => Promise<T>
  update: (id: string, input: Partial<OrganizationInput>) => Promise<T>
  remove: (id: string) => Promise<void>
}

interface Labels {
  title: string
  singular: string // "categoria"
  article: 'a' | 'o' // concordância: "a categoria", "o projeto"
  empty: string
  deleteEffect: string
}

interface ResourceManagerProps<T> {
  labels: Labels
  api: ResourceApi<T>
  withColor?: boolean
  withDescription?: boolean
}

export function ResourceManager<T extends Item>({ labels, api, withColor, withDescription }: ResourceManagerProps<T>) {
  const { data, error, loading, reload } = useAsync(api.list, `${labels.title}`)
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [deleting, setDeleting] = useState<T | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const done = (message: string) => {
    setNotice(message)
    setEditing(null)
    reload()
  }
  const Cap = labels.singular[0].toUpperCase() + labels.singular.slice(1)
  const feminine = labels.article === 'a'

  return (
    <section className={styles.section} aria-labelledby={`h-${labels.title}`}>
      <div className={styles.sectionHead}>
        <h2 id={`h-${labels.title}`}>{labels.title}</h2>
        <Button onClick={() => { setNotice(null); setEditing('new') }} disabled={editing === 'new'}>
          <Plus size={15} aria-hidden /> Nov{labels.article} {labels.singular}
        </Button>
      </div>

      {notice && <p className={styles.banner} role="status">{notice}</p>}

      {editing === 'new' && (
        <ItemForm
          legend={`Nov${labels.article} ${labels.singular}`}
          withColor={withColor}
          withDescription={withDescription}
          onCancel={() => setEditing(null)}
          onSave={async (values) => {
            await api.create(values)
            done(`${Cap} criad${labels.article}.`)
          }}
        />
      )}

      {error ? (
        <ErrorState message={error.message} onRetry={reload} />
      ) : loading && !data ? (
        <LoadingState />
      ) : data && data.length === 0 && !loading && editing !== 'new' ? (
        <EmptyState>{labels.empty}</EmptyState>
      ) : (
        <ul className={local.list}>
          {data?.map((item) =>
            editing === item.id ? (
              <li key={item.id}>
                <ItemForm
                  legend={`Editar ${labels.singular} ${item.name}`}
                  initial={item}
                  withColor={withColor}
                  withDescription={withDescription}
                  onCancel={() => setEditing(null)}
                  onSave={async (values) => {
                    await api.update(item.id, values)
                    done(`${Cap} salv${labels.article}.`)
                  }}
                />
              </li>
            ) : (
              <li key={item.id} className={local.row}>
                {withColor && <span className={local.dot} style={{ background: item.color ?? 'transparent' }} aria-hidden />}
                <div className={local.info}>
                  <strong>{item.name}</strong>
                  {item.description && <span className={styles.muted}>{item.description}</span>}
                </div>
                <span className={local.count}>{item.notes_count} {item.notes_count === 1 ? 'nota' : 'notas'}</span>
                {item.documents_count > 0 && (
                  <span className={local.count}>{item.documents_count} {item.documents_count === 1 ? 'documento' : 'documentos'}</span>
                )}
                <Button variant="ghost" onClick={() => { setNotice(null); setEditing(item.id) }} aria-label={`Editar ${labels.singular} ${item.name}`}>
                  <Pencil size={15} aria-hidden />
                </Button>
                <Button variant="danger" onClick={() => setDeleting(item)} aria-label={`Excluir ${labels.singular} ${item.name}`}>
                  <Trash2 size={15} aria-hidden />
                </Button>
              </li>
            ),
          )}
        </ul>
      )}

      {deleting && (
        <ConfirmDialog
          title={`Excluir ${labels.singular}?`}
          message={`${feminine ? 'A' : 'O'} ${labels.singular} “${deleting.name}” será excluíd${labels.article}. ${labels.deleteEffect}`}
          confirmLabel={`Excluir ${labels.singular}`}
          onCancel={() => setDeleting(null)}
          onConfirm={async () => {
            await api.remove(deleting.id)
            setDeleting(null)
            done(`${Cap} excluíd${labels.article}.`)
          }}
        />
      )}
    </section>
  )
}

interface ItemFormProps {
  legend: string
  initial?: Item
  withColor?: boolean
  withDescription?: boolean
  onSave: (values: OrganizationInput) => Promise<void>
  onCancel: () => void
}

function ItemForm({ legend, initial, withColor, withDescription, onSave, onCancel }: ItemFormProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [color, setColor] = useState<string | null>(initial?.color ?? null)
  const [nameError, setNameError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) {
      setNameError('Informe um nome.')
      return
    }
    setNameError(null)
    setError(null)
    setSaving(true)
    const values: OrganizationInput = { name: name.trim() }
    if (withDescription) values.description = description.trim() || null
    if (withColor) values.color = color
    try {
      await onSave(values)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível salvar.')
      setSaving(false)
    }
  }

  return (
    <form className={local.form} onSubmit={submit} aria-label={legend} noValidate>
      {error && <p className={styles.formError} role="alert">{error}</p>}
      <TextField label="Nome" value={name} maxLength={80} error={nameError} onChange={(e) => setName(e.target.value)} autoFocus />
      {withDescription && <TextArea label="Descrição (opcional)" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />}
      {withColor && <ColorPicker legend="Cor" value={color} onChange={setColor} />}
      <div className={styles.actions}>
        <Button variant="primary" type="submit" disabled={saving}>{saving ? 'Salvando…' : 'Salvar'}</Button>
        <Button onClick={onCancel} disabled={saving}>Cancelar</Button>
      </div>
    </form>
  )
}
