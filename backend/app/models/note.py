import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Table, Text, Uuid, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.category import Category
from app.models.project import Project
from app.models.tag import Tag

# Associação N:N. A chave composta impede duplicidade; o CASCADE remove
# as associações quando a nota ou a etiqueta é excluída (as notas nunca
# são removidas por causa de uma etiqueta).
note_tags = Table(
    "note_tags",
    Base.metadata,
    Column("note_id", Uuid, ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Uuid, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_note_tags_tag_id", "tag_id"),
)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # SET NULL: excluir categoria/projeto apenas desassocia a nota.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    # Vetor de busca persistido (PostgreSQL). Mantido por services/search.py.
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR().with_variant(Text(), "sqlite"), deferred=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # selectin: uma consulta extra por relação para a página inteira (sem N+1).
    category: Mapped[Category | None] = relationship(lazy="selectin")
    project: Mapped[Project | None] = relationship(lazy="selectin")
    tags: Mapped[list[Tag]] = relationship(
        secondary=note_tags, lazy="selectin", order_by=Tag.name
    )


Index("ix_notes_search_vector", Note.search_vector, postgresql_using="gin")
