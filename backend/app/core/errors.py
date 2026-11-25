"""Erros de domínio mapeados para respostas HTTP em main.py."""


class AppError(Exception):
    status_code = 500
    detail = "Erro interno do servidor."

    def __init__(self, detail: str | None = None, **extra: object) -> None:
        super().__init__(detail or self.detail)
        self.detail = detail or self.detail
        # Campos estruturados adicionais da resposta (ex.: `code`, `existing_document`).
        self.extra = extra


class NotFoundError(AppError):
    status_code = 404
    detail = "Recurso não encontrado."


class ConflictError(AppError):
    status_code = 409
    detail = "Conflito com um recurso existente."


class InvalidReferenceError(AppError):
    """O corpo da requisição referencia um recurso que não existe."""

    status_code = 422
    detail = "Referência inválida."


class SearchUnavailableError(AppError):
    status_code = 503
    detail = "A busca textual requer PostgreSQL."


class UnsupportedMediaError(AppError):
    """Extensão ou Content-Type não aceitos."""

    status_code = 415
    detail = "Formato de arquivo não suportado. Envie um PDF."


class InvalidFileError(AppError):
    """O conteúdo do arquivo não é um PDF utilizável."""

    status_code = 422
    detail = "O arquivo não é um PDF válido."


class PayloadTooLargeError(AppError):
    status_code = 413
    detail = "O arquivo excede o tamanho máximo permitido."


class StorageError(AppError):
    """Falha de armazenamento. A mensagem nunca inclui caminhos do sistema."""

    status_code = 500
    detail = "Falha ao acessar o armazenamento de arquivos."


class DuplicateDocumentError(ConflictError):
    """O mesmo conteúdo binário (SHA-256) já foi importado."""

    detail = "Este arquivo já foi importado."

    def __init__(self, existing: dict[str, object]) -> None:
        super().__init__(code="duplicate_document", existing_document=existing)


class ProcessingInProgressError(ConflictError):
    """O documento já está na fila ou sendo processado: não inicia uma segunda execução."""

    detail = "O documento já está aguardando ou em processamento."

    def __init__(self, status: str) -> None:
        super().__init__(code="already_processing", status=status)


class OriginalFileMissingError(ConflictError):
    """O registro existe, mas o PDF original não está no armazenamento."""

    detail = "O arquivo original deste documento não foi encontrado no armazenamento; não é possível reprocessar."

    def __init__(self) -> None:
        super().__init__(code="original_file_missing")
