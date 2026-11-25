from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Lê o .env da raiz do projeto ou do diretório backend, se existir.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Second Brain API"
    app_env: str = "development"
    api_prefix: str = "/api"
    database_url: str = (
        "postgresql+psycopg://secondbrain:change-me-locally@localhost:5432/secondbrain"
    )
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Documentos (PDF). O caminho relativo é resolvido a partir do diretório de execução.
    document_storage_path: str = "storage/documents"
    max_upload_mb: int = Field(default=20, ge=1, le=500)
    max_document_pages: int = Field(default=500, ge=1, le=5000)

    # Processamento de documentos em segundo plano (pool de threads no próprio processo).
    document_processing_enabled: bool = True
    document_workers: int = Field(default=2, ge=1, le=16)
    # Ao iniciar, reenfileira documentos `pending` e devolve `processing` para `pending`.
    # Pressupõe um único processo da API (ver README).
    recover_on_startup: bool = True

    # Segmentação do texto em trechos (chunks). Valores em caracteres.
    chunk_max_chars: int = Field(default=1200, ge=100, le=20000)
    chunk_overlap_chars: int = Field(default=200, ge=0, le=10000)
    chunk_min_chars: int = Field(default=50, ge=1, le=5000)

    @model_validator(mode="after")
    def _check_chunking(self) -> "Settings":
        if self.chunk_overlap_chars >= self.chunk_max_chars:
            raise ValueError("CHUNK_OVERLAP_CHARS deve ser menor que CHUNK_MAX_CHARS.")
        if self.chunk_min_chars > self.chunk_max_chars:
            raise ValueError("CHUNK_MIN_CHARS não pode ser maior que CHUNK_MAX_CHARS.")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
