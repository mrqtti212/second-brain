"""Geração e persistência de embeddings dos trechos (Etapa B).

Modelo
------
* O **banco é a fonte da verdade**. Um trecho está "pendente" quando não tem linha em
  `chunk_embeddings` para o modelo do provedor atual. Não há coluna de estado: o que falta
  é derivado dessa contagem, então reiniciar, repetir ou rodar o comando de manutenção
  sempre converge para o mesmo resultado.
* **Fora da troca atômica do processamento.** O documento já é `completed` (texto e trechos
  utilizáveis) quando o vetor é gerado. Falha do provedor nunca muda o estado do documento.
* **Idempotente e retomável.** Cada lote é gravado e confirmado sozinho; uma falha no meio
  preserva os lotes anteriores e a próxima execução continua do que falta.
* **Sem chamadas desnecessárias.** Antes de chamar o provedor, o vetor é copiado de qualquer
  trecho com o mesmo texto (`content_sha256`) e o mesmo modelo, inclusive de outro documento.
  Textos repetidos no mesmo documento são enviados uma única vez. No reprocessamento, os
  vetores dos trechos antigos são copiados para os novos trechos de mesmo texto dentro da
  própria troca atômica (`snapshot_embeddings`/`restore_embeddings`).
* **Uma tarefa por documento neste processo** (trava em memória). Entre processos, a gravação
  usa `ON CONFLICT DO NOTHING`: duas execuções simultâneas nunca duplicam nem quebram, no
  máximo repetem uma chamada ao provedor.
* Logs e mensagens de erro trazem só ids e o tipo da exceção, nunca o texto dos documentos.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol, TypeVar

from sqlalchemy import Insert, delete, exists, or_, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.core.config import EMBEDDING_SCHEMA_DIMENSIONS, Settings, get_settings
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.embedding import ChunkEmbedding
from app.services.embeddings import (
    EmbeddingConfigError,
    EmbeddingProvider,
    EmbeddingTransientError,
    text_sha256,
    validate_vectors,
)

logger = logging.getLogger("second_brain.embeddings")

DONE, FAILED, BUSY, SKIPPED, DELETED = "completed", "failed", "busy", "skipped", "deleted"

T = TypeVar("T")


@dataclass
class EmbedResult:
    status: str  # completed | failed | busy | skipped (documento não concluído) | deleted
    generated: int = 0  # vetores calculados pelo provedor (um por texto distinto)
    reused: int = 0  # trechos gravados sem vetor próprio do provedor (copiados ou texto repetido)
    remaining: int = 0  # trechos que ainda estão sem vetor depois desta execução
    provider_calls: int = 0  # chamadas feitas ao provedor, contando repetições
    error: str | None = None  # só o nome do tipo da exceção


# --- trava por documento (neste processo) -------------------------------------------
_active: set[uuid.UUID] = set()
_active_lock = threading.Lock()


def _acquire(document_id: uuid.UUID) -> bool:
    with _active_lock:
        if document_id in _active:
            return False
        _active.add(document_id)
        return True


def _release(document_id: uuid.UUID) -> None:
    with _active_lock:
        _active.discard(document_id)


# --- consultas -------------------------------------------------------------------------
def _insert_ignoring_conflicts(db: Session) -> Insert:
    """INSERT ... ON CONFLICT DO NOTHING na chave `chunk_id`, para o dialeto em uso."""
    name = db.get_bind().dialect.name
    if name == "postgresql":
        return postgresql.insert(ChunkEmbedding).on_conflict_do_nothing(index_elements=["chunk_id"])
    if name == "sqlite":
        return sqlite.insert(ChunkEmbedding).on_conflict_do_nothing(index_elements=["chunk_id"])
    raise NotImplementedError(f"Dialeto sem suporte para embeddings: {name}")


def _pending_chunks(db: Session, document_id: uuid.UUID, model: str) -> list[tuple[uuid.UUID, str]]:
    """Trechos do documento sem vetor do modelo informado, na ordem do documento."""
    rows = db.execute(
        select(DocumentChunk.id, DocumentChunk.content, ChunkEmbedding.model)
        .outerjoin(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    ).all()
    return [(chunk_id, content) for chunk_id, content, current in rows if current != model]


def documents_pending_embedding(db: Session, model: str) -> list[uuid.UUID]:
    """Documentos concluídos com algum trecho sem vetor do modelo (fila derivada do banco)."""
    missing = (
        select(DocumentChunk.id)
        .outerjoin(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
        .where(
            DocumentChunk.document_id == Document.id,
            or_(ChunkEmbedding.chunk_id.is_(None), ChunkEmbedding.model != model),
        )
        .correlate(Document)
    )
    return list(
        db.scalars(
            select(Document.id)
            .where(Document.status == DocumentStatus.COMPLETED.value, exists(missing))
            .order_by(Document.created_at)
        )
    )


def _known_vectors(db: Session, hashes: Sequence[str], model: str) -> dict[str, list[float]]:
    """Vetores já existentes para esses textos (de qualquer trecho de qualquer documento)."""
    if not hashes:
        return {}
    known: dict[str, list[float]] = {}
    for digest, vector in db.execute(
        select(ChunkEmbedding.content_sha256, ChunkEmbedding.embedding)
        .where(ChunkEmbedding.content_sha256.in_(list(hashes)), ChunkEmbedding.model == model)
        .order_by(ChunkEmbedding.created_at)
    ):
        known.setdefault(digest, list(vector))
    return known


# --- gravação --------------------------------------------------------------------------
def _persist(db: Session, provider: EmbeddingProvider, rows: list[tuple[uuid.UUID, str, list[float]]]) -> int:
    """Grava e confirma um lote. Devolve quantas linhas entraram de fato."""
    if not rows:
        return 0
    ids = [chunk_id for chunk_id, _, _ in rows]
    alive = set(db.scalars(select(DocumentChunk.id).where(DocumentChunk.id.in_(ids))))  # reprocessado no meio?
    rows = [row for row in rows if row[0] in alive]
    if not rows:
        db.rollback()
        return 0
    # Vetores de outro modelo (troca de modelo) dão lugar aos novos, na mesma transação.
    db.execute(
        delete(ChunkEmbedding).where(
            ChunkEmbedding.chunk_id.in_([chunk_id for chunk_id, _, _ in rows]), ChunkEmbedding.model != provider.model
        )
    )
    inserted = db.execute(
        _insert_ignoring_conflicts(db)
        .returning(ChunkEmbedding.chunk_id)  # `rowcount` não é confiável neste INSERT; conta o que de fato entrou
        .values(
            [
                {
                    "chunk_id": chunk_id,
                    "model": provider.model,
                    "dimensions": provider.dimensions,
                    "content_sha256": digest,
                    "embedding": vector,
                }
                for chunk_id, digest, vector in rows
            ]
        )
    ).all()
    db.commit()
    return len(inserted)


def _with_retries(call: Callable[[], T], *, attempts: int, backoff: float, sleep: Callable[[float], None]) -> T:
    """Repete só `EmbeddingTransientError`, com espera que dobra. Na última tentativa, propaga o erro."""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except EmbeddingTransientError as exc:
            if attempt == attempts:
                raise
            logger.warning("Provedor de embeddings falhou (%s); tentativa %d de %d", type(exc).__name__, attempt, attempts)
            sleep(backoff * 2 ** (attempt - 1))
    raise AssertionError("inalcançável")  # pragma: no cover


# --- tarefa principal ----------------------------------------------------------------------
def embed_document(
    db: Session,
    provider: EmbeddingProvider,
    settings: Settings,
    document_id: uuid.UUID,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> EmbedResult:
    """Gera os vetores que faltam de um documento. Nunca levanta por falha do provedor."""
    if not _acquire(document_id):
        return EmbedResult(BUSY)
    try:
        return _embed(db, provider, settings, document_id, sleep)
    finally:
        _release(document_id)


def _embed(
    db: Session, provider: EmbeddingProvider, settings: Settings, document_id: uuid.UUID, sleep: Callable[[float], None]
) -> EmbedResult:
    status = db.scalar(select(Document.status).where(Document.id == document_id))
    if status is None:
        return EmbedResult(DELETED)
    if status != DocumentStatus.COMPLETED.value:
        return EmbedResult(SKIPPED)  # ainda será (re)processado; o fim do processamento dispara a geração

    result = EmbedResult(DONE)
    written = 0
    try:
        if provider.dimensions != EMBEDDING_SCHEMA_DIMENSIONS:  # a coluna é vector(384): nada é chamado nem gravado
            raise EmbeddingConfigError(
                f"O provedor produz {provider.dimensions} dimensões; o esquema do banco exige {EMBEDDING_SCHEMA_DIMENSIONS}."
            )
        pending = [(chunk_id, text_sha256(content), content) for chunk_id, content in _pending_chunks(db, document_id, provider.model)]
        if not pending:
            return result
        db.rollback()

        vectors = _known_vectors(db, sorted({digest for _, digest, _ in pending}), provider.model)
        texts: dict[str, str] = {}
        for _, digest, content in pending:
            if digest not in vectors:
                texts.setdefault(digest, content)  # textos repetidos são enviados uma vez só
        db.rollback()

        by_digest: dict[str, list[uuid.UUID]] = {}
        for chunk_id, digest, _ in pending:
            by_digest.setdefault(digest, []).append(chunk_id)

        # 1) o que já tem vetor conhecido não passa pelo provedor
        reusable = [(c, d, vectors[d]) for d, ids in by_digest.items() if d in vectors for c in ids]
        written += _persist(db, provider, reusable)

        # 2) o restante, em lotes; cada lote é confirmado sozinho
        digests = list(texts)
        for start in range(0, len(digests), settings.embedding_batch_size):
            batch = digests[start : start + settings.embedding_batch_size]
            batch_texts = [texts[d] for d in batch]

            def call(texts_=batch_texts) -> list[list[float]]:
                result.provider_calls += 1
                return provider.embed_passages(texts_)

            computed = _with_retries(
                call,
                attempts=settings.embedding_max_attempts,
                backoff=settings.embedding_retry_backoff_seconds,
                sleep=sleep,
            )
            validate_vectors(provider, batch_texts, computed)
            result.generated += len(batch)
            rows = [(c, d, list(v)) for d, v in zip(batch, computed) for c in by_digest[d]]
            written += _persist(db, provider, rows)
    except Exception as exc:  # noqa: BLE001 - o documento continua `completed`; a próxima execução retoma
        db.rollback()
        result.status = FAILED
        result.error = type(exc).__name__
        logger.warning("Embeddings do documento %s incompletos (%s)", document_id, type(exc).__name__)
    result.reused = max(written - result.generated, 0)
    result.remaining = len(_pending_chunks(db, document_id, provider.model))
    db.rollback()
    if result.status == DONE and result.remaining:
        result.status = FAILED  # gravação concorrente ou trecho trocado no meio: uma nova execução completa
        result.error = result.error or "RemainingChunks"
    return result


# --- reprocessamento: preservar vetores de trechos com o mesmo texto -------------------------
@dataclass(frozen=True)
class SavedEmbedding:
    model: str
    dimensions: int
    vector: list[float]


def snapshot_embeddings(db: Session, document_id: uuid.UUID) -> dict[str, SavedEmbedding]:
    """Vetores atuais do documento, por hash do texto. Chamar ANTES de apagar os trechos."""
    saved: dict[str, SavedEmbedding] = {}
    for digest, model, dimensions, vector in db.execute(
        select(ChunkEmbedding.content_sha256, ChunkEmbedding.model, ChunkEmbedding.dimensions, ChunkEmbedding.embedding)
        .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    ):
        saved.setdefault(digest, SavedEmbedding(model, dimensions, list(vector)))
    return saved


def restore_embeddings(db: Session, chunks: Sequence[DocumentChunk], saved: dict[str, SavedEmbedding]) -> int:
    """Copia os vetores salvos para os novos trechos de mesmo texto. Os trechos já devem ter id (flush)."""
    rows = []
    for chunk in chunks:
        previous = saved.get(text_sha256(chunk.content))
        if previous is not None:
            rows.append(
                {
                    "chunk_id": chunk.id,
                    "model": previous.model,
                    "dimensions": previous.dimensions,
                    "content_sha256": text_sha256(chunk.content),
                    "embedding": previous.vector,
                }
            )
    if rows:
        db.execute(_insert_ignoring_conflicts(db).values(rows))
    return len(rows)


# --- execução em segundo plano ---------------------------------------------------------------
class EmbeddingRunner:
    """Executa `embed_document` com sessão própria (nunca compartilhada entre threads)."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        provider: EmbeddingProvider,
        settings_factory: Callable[[], Settings] = get_settings,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session_factory = session_factory
        self.provider = provider
        self._settings_factory = settings_factory
        self._sleep = sleep

    def run(self, document_id: uuid.UUID) -> EmbedResult:
        with self._session_factory() as db:
            return embed_document(db, self.provider, self._settings_factory(), document_id, sleep=self._sleep)


