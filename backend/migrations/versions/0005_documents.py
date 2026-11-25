"""documents, document pages and document tags

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("has_text", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_message", sa.Text()),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("search_vector", TSVECTOR()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("storage_key", name="uq_documents_storage_key"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')", name="ck_documents_status"
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_documents_size_positive"),
    )
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.create_index("ix_documents_category_id", "documents", ["category_id"])
    op.create_index("ix_documents_project_id", "documents", ["project_id"])
    op.create_index("ix_documents_created_at", "documents", ["created_at"])
    op.create_index("ix_documents_search_vector", "documents", ["search_vector"], postgresql_using="gin")

    op.create_table(
        "document_pages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.UniqueConstraint("document_id", "page_number", name="uq_document_pages_document_page"),
        sa.CheckConstraint("page_number >= 1", name="ck_document_pages_number_positive"),
    )

    op.create_table(
        "document_tags",
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.Uuid(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_document_tags_tag_id", "document_tags", ["tag_id"])


def downgrade() -> None:
    op.drop_table("document_tags")
    op.drop_table("document_pages")
    op.drop_table("documents")
