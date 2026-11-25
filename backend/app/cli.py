"""Comandos de manutenção. Uso (de `backend/`, com o venv ativo):

    python -m app.cli rebuild-chunks --missing-only     # só documentos sem chunks
    python -m app.cli rebuild-chunks --document-id UUID # um documento
    python -m app.cli rebuild-chunks --all              # todos os documentos concluídos
    python -m app.cli process-pending                   # processa documentos `pending` (fila perdida)
    python -m app.cli process-pending --include-processing  # com a API PARADA: retoma também `processing`

É idempotente: repetir o comando não duplica chunks.
"""

import argparse
import sys
import uuid
from collections.abc import Callable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.document import Document, DocumentStatus
from app.services import documents as documents_service
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


def main(
    argv: Sequence[str] | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
    settings: Settings | None = None,
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
    args = parser.parse_args(argv)

    if args.command == "process-pending":
        processor = DocumentProcessor(session_factory, settings_factory=lambda: settings or get_settings())
        count = recover_interrupted(session_factory, InlineDispatcher(processor), include_processing=args.include_processing)
        print(f"{count} documento(s) enviado(s) ao processamento.")
        return 0

    with session_factory() as db:
        processed, chunks, failures = rebuild_chunks(
            db, settings or get_settings(), document_id=args.document_id, missing_only=args.missing_only
        )
    print(f"{processed} documento(s) processado(s), {chunks} chunk(s) gerado(s), {failures} falha(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
