"""Processamento de documentos em segundo plano: extração de texto e geração de chunks.

Modelo
------
* O **banco é a fonte da verdade**. O estado do documento (`pending` -> `processing` ->
  `completed`/`failed`) e o PDF original em disco são duráveis; o pool de threads é só
  quem executa. Perder o pool (reinício do processo) não perde dados: os documentos
  ficam `pending`/`processing` e são retomados por `recover_interrupted`.
* **Uma execução por documento**: a passagem `pending -> processing` é um UPDATE
  condicional (compare-and-set). Quem não vencer a disputa não faz nada.
* **Cada tarefa abre a própria sessão** do banco; nenhuma sessão atravessa threads.
* **Troca atômica**: a extração e a segmentação acontecem fora de qualquer transação.
  Só depois, numa única transação, os dados antigos (se houver) são substituídos pelos
  novos e o documento vira `completed`. Qualquer erro => rollback e `failed`, com os
  dados anteriores intactos.

Limitação importante: o pool em memória NÃO é uma fila durável. Tarefas enfileiradas e
não executadas somem se o processo cair; elas voltam a ser enfileiradas na próxima
inicialização (ou por `python -m app.cli process-pending`), nunca antes.
"""

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import SessionLocal
from app.models.document import Document, DocumentChunk, DocumentPage, DocumentStatus
from app.services import chunker, pdf, search
from app.services import documents as documents_service
from app.services.storage import LocalStorage, get_storage

logger = logging.getLogger("second_brain.processing")

COMPLETED, SKIPPED, DELETED, FAILED = "completed", "skipped", "deleted", "failed"


class OriginalFileMissing(Exception):
    """O PDF original não está no armazenamento."""


# --- um documento ---------------------------------------------------------------
def claim(db: Session, document_id: uuid.UUID) -> bool:
    """`pending` -> `processing`, de forma atômica. False se outro já assumiu (ou o documento sumiu)."""
    moved = db.execute(
        update(Document)
        .where(Document.id == document_id, Document.status == DocumentStatus.PENDING.value)
        .values(status=DocumentStatus.PROCESSING.value, updated_at=func.now())
    ).rowcount
    db.commit()
    return moved == 1


def process_document(db: Session, storage: LocalStorage, settings: Settings, document_id: uuid.UUID) -> str:
    """Executa uma tentativa de processamento. Devolve o resultado (`completed`, `failed`, `skipped`, `deleted`)."""
    if not claim(db, document_id):
        return SKIPPED  # já em andamento, já concluído ou excluído: nada a fazer

    row = db.execute(
        select(Document.storage_key, exists().where(DocumentPage.document_id == Document.id))
        .where(Document.id == document_id)
    ).first()
    if row is None:
        return DELETED
    storage_key, had_previous = row
    db.rollback()  # nenhuma transação aberta durante a parte lenta

    step = "ler o arquivo original"
    try:
        path = storage.path_for(storage_key)
        if not path.is_file():
            raise OriginalFileMissing()
        step = "abrir o PDF"
        reader = pdf.open_pdf(path, settings.max_document_pages)
        page_count = len(reader.pages)
        step = "extrair o texto do PDF"
        texts = pdf.extract_text(reader)
        step = "dividir o texto em trechos"
        specs = chunker.chunk_pages(list(enumerate(texts, start=1)), documents_service.chunking_config(settings))
    except Exception as exc:  # noqa: BLE001 - qualquer falha vira `failed`; o PDF original nunca é tocado
        return _fail(db, document_id, step, exc, had_previous)

    try:
        return _store_result(db, document_id, page_count, texts, specs)
    except Exception as exc:  # noqa: BLE001
        db.rollback()  # desfaz a troca inteira: os dados anteriores continuam valendo
        return _fail(db, document_id, "gravar o resultado", exc, had_previous)


def _store_result(
    db: Session,
    document_id: uuid.UUID,
    page_count: int,
    texts: list[str],
    specs: list[chunker.ChunkSpec],
) -> str:
    """Substitui páginas e trechos e marca `completed`, tudo na mesma transação."""
    document = db.get(Document, document_id)
    if document is None:  # excluído durante o processamento
        return DELETED
    # Trechos antes das páginas: a FK dos trechos aponta para as páginas.
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
    db.add_all(DocumentPage(document_id=document_id, page_number=i, text=t) for i, t in enumerate(texts, start=1))
    db.flush()  # páginas existem antes dos trechos
    db.add_all(documents_service._chunk_rows(document_id, specs))
    document.page_count = page_count
    document.has_text = any(texts)
    document.error_message = None
    document.status = DocumentStatus.COMPLETED.value  # só aqui: páginas e trechos já estão na transação
    document.updated_at = func.now()
    db.flush()
    search.refresh_documents(db, [document_id])
    db.commit()
    return COMPLETED


