"""Comandos de manutenção. Uso (de `backend/`, com o venv ativo):

    python -m app.cli rebuild-chunks --missing-only     # só documentos sem chunks
    python -m app.cli rebuild-chunks --document-id UUID # um documento
    python -m app.cli rebuild-chunks --all              # todos os documentos concluídos
    python -m app.cli process-pending                   # processa documentos `pending` (fila perdida)
    python -m app.cli process-pending --include-processing  # com a API PARADA: retoma também `processing`
    python -m app.cli embed-pending                     # gera os embeddings que faltam (exige EMBEDDINGS_ENABLED=true)
    python -m app.cli embed-pending --document-id UUID  # só um documento
    python -m app.cli download-embedding-model          # MANUAL: baixa o modelo local (revisão fixa, SHA-256 verificado)
    python -m app.cli download-embedding-model --from-dir DIR  # instala de uma cópia local, sem baixar nada

É idempotente: repetir o comando não duplica chunks.
"""

import argparse
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.document import Document, DocumentStatus
from app.services import documents as documents_service
from app.services.embedding_model import ModelFileError, install_model
from app.services.embedding_tasks import documents_pending_embedding, embed_document
from app.services.embeddings import EmbeddingConfigError, EmbeddingProvider, build_provider
from app.services.processing import DocumentProcessor, InlineDispatcher, recover_interrupted


def rebuild_chunks(db: Session, settings: Settings, *, document_id: uuid.UUID | None, missing_only: bool) -> tuple[int, int, int]:
    """Devolve (documentos processados, chunks gerados, falhas)."""
    if document_id is not None:
        ids = [document_id]
    elif missing_only:
        ids = documents_service.documents_without_chunks(db)
    else:
        ids = list(
            db.scalars(
                select(Document.id)
                .where(Document.status == DocumentStatus.COMPLETED.value)
                .order_by(Document.created_at)
            )
        )
    processed = chunks = failures = 0
    for item in ids:
        try:
            chunks += documents_service.rebuild_chunks(db, settings, item)
            processed += 1
        except Exception as exc:  # noqa: BLE001 - segue para o próximo documento
            failures += 1
            print(f"  falha em {item}: {type(exc).__name__}", file=sys.stderr)
    return processed, chunks, failures


def embed_pending(
    db: Session,
    provider: EmbeddingProvider,
    settings: Settings,
    *,
    document_id: uuid.UUID | None,
    sleep: Callable[[float], None],
) -> tuple[int, int, int, int]:
    """Devolve (documentos tratados, vetores gerados, trechos reaproveitados, falhas)."""
    ids = [document_id] if document_id is not None else documents_pending_embedding(db, provider.model)
    db.rollback()
    handled = generated = reused = failures = 0
    for item in ids:
        result = embed_document(db, provider, settings, item, sleep=sleep)
        if result.status == "failed":
            failures += 1
            print(f"  falha em {item}: {result.error} ({result.remaining} trecho(s) sem vetor)", file=sys.stderr)
        elif result.status in {"skipped", "deleted", "busy"}:
            print(f"  {item}: {result.status}", file=sys.stderr)
            continue
        handled += 1
        generated += result.generated
        reused += result.reused
    return handled, generated, reused, failures


def main(
    argv: Sequence[str] | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
    settings: Settings | None = None,
    provider_factory: Callable[[Settings], EmbeddingProvider | None] = build_provider,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rebuild = sub.add_parser("rebuild-chunks", help="Gera de novo os chunks a partir do texto das páginas.")
    target = rebuild.add_mutually_exclusive_group(required=True)
    target.add_argument("--missing-only", action="store_true", help="Apenas documentos concluídos sem chunks.")
    target.add_argument("--all", action="store_true", help="Todos os documentos concluídos.")
    target.add_argument("--document-id", type=uuid.UUID, help="Um documento específico.")
    pending = sub.add_parser("process-pending", help="Processa agora os documentos que ficaram pending.")
    pending.add_argument(
        "--include-processing",
        action="store_true",
        help="Também devolve `processing` para `pending`. Use só com a API parada.",
    )
    embedding = sub.add_parser("embed-pending", help="Gera agora os embeddings dos trechos que ainda não têm vetor.")
    embedding.add_argument("--document-id", type=uuid.UUID, help="Apenas este documento.")
    download = sub.add_parser(
        "download-embedding-model",
        help="Instala o modelo local de embeddings (nunca roda sozinho; só o modelo é baixado, nenhum texto sai).",
    )
    download.add_argument("--from-dir", type=Path, help="Copia de um diretório local em vez de baixar.")
    download.add_argument("--dest", type=Path, help="Destino (padrão: EMBEDDING_MODEL_PATH).")
    args = parser.parse_args(argv)

    if args.command == "process-pending":
        processor = DocumentProcessor(session_factory, settings_factory=lambda: settings or get_settings())
        count = recover_interrupted(session_factory, InlineDispatcher(processor), include_processing=args.include_processing)
        print(f"{count} documento(s) enviado(s) ao processamento.")
        return 0

    if args.command == "download-embedding-model":
        destination = (args.dest or Path((settings or get_settings()).embedding_model_path)).expanduser().resolve()
        try:
            install_model(destination, source_dir=args.from_dir, log=print)
        except (ModelFileError, OSError) as exc:
            print(f"Falha ao instalar o modelo: {exc}", file=sys.stderr)
            return 1
        print(f"Modelo instalado e verificado em {destination}")
        return 0

    if args.command == "embed-pending":
        config = settings or get_settings()
        try:
            provider = provider_factory(config)
        except EmbeddingConfigError as exc:
            print(f"Embeddings indisponíveis: {exc}", file=sys.stderr)
            return 2
        if provider is None:
            print("Embeddings desligados. Defina EMBEDDINGS_ENABLED=true para gerar vetores.", file=sys.stderr)
            return 2
        with session_factory() as db:
            handled, generated, reused, failures = embed_pending(
                db, provider, config, document_id=args.document_id, sleep=sleep
            )
        print(
            f"{handled} documento(s) tratado(s), {generated} vetor(es) gerado(s), "
            f"{reused} trecho(s) reaproveitado(s), {failures} falha(s)."
        )
        return 1 if failures else 0

    with session_factory() as db:
        processed, chunks, failures = rebuild_chunks(
            db, settings or get_settings(), document_id=args.document_id, missing_only=args.missing_only
        )
    print(f"{processed} documento(s) processado(s), {chunks} chunk(s) gerado(s), {failures} falha(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
