"""Importação, consulta, segmentação e exclusão de documentos PDF."""

import logging
import re
import uuid
from pathlib import PurePosixPath
from typing import BinaryIO

from sqlalchemy import asc, delete, desc, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    DuplicateDocumentError,
    InvalidReferenceError,
    NotFoundError,
    OriginalFileMissingError,
    ProcessingInProgressError,
    UnsupportedMediaError,
)
from app.models.category import Category
from app.models.document import Document, DocumentChunk, DocumentPage, DocumentStatus
from app.models.project import Project
from app.models.tag import Tag
from app.schemas.document import DocumentUpdate
from app.services import chunker, embedding_tasks, pdf, search
from app.services.storage import LocalStorage

logger = logging.getLogger("second_brain.documents")

ACCEPTED_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}
_UNSAFE_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f\"\\/]")
MAX_NAME_LENGTH = 255


def safe_filename(raw: str | None) -> str:
    """Nome apenas para exibição/download. Nunca é usado como caminho."""
    name = PurePosixPath((raw or "").replace("\\", "/")).name  # descarta diretórios
    name = _UNSAFE_NAME_CHARS.sub("", name).strip().strip(".")
    return name[:MAX_NAME_LENGTH] or "documento.pdf"


def _validate_declared_type(filename: str, content_type: str | None) -> None:
    if not filename.lower().endswith(".pdf"):
        raise UnsupportedMediaError("Formato não suportado: a extensão do arquivo deve ser .pdf.")
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared not in ACCEPTED_CONTENT_TYPES:
        raise UnsupportedMediaError("Formato não suportado: o tipo de conteúdo deve ser application/pdf.")


# --- relações -------------------------------------------------------------
def _check_refs(db: Session, category_id: uuid.UUID | None, project_id: uuid.UUID | None) -> None:
    if category_id is not None and db.get(Category, category_id) is None:
        raise InvalidReferenceError("Categoria não encontrada.")
    if project_id is not None and db.get(Project, project_id) is None:
        raise InvalidReferenceError("Projeto não encontrado.")


def _load_tags(db: Session, tag_ids: list[uuid.UUID]) -> list[Tag]:
    unique = list(dict.fromkeys(tag_ids))
    if not unique:
        return []
    tags = list(db.scalars(select(Tag).where(Tag.id.in_(unique))))
    if len(tags) != len(unique):
        raise InvalidReferenceError("Uma ou mais etiquetas não foram encontradas.")
    return tags


# --- segmentação ------------------------------------------------------------
def chunking_config(settings: Settings) -> chunker.ChunkingConfig:
    return chunker.ChunkingConfig(
        max_chars=settings.chunk_max_chars,
        overlap_chars=settings.chunk_overlap_chars,
        min_chars=settings.chunk_min_chars,
    )


def _chunk_rows(document_id: uuid.UUID, specs: list[chunker.ChunkSpec]) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            document_id=document_id,
            page_number=spec.page_number,
            chunk_index=spec.chunk_index,
            content=spec.content,
            character_count=len(spec.content),
            start_offset=spec.start_offset,
            end_offset=spec.end_offset,
        )
        for spec in specs
    ]


def rebuild_chunks(db: Session, settings: Settings, document_id: uuid.UUID) -> int:
    """Gera de novo os chunks de um documento a partir de `document_pages`.

    Idempotente: apaga os chunks atuais e recria na mesma transação, então repetir
    a chamada nunca duplica registros. Se a segmentação falhar, nada é alterado.
    """
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Documento não encontrado.")
    pages = [
        (number, text)
        for number, text in db.execute(
            select(DocumentPage.page_number, DocumentPage.text)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number)
        )
    ]
    specs = chunker.chunk_pages(pages, chunking_config(settings))  # pode falhar: ainda nada alterado
    try:
        saved_embeddings = embedding_tasks.snapshot_embeddings(db, document_id)  # trechos iguais herdam os vetores
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        new_chunks = _chunk_rows(document_id, specs)
        db.add_all(new_chunks)
        if saved_embeddings:
            db.flush()
            embedding_tasks.restore_embeddings(db, new_chunks, saved_embeddings)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return len(specs)


