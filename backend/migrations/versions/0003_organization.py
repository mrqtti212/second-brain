"""categories, projects, tags and note associations

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_created = sa.Column(
    "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
)


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("color", sa.String(7)),
        _created.copy(),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_categories_name_not_blank"),
    )
    op.create_index("uq_categories_name_lower", "categories", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text()),
        _created.copy(),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_projects_name_not_blank"),
    )
    op.create_index("uq_projects_name_lower", "projects", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("color", sa.String(7)),
        _created.copy(),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_tags_name_not_blank"),
    )
    op.create_index("uq_tags_name_lower", "tags", [sa.text("lower(name)")], unique=True)

    # Excluir categoria/projeto não exclui notas: apenas zera a referência.
    op.add_column("notes", sa.Column("category_id", sa.Uuid()))
    op.add_column("notes", sa.Column("project_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_notes_category_id", "notes", "categories", ["category_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_notes_project_id", "notes", "projects", ["project_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_notes_category_id", "notes", ["category_id"])
    op.create_index("ix_notes_project_id", "notes", ["project_id"])

    op.create_table(
        "note_tags",
        sa.Column("note_id", sa.Uuid(), sa.ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.Uuid(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_note_tags_tag_id", "note_tags", ["tag_id"])


def downgrade() -> None:
    op.drop_table("note_tags")
    op.drop_index("ix_notes_project_id", table_name="notes")
    op.drop_index("ix_notes_category_id", table_name="notes")
    op.drop_constraint("fk_notes_project_id", "notes", type_="foreignkey")
    op.drop_constraint("fk_notes_category_id", "notes", type_="foreignkey")
    op.drop_column("notes", "project_id")
    op.drop_column("notes", "category_id")
    op.drop_table("tags")
    op.drop_table("projects")
    op.drop_table("categories")
