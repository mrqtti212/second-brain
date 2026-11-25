import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.organization import CategorySummary, ProjectSummary, TagSummary


def _clean_title(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("O título não pode ficar vazio.")
    return value


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(default="", max_length=200_000)
    category_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)

    _strip_title = field_validator("title")(_clean_title)


class NoteUpdate(BaseModel):
    """PATCH parcial. Campos omitidos não são alterados.

    - `category_id`/`project_id` enviados como null removem a associação.
    - `tag_ids`, quando enviado, substitui o conjunto de etiquetas.
    - `title`/`content` nulos são ignorados.
    """

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, max_length=200_000)
    category_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str | None) -> str | None:
        return None if value is None else _clean_title(value)


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    content: str
    category: CategorySummary | None
    project: ProjectSummary | None
    tags: list[TagSummary]
    created_at: datetime
    updated_at: datetime
