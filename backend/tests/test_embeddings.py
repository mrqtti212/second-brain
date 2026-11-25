"""Etapa A dos embeddings: contrato do provedor, configuração e tabela `chunk_embeddings`.

Sem rede, sem modelo e sem credenciais. Os testes marcados com `requires_postgres` usam o tipo
`vector`, o índice HNSW e a migration 0007 e exigem TEST_DATABASE_URL (PostgreSQL com pgvector).
"""

import logging
import math
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import EMBEDDING_SCHEMA_DIMENSIONS, Settings
from app.db.base import Base
from app.models import ChunkEmbedding, Document, DocumentChunk, DocumentPage
from app.services.embeddings import (
    EmbeddingConfigError,
    EmbeddingError,
    EmbeddingProvider,
    FakeEmbeddingProvider,
    build_provider,
    text_sha256,
    validate_vectors,
)
from tests.conftest import TEST_DATABASE_URL, requires_postgres

DIMS = EMBEDDING_SCHEMA_DIMENSIONS


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # os vetores já têm norma 1


# --- provedor falso ------------------------------------------------------------
def test_fake_provider_follows_the_contract():
    provider = FakeEmbeddingProvider()
    assert isinstance(provider, EmbeddingProvider)
    assert provider.dimensions == DIMS == 384
    vectors = provider.embed_passages(["primeiro texto", "segundo texto"])
    assert len(vectors) == 2 and all(len(v) == DIMS for v in vectors)
    validate_vectors(provider, ["primeiro texto", "segundo texto"], vectors)
    assert provider.embed_passages([]) == []


def test_fake_provider_is_deterministic_and_normalized():
    a, b = FakeEmbeddingProvider(), FakeEmbeddingProvider()
    text_ = "Contrato de locação residencial com prazo de 30 meses."
    assert a.embed_passages([text_]) == b.embed_passages([text_])
    assert a.embed_query(text_) == a.embed_passages([text_])[0]
    assert math.isclose(math.sqrt(sum(x * x for x in a.embed_query(text_))), 1.0, rel_tol=1e-9)
    assert a.embed_query("LOCAÇÃO residencial") == a.embed_query("locação RESIDENCIAL")  # ignora maiúsculas


def test_fake_provider_puts_similar_texts_closer_than_unrelated_ones():
    provider = FakeEmbeddingProvider()
    base = provider.embed_query("prazo do contrato de locação residencial")
    similar = provider.embed_query("contrato de locação com prazo de trinta meses")
    unrelated = provider.embed_query("receita de bolo de cenoura com cobertura de chocolate")
    assert cosine(base, similar) > 0.3 > abs(cosine(base, unrelated))


def test_fake_provider_handles_text_without_words():
    provider = FakeEmbeddingProvider()
    vector = provider.embed_query("!!! ???")
    assert len(vector) == DIMS and math.isclose(sum(x * x for x in vector), 1.0, rel_tol=1e-9)
    assert provider.embed_query("!!! ???") == vector


def test_fake_provider_counts_calls_for_later_stages():
    provider = FakeEmbeddingProvider()
    provider.embed_passages(["a", "b", "c"])
    provider.embed_passages(["d"])
    provider.embed_query("q")
    assert (provider.passage_calls, provider.passage_texts, provider.query_calls) == (2, 4, 1)