def documents_without_chunks(db: Session) -> list[uuid.UUID]:
    """Documentos concluídos, com texto e sem nenhum chunk (ex.: importados antes da segmentação)."""
    has_chunks = exists().where(DocumentChunk.document_id == Document.id)
    return list(
        db.scalars(
            select(Document.id)
            .where(Document.status == DocumentStatus.COMPLETED.value, Document.has_text.is_(True), ~has_chunks)
            .order_by(Document.created_at)
        )
    )


# --- duplicatas ---------------------------------------------------------------
def find_by_hash(db: Session, sha256: str) -> Document | None:
    return db.scalar(select(Document).where(Document.sha256 == sha256).limit(1))


def _duplicate_error(existing: Document) -> DuplicateDocumentError:
    return DuplicateDocumentError(
        {
            "id": str(existing.id),
            "title": existing.title,
            "original_filename": existing.original_filename,
            "created_at": existing.created_at.isoformat(),
        }
    )


# --- importação -----------------------------------------------------------
def import_pdf(
    db: Session,
    storage: LocalStorage,
    settings: Settings,
    *,
    stream: BinaryIO,
    filename: str | None,
    content_type: str | None,
    title: str | None = None,
    category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    tag_ids: list[uuid.UUID] | None = None,
) -> Document:
    """Aceita o PDF: valida, armazena o original e registra o documento como `pending`.

    A extração do texto e a geração de chunks NÃO acontecem aqui: ficam para
    `services/processing.py`, em segundo plano. A resposta ao cliente só depende do
    que é rápido e precisa ser síncrono.

    Ordem pensada para não deixar resíduos:
      1. valida o nome e as referências (nada gravado);
      2. grava em arquivo temporário, checando tamanho e assinatura (calcula o SHA-256);
      3. se o SHA-256 já existe, recusa com 409: nada novo é gravado;
      4. abre o PDF e confere a estrutura (corrompido, com senha ou páginas demais => 422,
         nada persistido). Isso é rápido e dá o `page_count`;
      5. grava o registro `pending`, move o arquivo para o destino e confirma a transação.
         Se qualquer passo de 5 falhar, o arquivo definitivo é removido e a transação é
         desfeita. Uma corrida entre dois uploads idênticos é decidida pelo índice único
         de `sha256`: o perdedor recebe o mesmo 409.
    """
    display_name = safe_filename(filename)
    _validate_declared_type(display_name, content_type)
    _check_refs(db, category_id, project_id)
    tags = _load_tags(db, tag_ids or [])

    with storage.stage(stream, settings.max_upload_bytes) as staged:
        existing = find_by_hash(db, staged.sha256)
        if existing is not None:
            raise _duplicate_error(existing)

        reader = pdf.open_pdf(staged.path, settings.max_document_pages)
        page_count = len(reader.pages)

        key = staged.commit()
        try:
            document = Document(
                title=(title or "").strip() or PurePosixPath(display_name).stem[:255] or "Documento",
                original_filename=display_name,
                storage_key=key,
                content_type="application/pdf",
                size_bytes=staged.size,
                sha256=staged.sha256,
                page_count=page_count,
                status=DocumentStatus.PENDING.value,
                has_text=False,
                error_message=None,
                category_id=category_id,
                project_id=project_id,
                tags=tags,
            )
            db.add(document)
            db.flush()
            search.refresh_documents(db, [document.id])  # título, nome do arquivo e organização já pesquisáveis
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            storage.delete(key)
            winner = find_by_hash(db, staged.sha256)  # outra requisição gravou o mesmo arquivo antes
            if winner is not None:
                raise _duplicate_error(winner) from exc
            raise
        except BaseException:
            db.rollback()
            storage.delete(key)
            raise
    return _reload(db, document.id)


# --- reprocessamento ------------------------------------------------------------
def request_reprocess(db: Session, storage: LocalStorage, document_id: uuid.UUID) -> Document:
    """Coloca o documento de volta na fila (`failed`/`completed` -> `pending`).

    A transição é um UPDATE condicional no banco: de várias requisições simultâneas,
    exatamente uma vence; as demais recebem 409 e não iniciam nada. O conteúdo atual
    (páginas e trechos) continua intacto até a nova versão ficar pronta.
    """
    document = get_document(db, document_id)  # 404
    if not storage.exists(document.storage_key):
        raise OriginalFileMissingError()
    moved = db.execute(
        update(Document)
        .where(
            Document.id == document_id,
            Document.status.in_([DocumentStatus.COMPLETED.value, DocumentStatus.FAILED.value]),
        )
        .values(status=DocumentStatus.PENDING.value, error_message=None, updated_at=func.now())
    ).rowcount
    db.commit()
    if moved != 1:
        current = db.scalar(select(Document.status).where(Document.id == document_id))
        if current is None:
            raise NotFoundError("Documento não encontrado.")
        raise ProcessingInProgressError(current)
    return _reload(db, document_id)


