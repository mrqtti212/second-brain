from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dimensão da coluna `chunk_embeddings.embedding` (migration 0007). É fixa no esquema:
# trocar de modelo para outra dimensão exige uma migration nova e regerar os vetores.
EMBEDDING_SCHEMA_DIMENSIONS = 384


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

    # Embeddings dos trechos. Desligados por padrão: nada é gerado nem consultado.
    # Sem API externa e sem credenciais; `local` roda o modelo em CPU a partir de arquivos locais.
    embeddings_enabled: bool = False
    embedding_provider: Literal["local", "fake"] = "local"
    embedding_model: str = Field(default="intfloat/multilingual-e5-small", min_length=1, max_length=100)
    embedding_dimensions: int = Field(default=EMBEDDING_SCHEMA_DIMENSIONS, ge=1, le=2000)
    embedding_batch_size: int = Field(default=16, ge=1, le=256)
    # Geração em segundo plano: tarefas simultâneas (um modelo em CPU já usa vários núcleos),
    # tentativas por lote e espera inicial entre tentativas (dobra a cada nova tentativa).
    # Provedor local: onde ficam os arquivos do modelo (relativo ao diretório de execução) e quantas
    # threads o onnxruntime usa em CPU (0 = automático, até 4).
    embedding_model_path: str = "models/multilingual-e5-small"
    embedding_threads: int = Field(default=0, ge=0, le=64)
    embedding_workers: int = Field(default=1, ge=1, le=8)
    embedding_max_attempts: int = Field(default=3, ge=1, le=10)
    embedding_retry_backoff_seconds: float = Field(default=1.0, ge=0, le=60)

    @model_validator(mode="after")
    def _check_chunking(self) -> "Settings":
        if self.chunk_overlap_chars >= self.chunk_max_chars:
            raise ValueError("CHUNK_OVERLAP_CHARS deve ser menor que CHUNK_MAX_CHARS.")
        if self.chunk_min_chars > self.chunk_max_chars:
            raise ValueError("CHUNK_MIN_CHARS não pode ser maior que CHUNK_MAX_CHARS.")
        return self

    @model_validator(mode="after")
    def _check_embeddings(self) -> "Settings":
        # Só vale quando ligado: uma variável esquecida no .env não impede a API de subir.
        if self.embeddings_enabled and self.embedding_dimensions != EMBEDDING_SCHEMA_DIMENSIONS:
            raise ValueError(
                f"EMBEDDING_DIMENSIONS deve ser {EMBEDDING_SCHEMA_DIMENSIONS}, a dimensão da coluna "
                "no banco. Outra dimensão exige uma migration nova."
            )
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
