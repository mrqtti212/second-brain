"""chunk embeddings

Cria `chunk_embeddings` (um vetor `vector(384)` por trecho de `document_chunks`) e o índice
HNSW por cosseno. 384 é a dimensão de `intfloat/multilingual-e5-small`, o modelo candidato.

Exige a extensão `vector` (migration 0002) e pgvector >= 0.5 (HNSW). A tabela nasce vazia e
não altera nenhum dado existente. Os vetores são derivados dos trechos: podem ser apagados e
regerados. O `downgrade` apaga a tabela (e com ela todos os vetores) e não remove a extensão.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DIMENSIONS = 384  # fixa nesta migration; outra dimensão exige outra migration


def upgrade() -> None:
    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", sa.Uuid(), primary_key=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("embedding", VECTOR(DIMENSIONS), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["document_chunks.id"], ondelete="CASCADE", name="fk_chunk_embeddings_chunk"
        ),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_chunk_embeddings_hash_length"),
        sa.CheckConstraint("dimensions = vector_dims(embedding)", name="ck_chunk_embeddings_dimensions"),
    )
    # Reaproveitar o vetor de um trecho de conteúdo idêntico depois de um reprocessamento.
    op.create_index("ix_chunk_embeddings_reuse", "chunk_embeddings", ["content_sha256", "model"])
    op.create_index(
        "ix_chunk_embeddings_embedding_hnsw",
        "chunk_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )


def downgrade() -> None:
    op.drop_index("ix_chunk_embeddings_embedding_hnsw", table_name="chunk_embeddings")
    op.drop_index("ix_chunk_embeddings_reuse", table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")
