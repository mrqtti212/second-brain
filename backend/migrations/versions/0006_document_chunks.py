"""document chunks and unique document hash

Cria `document_chunks` (trechos por página, sem embeddings) e torna `documents.sha256`
único. Não depende de pgvector. Documentos e páginas existentes não são alterados.

A criação do índice único falha se já existirem documentos com o mesmo SHA-256
(a Fase 3.1 aceitava duplicatas). Nesse caso a migration aborta ANTES de qualquer
alteração, listando os grupos; resolva excluindo as cópias e rode de novo.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Em modo offline (`alembic upgrade --sql`) não há banco para consultar.
    duplicates = (
        []
        if op.get_context().as_sql
        else op.get_bind().execute(
            sa.text("SELECT sha256, count(*) AS n FROM documents GROUP BY sha256 HAVING count(*) > 1")
        ).all()
    )
    if duplicates:
        listing = "; ".join(f"{row.sha256[:12]}… ({row.n} documentos)" for row in duplicates[:10])
        raise RuntimeError(
            f"Existem {len(duplicates)} grupo(s) de documentos com o mesmo SHA-256: {listing}. "
            "Exclua as cópias pela interface ou pela API e execute a migration novamente. "
            "Nenhum dado foi alterado."
        )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE", name="fk_document_chunks_document"),
        # A página de origem precisa existir: referencia o par único de document_pages.
        sa.ForeignKeyConstraint(
            ["document_id", "page_number"],
            ["document_pages.document_id", "document_pages.page_number"],
            ondelete="CASCADE",
            name="fk_document_chunks_page",
        ),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_document_index"),
        sa.UniqueConstraint("document_id", "page_number", "start_offset", name="uq_document_chunks_page_start"),
        sa.CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index_nonneg"),
        sa.CheckConstraint("page_number >= 1", name="ck_document_chunks_page_positive"),
        sa.CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="ck_document_chunks_offsets"),
        sa.CheckConstraint(
            "character_count = length(content) AND character_count = end_offset - start_offset",
            name="ck_document_chunks_count",
        ),
        sa.CheckConstraint("length(trim(content)) > 0", name="ck_document_chunks_content_not_blank"),
    )

    # O índice não único da 0005 dá lugar a um único, com o mesmo nome.
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.create_index("ix_documents_sha256", "documents", ["sha256"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.drop_table("document_chunks")
