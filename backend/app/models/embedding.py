import uuid
from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import EMBEDDING_SCHEMA_DIMENSIONS
from app.db.base import Base


class ChunkEmbedding(Base):
    """Vetor de um trecho (`document_chunks`). Dados derivados: podem ser apagados e regerados.

    Um vetor por trecho (a chave é `chunk_id`): trocar de modelo substitui os vetores, e a busca
    nunca mistura modelos. `content_sha256` é o hash do texto do trecho; como os trechos recebem
    UUIDs novos a cada reprocessamento, é ele que permite reaproveitar o vetor de um trecho de
    conteúdo idêntico (Etapa B). Excluir o trecho, a página ou o documento remove o vetor.

    O tipo `vector` e o índice HNSW existem só no PostgreSQL. No SQLite (testes) a coluna guarda o
    vetor como texto e o índice e o check de dimensão não são criados.
    """

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        CheckConstraint("length(content_sha256) = 64", name="ck_chunk_embeddings_hash_length"),
        # O `vector_dims` é do pgvector; o SQLite não o conhece.
        CheckConstraint(
            "dimensions = vector_dims(embedding)", name="ck_chunk_embeddings_dimensions"
        ).ddl_if(dialect="postgresql"),
        Index("ix_chunk_embeddings_reuse", "content_sha256", "model"),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_chunks.id", ondelete="CASCADE", name="fk_chunk_embeddings_chunk"),
        primary_key=True,
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(EMBEDDING_SCHEMA_DIMENSIONS), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# Vizinhos mais próximos por cosseno (`<=>`). Parâmetros iguais aos padrões do pgvector, explícitos.
Index(
    "ix_chunk_embeddings_embedding_hnsw",
    ChunkEmbedding.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
    postgresql_with={"m": 16, "ef_construction": 64},
).ddl_if(dialect="postgresql")
