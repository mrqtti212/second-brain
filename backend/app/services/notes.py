import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import InvalidReferenceError, NotFoundError
from app.models.category import Category
from app.models.note import Note
from app.models.project import Project
from app.models.tag import Tag
from app.schemas.note import NoteCreate, NoteUpdate
from app.services import search


def list_notes(db: Session, *, limit: int = 50, offset: int = 0) -> Sequence[Note]:
    stmt = select(Note).order_by(Note.updated_at.desc(), Note.id).limit(limit).offset(offset)
    return db.scalars(stmt).all()


def get_note(db: Session, note_id: uuid.UUID) -> Note:
    note = db.get(Note, note_id)
    if note is None:
        raise NotFoundError("Nota não encontrada.")
    return note


def _check_category(db: Session, category_id: uuid.UUID | None) -> None:
    if category_id is not None and db.get(Category, category_id) is None:
        raise InvalidReferenceError("Categoria não encontrada.")


def _check_project(db: Session, project_id: uuid.UUID | None) -> None:
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


def _reload(db: Session, note_id: uuid.UUID) -> Note:
    """Relê a nota com relações atualizadas (após commit)."""
    note = db.scalar(
        select(Note).where(Note.id == note_id).execution_options(populate_existing=True)
    )
    assert note is not None
    return note


def create_note(db: Session, data: NoteCreate) -> Note:
    _check_category(db, data.category_id)
    _check_project(db, data.project_id)
    note = Note(
        title=data.title,
        content=data.content,
        category_id=data.category_id,
        project_id=data.project_id,
        tags=_load_tags(db, data.tag_ids),
    )
    db.add(note)
    db.flush()  # gera o id antes de calcular o vetor de busca
    search.refresh_notes(db, [note.id])
    db.commit()
    return _reload(db, note.id)


def update_note(db: Session, note: Note, data: NoteUpdate) -> Note:
    sent = data.model_fields_set
    if "category_id" in sent:
        _check_category(db, data.category_id)
        note.category_id = data.category_id
    if "project_id" in sent:
        _check_project(db, data.project_id)
        note.project_id = data.project_id
    if "tag_ids" in sent and data.tag_ids is not None:
        note.tags = _load_tags(db, data.tag_ids)
    if data.title is not None:
        note.title = data.title
    if data.content is not None:
        note.content = data.content
    # Garante UPDATE (e updated_at) mesmo quando só relações mudaram.
    note.updated_at = func.now()
    db.flush()
    search.refresh_notes(db, [note.id])
    db.commit()
    return _reload(db, note.id)


def delete_note(db: Session, note: Note) -> None:
    db.delete(note)  # note_tags é removida pelo ORM e pelo ON DELETE CASCADE
    db.commit()


def add_tag(db: Session, note: Note, tag_id: uuid.UUID) -> Note:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise NotFoundError("Etiqueta não encontrada.")
    if tag not in note.tags:
        note.tags = [*note.tags, tag]
        note.updated_at = func.now()
        db.flush()
        search.refresh_notes(db, [note.id])
        db.commit()
    return _reload(db, note.id)


def remove_tag(db: Session, note: Note, tag_id: uuid.UUID) -> Note:
    remaining = [t for t in note.tags if t.id != tag_id]
    if len(remaining) != len(note.tags):
        note.tags = remaining
        note.updated_at = func.now()
        db.flush()
        search.refresh_notes(db, [note.id])
        db.commit()
    return _reload(db, note.id)

