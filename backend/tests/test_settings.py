"""Leitura da configuração a partir do ambiente e de arquivos .env."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ["http://localhost:5173", "http://127.0.0.1:5173"]


def from_env_file(tmp_path, line: str) -> Settings:
    env_file = tmp_path / ".env"
    env_file.write_text(line + "\n", encoding="utf-8")
    return Settings(_env_file=env_file)


def test_cors_origins_accepts_a_comma_separated_list_from_a_dotenv_file(tmp_path):
    assert from_env_file(tmp_path, "CORS_ORIGINS=http://a.test:1, http://b.test:2").cors_origins == [
        "http://a.test:1", "http://b.test:2"]


def test_cors_origins_accepts_json_and_a_single_value(tmp_path, monkeypatch):
    assert from_env_file(tmp_path, 'CORS_ORIGINS=["http://a.test","http://b.test"]').cors_origins == [
        "http://a.test", "http://b.test"]
    assert from_env_file(tmp_path, "CORS_ORIGINS=http://unica.test").cors_origins == ["http://unica.test"]
    monkeypatch.setenv("CORS_ORIGINS", "http://x.test,http://y.test")  # variável de ambiente, sem arquivo
    assert Settings(_env_file=None).cors_origins == ["http://x.test", "http://y.test"]


def test_cors_origins_empty_value_gives_an_empty_list_and_invalid_json_is_rejected(tmp_path):
    assert from_env_file(tmp_path, "CORS_ORIGINS=").cors_origins == []
    with pytest.raises(ValueError):
        from_env_file(tmp_path, "CORS_ORIGINS=[http://sem-aspas")


def test_cors_origins_default_is_unchanged():
    assert Settings(_env_file=None).cors_origins == LOCAL


def test_the_whole_env_example_loads_without_errors():
    config = Settings(_env_file=ROOT / ".env.example")
    assert config.cors_origins == LOCAL
    assert config.embeddings_enabled is False and config.embedding_dimensions == 384
    assert config.document_workers == 2 and config.chunk_max_chars == 1200