def _reload(db: Session, document_id: uuid.UUID) -> Document:
    document = db.scalar(
        select(Document).where(Document.id == document_id).execution_options(populate_existing=True)
    )
    assert document is not None
    return document


# --- consulta -------------------------------------------------------------
def get_document(db: Session, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Documento não encontrado.")
    return document


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_documents(
    db: Session,
    *,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    tag_ids: list[uuid.UUID] | None = None,
    status: str | None = None,
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Document], int]:
    conditions = []
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        conditions.append(
            Document.title.ilike(pattern, escape="\\") | Document.original_filename.ilike(pattern, escape="\\")
        )
    if status:
        conditions.append(Document.status == status)
    if category_id:
        conditions.append(Document.category_id == category_id)
    if project_id:
        conditions.append(Document.project_id == project_id)
    for tag_id in dict.fromkeys(tag_ids or []):
        conditions.append(Document.tags.any(Tag.id == tag_id))

    column = Document.updated_at if sort == "updated_at" else Document.created_at
    direction = asc if order == "asc" else desc
    total = db.scalar(select(func.count()).select_from(Document).where(*conditions)) or 0
    items = db.scalars(
        select(Document).where(*conditions).order_by(direction(column), Document.id).limit(limit).offset(offset)
    ).all()
    return list(items), total


def list_chunks(
    db: Session, document_id: uuid.UUID, *, page_number: int | None, limit: int, offset: int
) -> tuple[list[DocumentChunk], int]:
    get_document(db, document_id)  # 404 se o documento não existir
    conditions = [DocumentChunk.document_id == document_id]
    if page_number is not None:
        conditions.append(DocumentChunk.page_number == page_number)
    total = db.scalar(select(func.count()).select_from(DocumentChunk).where(*conditions)) or 0
    items = db.scalars(
        select(DocumentChunk).where(*conditions).order_by(DocumentChunk.chunk_index).limit(limit).offset(offset)
    ).all()
    return list(items), total


# --- edição ---------------------------------------------------------------
def update_document(db: Session, document: Document, data: DocumentUpdate) -> Document:
    sent = data.model_fields_set
    if "category_id" in sent or "project_id" in sent:
        _check_refs(db, data.category_id if "category_id" in sent else None, data.project_id if "project_id" in sent else None)
    if "category_id" in sent:
        document.category_id = data.category_id
    if "project_id" in sent:
        document.project_id = data.project_id
    if "tag_ids" in sent and data.tag_ids is not None:
        document.tags = _load_tags(db, data.tag_ids)
    if data.title is not None:
        document.title = data.title
    document.updated_at = func.now()
    db.flush()
    search.refresh_documents(db, [document.id])
    db.commit()
    return _reload(db, document.id)


# --- exclusão -------------------------------------------------------------
def delete_document(db: Session, storage: LocalStorage, document: Document) -> None:
    """Remove registro e arquivo de forma consistente.

    O arquivo é renomeado antes (reversível). Se não for possível renomeá-lo ou
    confirmar a transação, nada é perdido e o erro é informado. Arquivo já
    ausente não impede a exclusão do registro.
    """
    key = document.storage_key
    tombstone = storage.mark_for_deletion(key)  # StorageError se falhar: nada foi alterado
    try:
        db.delete(document)
        db.commit()
    except BaseException:
        db.rollback()
        if tombstone is not None:
            storage.restore(key, tombstone)
        raise
    if tombstone is not None:
        storage.purge(tombstone)


def original_path(storage: LocalStorage, document: Document):
    path = storage.path_for(document.storage_key)
    if not path.is_file():
        logger.error("Arquivo ausente para o documento %s", document.id)
        raise NotFoundError("O arquivo original deste documento não foi encontrado no armazenamento.")
    return path

