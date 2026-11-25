"""persisted full-text search vector on notes

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notes", sa.Column("search_vector", TSVECTOR()))
    # Preenche notas já existentes (A=título, B=categoria/projeto/etiquetas, C=conteúdo).
    op.execute(
        """
        UPDATE notes SET search_vector =
            setweight(to_tsvector('portuguese', coalesce(notes.title, '')), 'A')
            || setweight(to_tsvector('portuguese',
                 coalesce((SELECT c.name FROM categories c WHERE c.id = notes.category_id), '')
                 || ' ' || coalesce((SELECT p.name FROM projects p WHERE p.id = notes.project_id), '')
                 || ' ' || coalesce((SELECT string_agg(t.name, ' ') FROM note_tags nt
                                     JOIN tags t ON t.id = nt.tag_id
                                     WHERE nt.note_id = notes.id), '')), 'B')
            || setweight(to_tsvector('portuguese', coalesce(notes.content, '')), 'C')
        """
    )
    op.create_index("ix_notes_search_vector", "notes", ["search_vector"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_notes_search_vector", table_name="notes")
    op.drop_column("notes", "search_vector")
