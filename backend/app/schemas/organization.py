import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.common import Color, Description, Name


class _Nullable(BaseModel):
    """Em PATCH, `name` não aceita null; os demais campos aceitam (limpam o valor)."""

    @field_validator("name", check_fields=False)
    @classmethod
    def _name_not_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("O nome não pode ser nulo.")
        return value


# --- Categoria ---
class CategoryCreate(BaseModel):
    name: Name
    description: Description | None = None
    color: Color | None = None


class CategoryUpdate(_Nullable):
    name: Name | None = None
    description: Description | None = None
    color: Color | None = None


class CategorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    color: str | None


class CategoryRead(CategorySummary):
    description: str | None
    created_at: datetime
    notes_count: int = 0
    documents_count: int = 0


# --- Projeto ---
class ProjectCreate(BaseModel):
    name: Name
    description: Description | None = None


class ProjectUpdate(_Nullable):
    name: Name | None = None
    description: Description | None = None


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


class ProjectRead(ProjectSummary):
    description: str | None
    created_at: datetime
    notes_count: int = 0
    documents_count: int = 0


# --- Etiqueta ---
class TagCreate(BaseModel):
    name: Name
    color: Color | None = None


class TagUpdate(_Nullable):
    name: Name | None = None
    color: Color | None = None


class TagSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    color: str | None


class TagRead(TagSummary):
    created_at: datetime
    notes_count: int = 0
    documents_count: int = 0
