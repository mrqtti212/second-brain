import logging
from pathlib import Path
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.spa import SPAStaticFiles
from app.db.session import SessionLocal
from app.services.embedding_tasks import EmbeddingRunner, ThreadPoolEmbeddingDispatcher, recover_pending_embeddings
from app.services.embeddings import EmbeddingConfigError, build_provider
from app.services.processing import DocumentProcessor, ThreadPoolDispatcher, recover_interrupted

logger = logging.getLogger("second_brain")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cria os pools de processamento de documentos e de embeddings e retoma o que ficou para trás."""
    settings = get_settings()
    dispatcher = None
    embedding_dispatcher = None
    app.state.embedding_dispatcher = None
    if settings.embeddings_enabled:
        try:
            provider = build_provider(settings)
        except EmbeddingConfigError as exc:  # configuração inválida não impede a API de subir
            provider = None
            logger.error("Embeddings desativados nesta execução: %s", exc)
        if provider is not None:
            embedding_dispatcher = ThreadPoolEmbeddingDispatcher(
                EmbeddingRunner(SessionLocal, provider), settings.embedding_workers
            )
            app.state.embedding_dispatcher = embedding_dispatcher
            if settings.recover_on_startup:
                try:
                    pending = recover_pending_embeddings(SessionLocal, embedding_dispatcher, provider.model)
                    if pending:
                        logger.info("%d documento(s) com embeddings pendentes enviado(s) à geração", pending)
                except Exception:  # noqa: BLE001 - banco indisponível não impede a API de subir
                    logger.exception("Não foi possível retomar embeddings pendentes")
    if settings.document_processing_enabled:
        # Ao concluir um documento, os embeddings dos trechos novos são gerados em outro pool.
        processor = DocumentProcessor(
            SessionLocal, on_completed=embedding_dispatcher.submit if embedding_dispatcher else None
        )
        dispatcher = ThreadPoolDispatcher(processor, settings.document_workers)
        app.state.dispatcher = dispatcher
        if settings.recover_on_startup:
            try:
                resumed = recover_interrupted(SessionLocal, dispatcher)
                if resumed:
                    logger.info("%d documento(s) pendente(s) reenfileirado(s)", resumed)
            except Exception:  # noqa: BLE001 - banco indisponível não impede a API de subir
                logger.exception("Não foi possível retomar documentos pendentes")
    yield
    if dispatcher is not None:
        dispatcher.shutdown()
    if embedding_dispatcher is not None:
        embedding_dispatcher.shutdown()
        app.state.embedding_dispatcher = None


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    upload_path = f"{settings.api_prefix}/documents"

    @app.middleware("http")
    async def reject_oversized_upload(request: Request, call_next):
        # Recusa pelo Content-Length antes de o corpo ser lido. A validação exata
        # (inclusive sem Content-Length) é feita em services/storage.py.
        if request.method == "POST" and request.url.path == upload_path:
            declared = request.headers.get("content-length", "")
            limit = get_settings().max_upload_bytes + 1024 * 1024  # folga para o envelope multipart
            if declared.isdigit() and int(declared) > limit:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"O arquivo excede o limite de {get_settings().max_upload_mb} MB."},
                )
        return await call_next(request)

    @app.exception_handler(AppError)
    async def domain_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, **exc.extra})

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Erro não tratado em %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Erro interno do servidor."})

    app.include_router(api_router, prefix=settings.api_prefix)

    # Montado por último: as rotas da API e da documentação têm prioridade sobre o frontend.
    if settings.frontend_dist_path.strip():
        dist = Path(settings.frontend_dist_path).expanduser().resolve()
        if (dist / "index.html").is_file():
            app.mount("/", SPAStaticFiles(directory=dist, reserved_prefixes=(settings.api_prefix,)), name="frontend")
        else:
            logger.warning("FRONTEND_DIST_PATH=%s não tem index.html; o frontend não será servido (rode npm run build).", dist)
    return app


app = create_app()
