import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_dispatcher
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.document import (
    DocumentChunkList,
    DocumentContent,
    DocumentPageList,
    DocumentRead,
    DocumentUpdate,
    UploadLimits,
)
from app.services import documents as service
from app.services.processing import Dispatcher
from app.services.storage import LocalStorage, get_storage

logger = logging.getLogger("second_brain.documents")
router = APIRouter(prefix="/documents", tags=["documents"])


def _enqueue(dispatcher: Dispatcher, document_id: uuid.UUID) -> None:
    """Envia ao segundo plano. Se falhar, o documento fica `pending` e é retomado na próxima inicialização."""
    try:
        dispatcher.submit(document_id)
    except Exception:  # noqa: BLE001
        logger.exception("Não foi possível enfileirar o documento %s", document_id)


@router.get("/limits", response_model=UploadLimits)
def upload_limits(settings: Settings = Depends(get_settings)):
    """Limites de importação, para o cliente validar antes de enviar."""
    return UploadLimits(max_upload_bytes=settings.max_upload_bytes, max_pages=settings.max_document_pages)


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def upload_document(
    response: Response,
    file: UploadFile = File(..., description="Arquivo PDF."),
    title: str | None = Form(None, max_length=255),
    category_id: uuid.UUID | None = Form(None),
    project_id: uuid.UUID | None = Form(None),
    tag_ids: list[uuid.UUID] = Form(default_factory=list),
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """Aceita um PDF: valida, armazena o original e registra o documento como `pending`.

    A extração do texto e a geração de chunks continuam em segundo plano: acompanhe o
    `status` em `GET /api/documents/{id}` (`pending` -> `processing` -> `completed`/`failed`).
    """
    document = service.import_pdf(
        db,
        storage,
        settings,
        stream=file.file,
        filename=file.filename,
        content_type=file.content_type,
        title=title,
        category_id=category_id,
        project_id=project_id,
        tag_ids=tag_ids,
    )
    _enqueue(dispatcher, document.id)
    response.headers["Location"] = f"/api/documents/{document.id}"
    return document


@router.get("", response_model=DocumentPageList)
def list_documents(
    q: str | None = Query(None, max_length=200, description="Parte do nome ou do título."),
    category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    tag_id: list[uuid.UUID] = Query(default_factory=list, max_length=10),
    processing_status: Literal["pending", "processing", "completed", "failed"] | None = Query(None, alias="status"),
    sort: Literal["created_at", "updated_at"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    items, total = service.list_documents(
        db, q=q, category_id=category_id, project_id=project_id, tag_ids=tag_id, status=processing_status,
        sort=sort, order=order, limit=limit, offset=offset,
    )
    return DocumentPageList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    return service.get_document(db, document_id)


@router.patch("/{document_id}", response_model=DocumentRead)
def update_document(document_id: uuid.UUID, data: DocumentUpdate, db: Session = Depends(get_db)):
    return service.update_document(db, service.get_document(db, document_id), data)


@router.post("/{document_id}/reprocess", response_model=DocumentRead, status_code=status.HTTP_202_ACCEPTED)
def reprocess_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
    dispatcher: Dispatcher = Depends(get_dispatcher),
):
    """Pede um novo processamento (extração + chunks) a partir do PDF original.

    Aceito (202) para `failed` e `completed`. Em `pending`/`processing` responde 409 e
    não inicia nada. O conteúdo atual só é substituído quando a nova versão estiver
    pronta; em falha, ele é mantido.
    """
    document = service.request_reprocess(db, storage, document_id)
    _enqueue(dispatcher, document.id)
    return document


@router.get("/{document_id}/content", response_model=DocumentContent)
def get_document_content(document_id: uuid.UUID, db: Session = Depends(get_db)):
    """Texto extraído, página por página."""
    document = service.get_document(db, document_id)
    return DocumentContent(
        id=document.id,
        title=document.title,
        status=document.status,
        has_text=document.has_text,
        page_count=document.page_count,
        pages=document.pages,
    )


@router.get("/{document_id}/chunks", response_model=DocumentChunkList)
def list_document_chunks(
    document_id: uuid.UUID,
    page_number: int | None = Query(None, ge=1, description="Apenas trechos desta página."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Trechos gerados do documento, em ordem, com a página de origem de cada um."""
    items, total = service.list_chunks(db, document_id, page_number=page_number, limit=limit, offset=offset)
    return DocumentChunkList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{document_id}/file")
def download_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
):
    """Baixa o PDF original."""
    document = service.get_document(db, document_id)
    path = service.original_path(storage, document)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document.original_filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
):
    service.delete_document(db, storage, service.get_document(db, document_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