def test_text_sha256_is_the_hex_digest_of_the_utf8_text():
    assert text_sha256("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert len(text_sha256("ação")) == 64 and text_sha256("ação") != text_sha256("acao")


# --- validação do que o provedor devolve ---------------------------------------
def test_validate_vectors_rejects_wrong_count_dimension_and_non_finite_values():
    provider = FakeEmbeddingProvider(dimensions=4)
    good = [0.5, 0.5, 0.5, 0.5]
    validate_vectors(provider, ["a"], [good])
    with pytest.raises(EmbeddingError, match="2 vetores para 1 textos"):
        validate_vectors(provider, ["a"], [good, good])
    with pytest.raises(EmbeddingError, match="3 dimensões"):
        validate_vectors(provider, ["a"], [[1.0, 0.0, 0.0]])
    with pytest.raises(EmbeddingError, match="não finitos"):
        validate_vectors(provider, ["a"], [[1.0, float("nan"), 0.0, 0.0]])
    with pytest.raises(EmbeddingError, match="não finitos"):
        validate_vectors(provider, ["a"], [[1.0, float("inf"), 0.0, 0.0]])


def test_validation_errors_never_contain_the_document_text():
    provider = FakeEmbeddingProvider(dimensions=4)
    secret = "CPF 123.456.789-00 da cliente"
    with pytest.raises(EmbeddingError) as raised:
        validate_vectors(provider, [secret], [[1.0, 0.0]])
    assert "123.456" not in str(raised.value) and "CPF" not in str(raised.value)


def test_fake_provider_rejects_a_degenerate_dimension():
    with pytest.raises(ValueError):
        FakeEmbeddingProvider(dimensions=1)


# --- configuração --------------------------------------------------------------
def settings(**env) -> Settings:
    return Settings(_env_file=None, **env)  # ignora qualquer .env da máquina


def test_embeddings_are_disabled_by_default():
    config = settings()
    assert config.embeddings_enabled is False
    assert config.embedding_provider == "local"
    assert config.embedding_model == "intfloat/multilingual-e5-small"
    assert config.embedding_dimensions == 384 and config.embedding_batch_size == 16
    assert build_provider(config) is None


def test_settings_read_the_documented_environment_variables(monkeypatch):
    for name, value in {
        "EMBEDDINGS_ENABLED": "true",
        "EMBEDDING_PROVIDER": "fake",
        "EMBEDDING_MODEL": "outro-modelo",
        "EMBEDDING_BATCH_SIZE": "8",
    }.items():
        monkeypatch.setenv(name, value)
    config = Settings(_env_file=None)
    assert config.embeddings_enabled and config.embedding_provider == "fake"
    assert config.embedding_model == "outro-modelo" and config.embedding_batch_size == 8


def test_enabled_with_the_fake_provider_builds_it():
    provider = build_provider(settings(embeddings_enabled=True, embedding_provider="fake"))
    assert isinstance(provider, FakeEmbeddingProvider) and provider.dimensions == 384


def test_enabled_with_the_local_provider_fails_clearly_when_the_model_files_are_missing(tmp_path):
    missing = settings(embeddings_enabled=True, embedding_provider="local", embedding_model_path=str(tmp_path / "nada"))
    with pytest.raises(EmbeddingConfigError, match="Arquivo do modelo ausente"):
        build_provider(missing)


def test_dimensions_must_match_the_schema_only_when_enabled():
    with pytest.raises(ValidationError, match="EMBEDDING_DIMENSIONS deve ser 384"):
        settings(embeddings_enabled=True, embedding_provider="fake", embedding_dimensions=1536)
    assert settings(embedding_dimensions=1536).embedding_dimensions == 1536  # desligado: não bloqueia a API
    with pytest.raises(ValidationError):
        settings(embedding_dimensions=3072)  # acima do limite de 2000 do índice HNSW
    with pytest.raises(ValidationError):
        settings(embedding_provider="openai")  # sem API externa nesta etapa


# --- modelo e tabela (SQLite e PostgreSQL) -------------------------------------
def make_chunk(db, content: str = "Texto de um trecho com conteúdo suficiente.") -> DocumentChunk:
    document = Document(
        title="Documento", original_filename="d.pdf", storage_key=f"{uuid.uuid4()}.pdf", size_bytes=10,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex, status="completed", has_text=True,
    )
    db.add(document)
    db.flush()
    db.add(DocumentPage(document_id=document.id, page_number=1, text=content))
    db.flush()
    chunk = DocumentChunk(
        document_id=document.id, page_number=1, chunk_index=0, content=content,
        character_count=len(content), start_offset=0, end_offset=len(content),
    )
    db.add(chunk)
    db.flush()
    return chunk


def embed(db, chunk: DocumentChunk, provider: FakeEmbeddingProvider | None = None) -> ChunkEmbedding:
    provider = provider or FakeEmbeddingProvider()
    row = ChunkEmbedding(
        chunk_id=chunk.id, model=provider.model, dimensions=provider.dimensions,
        content_sha256=text_sha256(chunk.content), embedding=provider.embed_passages([chunk.content])[0],
    )
    db.add(row)
    db.flush()
    return row


def test_embedding_round_trips_with_model_dimensions_and_hash(db):
    chunk = make_chunk(db)
    original = embed(db, chunk)
    db.commit()
    db.expire_all()
    stored = db.get(ChunkEmbedding, chunk.id)
    assert stored.model == "fake-hash-v1" and stored.dimensions == 384
    assert stored.content_sha256 == text_sha256(chunk.content)
    assert len(stored.embedding) == 384
    assert stored.embedding == pytest.approx(original.embedding, abs=1e-5)  # PostgreSQL guarda float4
    assert stored.created_at is not None


def test_one_embedding_per_chunk(db):
    chunk = make_chunk(db)
    embed(db, chunk)
    db.commit()
    with pytest.raises(IntegrityError):
        embed(db, chunk)
    db.rollback()


def test_content_hash_must_have_64_characters(db):
    chunk = make_chunk(db)
    db.add(ChunkEmbedding(chunk_id=chunk.id, model="m", dimensions=384, content_sha256="abc",
                          embedding=FakeEmbeddingProvider().embed_query("x")))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_embedding_requires_an_existing_chunk(db):
    db.add(ChunkEmbedding(chunk_id=uuid.uuid4(), model="m", dimensions=384, content_sha256="0" * 64,
                          embedding=FakeEmbeddingProvider().embed_query("x")))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_deleting_the_chunk_removes_its_embedding(db):
    chunk = make_chunk(db)
    embed(db, chunk)
    db.commit()
    db.delete(chunk)
    db.commit()
    assert db.get(ChunkEmbedding, chunk.id) is None


def test_deleting_the_document_removes_chunks_and_embeddings(db):
    chunk = make_chunk(db)
    other = make_chunk(db, "Outro documento com texto próprio e suficiente.")
    embed(db, chunk)
    embed(db, other)
    db.commit()
    db.delete(db.get(Document, chunk.document_id))
    db.commit()
    remaining = db.scalars(select(ChunkEmbedding.chunk_id)).all()
    assert remaining == [other.id]  # só o do outro documento sobrou


def test_metadata_declares_the_reuse_index_and_the_hnsw_index():
    table = Base.metadata.tables["chunk_embeddings"]
    names = {index.name for index in table.indexes}
    assert names == {"ix_chunk_embeddings_reuse", "ix_chunk_embeddings_embedding_hnsw"}
    assert [c.name for c in table.primary_key.columns] == ["chunk_id"]
    assert table.c.embedding.type.dim == 384 and not table.c.embedding.nullable


# --- somente PostgreSQL --------------------------------------------------------
@requires_postgres
def test_postgres_has_the_hnsw_cosine_index(db):
    definition = db.scalar(text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_chunk_embeddings_embedding_hnsw'"))
    assert definition and "USING hnsw" in definition and "vector_cosine_ops" in definition
    assert "m='16'" in definition and "ef_construction='64'" in definition
    column_type = db.scalar(text(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = 'chunk_embeddings'::regclass AND attname = 'embedding'"
    ))
    assert column_type == "vector(384)"


@requires_postgres
def test_postgres_rejects_a_vector_with_the_wrong_dimension(db):
    chunk = make_chunk(db)
    db.add(ChunkEmbedding(chunk_id=chunk.id, model="m", dimensions=383, content_sha256="0" * 64,
                          embedding=[0.1] * 383))
    with pytest.raises(DBAPIError):
        db.flush()
    db.rollback()


@requires_postgres
def test_postgres_rejects_a_dimensions_column_that_disagrees_with_the_vector(db):
    chunk = make_chunk(db)
    db.add(ChunkEmbedding(chunk_id=chunk.id, model="m", dimensions=768, content_sha256="0" * 64,
                          embedding=FakeEmbeddingProvider().embed_query("x")))
    with pytest.raises(IntegrityError, match="ck_chunk_embeddings_dimensions"):
        db.flush()
    db.rollback()


@requires_postgres
def test_postgres_orders_by_cosine_distance_using_the_hnsw_index(db):
    provider = FakeEmbeddingProvider()
    texts = [
        "contrato de locação residencial com prazo de trinta meses",
        "receita de bolo de cenoura com cobertura de chocolate",
        "manual de instalação do roteador wifi na sala",
    ]
    for content in texts:
        embed(db, make_chunk(db, content), provider)
    db.commit()

    query = provider.embed_query("prazo do contrato de locação")
    distance = ChunkEmbedding.embedding.cosine_distance(query)
    statement = select(DocumentChunk.content, distance).join(
        ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id
    ).order_by(distance).limit(3)
    rows = db.execute(statement).all()
    assert rows[0][0] == texts[0]
    assert [r[1] for r in rows] == sorted(r[1] for r in rows)
    assert 0.0 <= rows[0][1] < rows[1][1] <= 1.0 + 1e-6

    # Com poucos registros o planejador prefere varrer a tabela; desligando isso, o índice é usável.
    db.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        r[0] for r in db.execute(text(
            "EXPLAIN SELECT chunk_id FROM chunk_embeddings ORDER BY embedding <=> CAST(:q AS vector) LIMIT 2"
        ), {"q": "[" + ",".join(str(x) for x in query) + "]"})
    )
    assert "ix_chunk_embeddings_embedding_hnsw" in plan
    db.rollback()


# --- migration 0007 (PostgreSQL com pgvector) ----------------------------------
def schema_signature(engine) -> dict:
    inspector = inspect(engine)
    return {
        "columns": {c["name"]: (str(c["type"]).lower(), c["nullable"]) for c in inspector.get_columns("chunk_embeddings")},
        "pk": inspector.get_pk_constraint("chunk_embeddings")["constrained_columns"],
        "fk": [(f["name"], f["referred_table"], f["options"].get("ondelete")) for f in inspector.get_foreign_keys("chunk_embeddings")],
        "checks": sorted(c["name"] for c in inspector.get_check_constraints("chunk_embeddings")),
        "indexes": sorted(i["name"] for i in inspector.get_indexes("chunk_embeddings")),
    }


@pytest.fixture()
def keep_logging_state():
    """O `env.py` do Alembic chama `fileConfig`, que desativa os loggers existentes. Restaura o estado
    para não afetar os testes seguintes (por exemplo, os que leem `caplog`)."""
    manager = logging.root.manager
    disabled = {name: lg.disabled for name, lg in manager.loggerDict.items() if isinstance(lg, logging.Logger)}
    level = logging.root.level
    yield
    for name, was_disabled in disabled.items():
        logger = manager.loggerDict.get(name)
        if isinstance(logger, logging.Logger):
            logger.disabled = was_disabled
    logging.root.setLevel(level)


@requires_postgres
def test_migration_chain_reaches_0007_and_matches_the_models(monkeypatch, keep_logging_state):
    """Cadeia 0001 → 0007 num banco vazio, downgrade 0007 → 0006 e de novo até o head.

    Apaga TODO o esquema do banco de teste (o nome termina em `_test`) e o recria pelas migrations.
    """
    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings

    backend = Path(__file__).resolve().parent.parent
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    get_settings.cache_clear()
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))

    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))

        command.upgrade(config, "head")
        migrated = schema_signature(engine)
        assert inspect(engine).has_table("chunk_embeddings")
        assert migrated["pk"] == ["chunk_id"]
        assert migrated["fk"] == [("fk_chunk_embeddings_chunk", "document_chunks", "CASCADE")]
        assert migrated["indexes"] == ["ix_chunk_embeddings_embedding_hnsw", "ix_chunk_embeddings_reuse"]

        command.downgrade(config, "0006")
        assert not inspect(engine).has_table("chunk_embeddings")
        assert inspect(engine).has_table("document_chunks")  # a migration anterior segue intacta
        command.upgrade(config, "head")
        assert schema_signature(engine) == migrated  # idêntico depois do ciclo

        # O esquema das migrations tem de ser o mesmo que os modelos geram (create_all).
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(engine)
        assert schema_signature(engine) == migrated
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))  # o DROP a leva junto
        engine.dispose()
        get_settings.cache_clear()
