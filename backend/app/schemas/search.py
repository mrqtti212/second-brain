import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.organization import CategorySummary, ProjectSummary, TagSummary


class SearchResult(BaseModel):
    # Notas e documentos compartilham a mesma lista de resultados.
    type: Literal["note", "document"] = "note"
    id: uuid.UUID
    title: str
    # Trecho do conteúdo. Termos encontrados vêm entre U+E000 e U+E001
    # (caracteres privados), para o cliente destacar sem interpretar HTML.
    snippet: str
    updated_at: datetime
    category: CategorySummary | None
    project: ProjectSummary | None
    tags: list[TagSummary]
    # Relevância (ts_rank_cd). Nulo quando não há termo de busca.
    score: float | None
    # Apenas documentos:
    status: str | None = None
    page_count: int | None = None
    has_text: bool | None = None


class SearchPage(BaseModel):
    items: list[SearchResult]
    total: int
    limit: int
    offset: int
