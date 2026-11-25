from fastapi import Request

from app.core.errors import AppError
from app.services.processing import Dispatcher


class ProcessingDisabledError(AppError):
    status_code = 503
    detail = "O processamento de documentos está desativado neste servidor."


def get_dispatcher(request: Request) -> Dispatcher:
    """Despachante do processamento em segundo plano (criado na inicialização da aplicação)."""
    dispatcher = getattr(request.app.state, "dispatcher", None)
    if dispatcher is None:
        raise ProcessingDisabledError()
    return dispatcher
