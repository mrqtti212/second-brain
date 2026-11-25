import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.organization import CategorySummary, ProjectSummary, TagSummary

DocumentStatusLiteral = Literal["pending", "processing", "completed", "failed"]


class DocumentRead(BaseModel):
    """Metadados do documento. Não inclui chave ou caminho de armazenamento."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    page_count: int | None
    chunk_count: int = 0
    status: DocumentStatusLiteral
    has_text: bool
    error_message: str | None
    category: CategorySummary | None
    project: ProjectSummary | None
    tags: list[TagSummary]
    created_at: datetime
    updated_at: datetime


class DocumentPageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_number: int
    text: str


class DocumentContent(BaseModel):
    id: uuid.UUID
    title: str
    status: DocumentStatusLiteral
    has_text: bool
    page_count: int | None
    pages: list[DocumentPageRead]


class DocumentPageList(BaseModel):
    items: list[DocumentRead]
    total: int
    limit: int
    offset: int


class DocumentChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chunk_index: int
    page_number: int
    content: str
    character_count: int
    # Posição do trecho dentro do texto da página (`texto[start_offset:end_offset] == content`).
    start_offset: int
    end_offset: int


class DocumentChunkList(BaseModel):
    items: list[DocumentChunkRead]
    total: int
    limit: int
    offset: int


class DocumentUpdate(BaseModel):
    """PATCH parcial; mesma semântica das notas (omitido = não muda, null = remove).

    Só título, categoria, projeto e etiquetas são editáveis. Qualquer outro campo
    (id, arquivo, hash...) é rejeitado com 422 em vez de ignorado.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("O título não pode ficar vazio.")
        return value


class UploadLimits(BaseModel):
    max_upload_bytes: int
    max_pages: int
