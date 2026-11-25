import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.search import SearchPage
from app.services import search as search_service

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchPage)
def search(
    q: str | None = Query(None, max_length=200, description="Termos de busca (texto livre)."),
    content_type: Literal["all", "note", "document"] = Query("all", alias="type", description="Tipo de conteúdo."),
    category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    tag_id: list[uuid.UUID] = Query(default_factory=list, max_length=10),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Busca textual em notas e documentos. Sem `q`, lista tudo (filtrado) por data de atualização."""
    return search_service.search(
        db,
        q=q,
        content_type=content_type,
        category_id=category_id,
        project_id=project_id,
        tag_ids=tag_id,
        limit=limit,
        offset=offset,
    )