def _error_message(step: str, exc: Exception, had_previous: bool) -> str:
    if isinstance(exc, OriginalFileMissing):
        text = "O arquivo original não foi encontrado no armazenamento."
    elif isinstance(exc, AppError):
        text = exc.detail  # mensagens de domínio já são seguras para o usuário
    else:
        text = f"Não foi possível {step} ({type(exc).__name__})."  # sem detalhes internos
    return f"{text} A versão anterior foi mantida." if had_previous else text


def _fail(db: Session, document_id: uuid.UUID, step: str, exc: Exception, had_previous: bool) -> str:
    logger.warning("Processamento do documento %s falhou ao %s (%s)", document_id, step, type(exc).__name__)
    message = _error_message(step, exc, had_previous)
    try:
        db.rollback()
        db.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == DocumentStatus.PROCESSING.value)
            .values(status=DocumentStatus.FAILED.value, error_message=message, updated_at=func.now())
        )
        db.commit()
    except Exception:  # noqa: BLE001
        # Sem conseguir registrar a falha o documento fica `processing` e será retomado na próxima inicialização.
        db.rollback()
        logger.exception("Não foi possível registrar a falha do documento %s", document_id)
    return FAILED


# --- execução ----------------------------------------------------------------------
class DocumentProcessor:
    """Processa um documento por chamada, com sessão própria (nunca compartilhada)."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        storage_factory: Callable[[], LocalStorage] = get_storage,
        settings_factory: Callable[[], Settings] = get_settings,
    ) -> None:
        self._session_factory = session_factory
        self._storage_factory = storage_factory
        self._settings_factory = settings_factory

    def process(self, document_id: uuid.UUID) -> str:
        with self._session_factory() as db:
            return process_document(db, self._storage_factory(), self._settings_factory(), document_id)


class Dispatcher(Protocol):
    def submit(self, document_id: uuid.UUID) -> None: ...


class ThreadPoolDispatcher:
    """Executa em um pool de threads limitado. Documentos diferentes rodam em paralelo."""

    def __init__(self, processor: DocumentProcessor, workers: int) -> None:
        self._processor = processor
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="doc-worker")

    def submit(self, document_id: uuid.UUID) -> None:
        self._pool.submit(self._run, document_id)

    def _run(self, document_id: uuid.UUID) -> None:
        try:
            self._processor.process(document_id)
        except Exception:  # noqa: BLE001 - uma tarefa nunca derruba o pool
            logger.exception("Erro inesperado ao processar o documento %s", document_id)

    def shutdown(self) -> None:
        # Não espera tarefas em curso: elas ficam `processing` e são retomadas na próxima inicialização.
        self._pool.shutdown(wait=False, cancel_futures=True)


class InlineDispatcher:
    """Executa na hora, na thread de quem chama (CLI e testes)."""

    def __init__(self, processor: DocumentProcessor) -> None:
        self._processor = processor

    def submit(self, document_id: uuid.UUID) -> None:
        try:
            self._processor.process(document_id)
        except Exception:  # noqa: BLE001
            logger.exception("Erro inesperado ao processar o documento %s", document_id)


# --- retomada ---------------------------------------------------------------------------
def recover_interrupted(
    session_factory: Callable[[], Session], dispatcher: Dispatcher, *, include_processing: bool = True
) -> int:
    """Reenfileira o que ficou para trás (reinício, queda). Devolve quantos documentos foram enviados.

    `processing` volta para `pending` porque, num processo recém-iniciado, nenhuma tarefa
    própria está rodando. Com vários processos da API isso derrubaria o trabalho dos outros:
    por isso o pressuposto de processo único (ver README).
    """
    with session_factory() as db:
        if include_processing:
            db.execute(
                update(Document)
                .where(Document.status == DocumentStatus.PROCESSING.value)
                .values(status=DocumentStatus.PENDING.value, updated_at=func.now())
            )
            db.commit()
        ids = list(
            db.scalars(
                select(Document.id).where(Document.status == DocumentStatus.PENDING.value).order_by(Document.created_at)
            )
        )
    for document_id in ids:
        dispatcher.submit(document_id)
    return len(ids)
