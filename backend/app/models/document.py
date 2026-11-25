import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.db.base import Base
from app.models.category import Category
from app.models.project import Project
from app.models.tag import Tag

document_tags = Table(
    "document_tags",
    Base.metadata,
    Column("document_id", Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Uuid, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_document_tags_tag_id", "tag_id"),
)


class DocumentStatus(str, enum.Enum):
    # Nesta fase o processamento é síncrono: o cliente só observa completed/failed.
    # pending/processing ficam reservados para o processamento assíncrono futuro.
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_documents_status",
        ),
        CheckConstraint("size_bytes > 0", name="ck_documents_size_positive"),
        Index("ix_documents_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Chave interna no armazenamento (`<uuid>.pdf`). Nunca é exposta pela API.
    storage_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/pdf")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Único: o mesmo conteúdo binário não pode ser importado duas vezes (ver DuplicateDocumentError).
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=DocumentStatus.PENDING.value)
    # Concluído sem texto (ex.: PDF digitalizado): não é falha, só não há o que pesquisar.
    has_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR().with_variant(Text(), "sqlite"), deferred=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    category: Mapped[Category | None] = relationship(lazy="selectin")
    project: Mapped[Project | None] = relationship(lazy="selectin")
    tags: Mapped[list[Tag]] = relationship(secondary=document_tags, lazy="selectin", order_by=Tag.name)
    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document",
        order_by="DocumentPage.page_number",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        order_by="DocumentChunk.chunk_index",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )


Index("ix_documents_search_vector", Document.search_vector, postgresql_using="gin")


class DocumentPage(Base):
    """Texto de uma página. Base natural para dividir em trechos/embeddings na próxima fase."""

    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_document_pages_document_page"),
        CheckConstraint("page_number >= 1", name="ck_document_pages_number_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)  # começa em 1
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    document: Mapped[Document] = relationship(back_populates="pages")


class DocumentChunk(Base):
    """Trecho de uma página, para recuperação futura. Não contém embeddings.

    `document_pages` segue sendo a fonte do texto extraído: o chunk guarda uma cópia do
    trecho e a posição exata (`start_offset`/`end_offset`) dentro do texto da página.
    A FK composta garante, no banco, que a página de origem existe; excluir a página
    ou o documento remove os chunks.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE", name="fk_document_chunks_document"
        ),
        ForeignKeyConstraint(
            ["document_id", "page_number"],
            ["document_pages.document_id", "document_pages.page_number"],
            ondelete="CASCADE",
            name="fk_document_chunks_page",
        ),
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_document_index"),
        UniqueConstraint("document_id", "page_number", "start_offset", name="uq_document_chunks_page_start"),
        CheckConstraint("chunk_index >= 0", name="ck_document_chunks_index_nonneg"),
        CheckConstraint("page_number >= 1", name="ck_document_chunks_page_positive"),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="ck_document_chunks_offsets"),
        CheckConstraint(
            "character_count = length(content) AND character_count = end_offset - start_offset",
            name="ck_document_chunks_count",
        ),
        CheckConstraint("length(trim(content)) > 0", name="ck_document_chunks_content_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)  # sequencial no documento, desde 0
    content: Mapped[str] = mapped_column(Text, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="chunks")


# Contagem calculada no próprio SELECT do documento: listar N documentos não gera N consultas.
Document.chunk_count = column_property(  # type: ignore[attr-defined]
    select(func.count(DocumentChunk.id))
    .where(DocumentChunk.document_id == Document.id)
    .correlate_except(DocumentChunk)
    .scalar_subquery()
)