class EmbeddingDispatcher(Protocol):
    def submit(self, document_id: uuid.UUID) -> None: ...


class ThreadPoolEmbeddingDispatcher:
    """Pool próprio: gerar vetores é lento e não pode atrasar o processamento de documentos."""

    def __init__(self, runner: EmbeddingRunner, workers: int) -> None:
        self._runner = runner
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="embed-worker")

    def submit(self, document_id: uuid.UUID) -> None:
        self._pool.submit(self._run, document_id)

    def _run(self, document_id: uuid.UUID) -> None:
        try:
            self._runner.run(document_id)
        except Exception:  # noqa: BLE001 - uma tarefa nunca derruba o pool
            logger.exception("Erro inesperado ao gerar embeddings do documento %s", document_id)

    def shutdown(self) -> None:
        # Tarefas em curso ou na fila somem; o que faltar é retomado na próxima inicialização.
        self._pool.shutdown(wait=False, cancel_futures=True)


def recover_pending_embeddings(
    session_factory: Callable[[], Session], dispatcher: EmbeddingDispatcher, model: str
) -> int:
    """Envia ao despachante os documentos concluídos que ainda têm trechos sem vetor."""
    with session_factory() as db:
        ids = documents_pending_embedding(db, model)
    for document_id in ids:
        dispatcher.submit(document_id)
    return len(ids)


__all__ = [
    "EmbedResult",
    "EmbeddingRunner",
    "ThreadPoolEmbeddingDispatcher",
    "documents_pending_embedding",
    "embed_document",
    "recover_pending_embeddings",
    "restore_embeddings",
    "snapshot_embeddings",
]
