import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.note import NoteCreate, NoteRead, NoteUpdate
from app.services import notes as notes_service

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=list[NoteRead])
def list_notes(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return notes_service.list_notes(db, limit=limit, offset=offset)


@router.post("", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
def create_note(data: NoteCreate, db: Session = Depends(get_db)):
    return notes_service.create_note(db, data)


@router.get("/{note_id}", response_model=NoteRead)
def get_note(note_id: uuid.UUID, db: Session = Depends(get_db)):
    return notes_service.get_note(db, note_id)


@router.patch("/{note_id}", response_model=NoteRead)
def update_note(note_id: uuid.UUID, data: NoteUpdate, db: Session = Depends(get_db)):
    note = notes_service.get_note(db, note_id)
    return notes_service.update_note(db, note, data)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: uuid.UUID, db: Session = Depends(get_db)):
    note = notes_service.get_note(db, note_id)
    notes_service.delete_note(db, note)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{note_id}/tags/{tag_id}", response_model=NoteRead)
def add_tag(note_id: uuid.UUID, tag_id: uuid.UUID, db: Session = Depends(get_db)):
    """Associa uma etiqueta à nota. Idempotente."""
    note = notes_service.get_note(db, note_id)
    return notes_service.add_tag(db, note, tag_id)


@router.delete("/{note_id}/tags/{tag_id}", response_model=NoteRead)
def remove_tag(note_id: uuid.UUID, tag_id: uuid.UUID, db: Session = Depends(get_db)):
    """Desassocia uma etiqueta da nota. Idempotente."""
    note = notes_service.get_note(db, note_id)
    return notes_service.remove_tag(db, note, tag_id)
