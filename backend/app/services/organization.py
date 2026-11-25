"""CRUD compartilhado por categorias, projetos e etiquetas."""

import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models.category import Category
from app.models.document import Document, document_tags
from app.models.note import Note, note_tags
from app.models.project import Project
from app.models.tag import Tag
from app.services import search

Model = type[Category] | type[Project] | type[Tag]

LABELS = {Category: "Categoria", Project: "Projeto", Tag: "Etiqueta"}
DUPLICATE = {
    Category: "Já existe uma categoria com este nome.",
    Project: "Já existe um projeto com este nome.",
    Tag: "Já existe uma etiqueta com este nome.",
}


def _notes_count(model: Model):
    if model is Category:
        return select(func.count()).where(Note.category_id == Category.id).scalar_subquery()
    if model is Project:
        return select(func.count()).where(Note.project_id == Project.id).scalar_subquery()
    return select(func.count()).where(note_tags.c.tag_id == Tag.id).scalar_subquery()


def _documents_count(model: Model):
    if model is Category:
        return select(func.count()).where(Document.category_id == Category.id).scalar_subquery()
    if model is Project:
        return select(func.count()).where(Document.project_id == Project.id).scalar_subquery()
    return select(func.count()).where(document_tags.c.tag_id == Tag.id).scalar_subquery()


def _affected_ids(db: Session, model: Model, item_id: uuid.UUID) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """(ids de notas, ids de documentos) cujo vetor de busca depende deste item."""
    if model is Category:
        notes = select(Note.id).where(Note.category_id == item_id)
        docs = select(Document.id).where(Document.category_id == item_id)
    elif model is Project:
        notes = select(Note.id).where(Note.project_id == item_id)
        docs = select(Document.id).where(Document.project_id == item_id)
    else:
        notes = select(note_tags.c.note_id).where(note_tags.c.tag_id == item_id)
        docs = select(document_tags.c.document_id).where(document_tags.c.tag_id == item_id)
    return list(db.scalars(notes)), list(db.scalars(docs))


def _refresh_affected(db: Session, affected: tuple[list[uuid.UUID], list[uuid.UUID]]) -> None:
    search.refresh_notes(db, affected[0])
    search.refresh_documents(db, affected[1])


def _with_count(item: Any, notes: int, documents: int) -> Any:
    item.notes_count = notes
    item.documents_count = documents
    return item


def list_items(db: Session, model: Model) -> list[Any]:
    rows = db.execute(
        select(model, _notes_count(model), _documents_count(model)).order_by(func.lower(model.name))
    ).all()
    return [_with_count(item, n, d) for item, n, d in rows]


def get_item(db: Session, model: Model, item_id: uuid.UUID) -> Any:
    row = db.execute(select(model, _notes_count(model), _documents_count(model)).where(model.id == item_id)).first()
    if row is None:
        raise NotFoundError(f"{LABELS[model]} não encontrada." if model is not Project else "Projeto não encontrado.")
    return _with_count(*row)


def create_item(db: Session, model: Model, data: BaseModel) -> Any:
    item = model(**data.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(DUPLICATE[model]) from exc
    return _with_count(item, 0, 0)


def update_item(db: Session, model: Model, item_id: uuid.UUID, data: BaseModel) -> Any:
    item = get_item(db, model, item_id)
    changes = data.model_dump(exclude_unset=True)
    renamed = "name" in changes and changes["name"] != item.name
    for field, value in changes.items():
        setattr(item, field, value)
    try:
        db.flush()
        if renamed:  # o nome faz parte do vetor de busca das notas associadas
            _refresh_affected(db, _affected_ids(db, model, item_id))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(DUPLICATE[model]) from exc
    return item


def delete_item(db: Session, model: Model, item_id: uuid.UUID) -> None:
    item = get_item(db, model, item_id)
    affected = _affected_ids(db, model, item_id)
    # As notas são preservadas: o banco aplica SET NULL (categoria/projeto)
    # ou CASCADE apenas em note_tags (etiqueta).
    db.delete(item)
    db.flush()
    _refresh_affected(db, affected)
    db.commit()
