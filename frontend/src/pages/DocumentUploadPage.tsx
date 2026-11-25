import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '../components/Button/Button'
import { ToggleChip } from '../components/Chip/Chip'
import { SelectField, TextField } from '../components/Field/Field'
import { useTaxonomy } from '../features/organization/useTaxonomy'
import { useAsync } from '../hooks/useAsync'
import { ApiError, documentsApi } from '../services/api'
import type { DuplicateDocumentInfo } from '../types/library'
import { formatBytes } from '../utils/format'
import styles from './Page.module.css'

/** Mensagem de erro para o arquivo escolhido, ou null se estiver ok. */
function validateFile(file: File, maxBytes: number | undefined): string | null {
  if (!file.name.toLowerCase().endsWith('.pdf')) return 'Formato não suportado. Selecione um arquivo PDF.'
  if (file.size === 0) return 'O arquivo está vazio.'
  if (maxBytes !== undefined && file.size > maxBytes) {
    return `O arquivo tem ${formatBytes(file.size)}; o limite é ${formatBytes(maxBytes)}.`
  }
  return null
}

export function DocumentUploadPage() {
  const navigate = useNavigate()
  const taxonomy = useTaxonomy()
  const limits = useAsync(documentsApi.limits, 'upload-limits')
  const maxBytes = limits.data?.max_upload_bytes

  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [projectId, setProjectId] = useState('')
  const [tagIds, setTagIds] = useState<string[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [duplicate, setDuplicate] = useState<DuplicateDocumentInfo | null>(null)
  const inFlight = useRef(false) // trava síncrona contra clique/Enter repetidos

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0] ?? null
    setError(null)
    setDuplicate(null)
    if (!chosen) {
      setFile(null)
      setFileError(null)
      return
    }
    const problem = validateFile(chosen, maxBytes)
    setFileError(problem)
    setFile(problem ? null : chosen)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (inFlight.current) return
    if (!file) {
      setFileError((current) => current ?? 'Selecione um arquivo PDF.')
      return
    }
    const problem = validateFile(file, maxBytes)
    if (problem) {
      setFileError(problem)
      return
    }

    const form = new FormData()
    form.append('file', file)
    if (title.trim()) form.append('title', title.trim())
    if (categoryId) form.append('category_id', categoryId)
    if (projectId) form.append('project_id', projectId)
    tagIds.forEach((id) => form.append('tag_ids', id))

    inFlight.current = true
    setUploading(true)
    setError(null)
    setDuplicate(null)
    try {
      const document = await documentsApi.upload(form)
      navigate(`/documents/${document.id}`, {
        state: { notice: 'Documento recebido. O texto está sendo extraído em segundo plano.' },
      })
    } catch (err) {
      // Arquivo idêntico já importado: não é um erro de envio nem um sucesso, é um aviso com atalho.
      if (err instanceof ApiError && err.duplicateOf) setDuplicate(err.duplicateOf)
      else setError(err instanceof Error ? err.message : 'Não foi possível importar o documento.')
      inFlight.current = false
      setUploading(false)
    }
  }

  const toggleTag = (id: string) =>
    setTagIds((current) => (current.includes(id) ? current.filter((t) => t !== id) : [...current, id]))

  return (
    <>
      <header className={styles.header}>
        <h1>Importar PDF</h1>
        <p>O arquivo original é guardado na hora e o texto de cada página é extraído em segundo plano; você acompanha o andamento na página do documento. Não há OCR: PDFs digitalizados ficam sem texto.</p>
      </header>

      <form className={styles.form} onSubmit={submit} noValidate>
        {error && <p className={styles.formError} role="alert">{error}</p>}
        {duplicate && (
          <div className={styles.duplicate} role="alert">
            <span>
              <strong>Este arquivo já foi importado</strong> como “{duplicate.title}” ({duplicate.original_filename}). Nada foi
              importado de novo e o documento existente não foi alterado.
            </span>
            <Link className={styles.link} to={`/documents/${duplicate.id}`}>Abrir o documento existente</Link>
          </div>
        )}

        <TextField
          label="Arquivo PDF"
          type="file"
          accept=".pdf,application/pdf"
          onChange={onFileChange}
          error={fileError}
          hint={maxBytes ? `Tamanho máximo: ${formatBytes(maxBytes)}.` : undefined}
          disabled={uploading}
        />
        <TextField
          label="Título (opcional)"
          value={title}
          maxLength={255}
          onChange={(e) => setTitle(e.target.value)}
          hint="Se ficar vazio, usamos o nome do arquivo."
          disabled={uploading}
        />

        <div className={styles.formRow}>
          <SelectField
            label="Categoria"
            emptyLabel="Sem categoria"
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
            options={taxonomy.categories.map((c) => ({ value: c.id, label: c.name }))}
            disabled={uploading}
          />
          <SelectField
            label="Projeto"
            emptyLabel="Sem projeto"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            options={taxonomy.projects.map((p) => ({ value: p.id, label: p.name }))}
            disabled={uploading}
          />
        </div>

        {taxonomy.tags.length > 0 && (
          <fieldset className={styles.tagRow}>
            <legend>Etiquetas</legend>
            {taxonomy.tags.map((tag) => (
              <ToggleChip key={tag.id} label={`#${tag.name}`} color={tag.color} pressed={tagIds.includes(tag.id)} onClick={() => toggleTag(tag.id)} disabled={uploading} />
            ))}
          </fieldset>
        )}

        <div className={styles.actions}>
          <Button variant="primary" type="submit" disabled={uploading}>
            {uploading ? 'Enviando…' : 'Importar documento'}
          </Button>
          <Button onClick={() => navigate('/documents')} disabled={uploading}>Cancelar</Button>
        </div>
        {uploading && <p className={styles.muted} role="status">Enviando e validando o arquivo. A extração do texto continua depois, em segundo plano.</p>}
      </form>
    </>
  )
}
