"""Etapa B dos embeddings: geração, reaproveitamento, retomada e comando de manutenção.

Usa só o `FakeEmbeddingProvider`: sem rede, sem modelo e sem credenciais. Os testes com threads
reais e o conflito entre execuções simultâneas exigem PostgreSQL (`TEST_DATABASE_URL`).
"""

import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import cli
from app.core.config import Settings, get_settings
from app.main import app
from app.models import ChunkEmbedding, Document, DocumentChunk, DocumentPage
from app.services import documents as documents_service
from app.services import embedding_tasks
from app.services.embedding_tasks import (
    EmbeddingRunner,
    documents_pending_embedding,
    embed_document,
    recover_pending_embeddings,
    restore_embeddings,
    snapshot_embeddings,
)
from app.services.embeddings import (
    EmbeddingConfigError,
    EmbeddingTransientError,
    FakeEmbeddingProvider,
    text_sha256,
)
from app.services.processing import DocumentProcessor
from tests.conftest import requires_postgres
from tests.docs_helpers import long_text, ok
from tests.pdfs import unique_pdf


# --- apoio ------------------------------------------------------------------------------
def settings(**overrides) -> Settings:
    values = dict(embeddings_enabled=True, embedding_provider="fake", embedding_retry_backoff_seconds=0.5)
    values.update(overrides)
    return Settings(_env_file=None, **values)


class ScriptedProvider(FakeEmbeddingProvider):
    """Provedor falso que falha conforme um roteiro (um item por chamada; None = funciona)."""

    def __init__(self, script=(), model="fake-hash-v1", delay=0.0, on_call=None, **kwargs):
        super().__init__(model=model, **kwargs)
        self.script = list(script)
        self.delay = delay
        self.on_call = on_call
        self.batches: list[list[str]] = []
        self._lock = threading.Lock()

    def embed_passages(self, texts):
        with self._lock:
            self.batches.append(list(texts))
            failure = self.script.pop(0) if self.script else None
        if self.on_call:
            self.on_call(list(texts))
        if self.delay:
            time.sleep(self.delay)
        if failure is not None:
            raise failure
        return super().embed_passages(texts)


class Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def make_document(db, contents: list[str], status: str = "completed") -> Document:
    """Documento com uma página e um trecho por item de `contents`."""
    document = Document(
        title="Doc", original_filename="d.pdf", storage_key=f"{uuid.uuid4()}.pdf", size_bytes=10,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex, status=status, has_text=True, page_count=len(contents),
    )
    db.add(document)
    db.flush()
    for number, content in enumerate(contents, start=1):
        db.add(DocumentPage(document_id=document.id, page_number=number, text=content))
    db.flush()
    for index, content in enumerate(contents):
        db.add(DocumentChunk(
            document_id=document.id, page_number=index + 1, chunk_index=index, content=content,
            character_count=len(content), start_offset=0, end_offset=len(content),
        ))
    db.commit()
    return document


def rows_of(db, document_id) -> list[ChunkEmbedding]:
    return list(db.scalars(
        select(ChunkEmbedding).join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
        .where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index)
    ))


def texts_for(n: int) -> list[str]:
    return [f"Trecho número {i} sobre assunto {i * 7} diferente dos demais." for i in range(n)]


# --- geração básica ----------------------------------------------------------------------
def test_embeds_every_chunk_with_model_dimensions_and_hash(db):
    contents = texts_for(3)
    document = make_document(db, contents)
    provider = FakeEmbeddingProvider()
    result = embed_document(db, provider, settings(), document.id)

    assert (result.status, result.generated, result.reused, result.remaining) == ("completed", 3, 0, 0)
    assert result.provider_calls == 1 and result.error is None
    rows = rows_of(db, document.id)
    assert [r.content_sha256 for r in rows] == [text_sha256(c) for c in contents]
    assert {r.model for r in rows} == {"fake-hash-v1"} and {r.dimensions for r in rows} == {384}
    assert all(len(r.embedding) == 384 for r in rows)
    assert db.get(Document, document.id).status == "completed"


def test_embeds_in_batches_of_the_configured_size(db):
    document = make_document(db, texts_for(5))
    provider = ScriptedProvider()
    result = embed_document(db, provider, settings(embedding_batch_size=2), document.id)
    assert [len(b) for b in provider.batches] == [2, 2, 1]
    assert result.generated == 5 and result.provider_calls == 3 and len(rows_of(db, document.id)) == 5


def test_second_run_is_idempotent_and_calls_nothing(db):
    document = make_document(db, texts_for(4))
    provider = FakeEmbeddingProvider()
    embed_document(db, provider, settings(), document.id)
    before = [(r.chunk_id, r.embedding) for r in rows_of(db, document.id)]
    again = embed_document(db, provider, settings(), document.id)
    assert (again.status, again.generated, again.reused, again.provider_calls) == ("completed", 0, 0, 0)
    assert provider.passage_calls == 1
    assert [(r.chunk_id, r.embedding) for r in rows_of(db, document.id)] == before


def test_repeated_text_inside_a_document_is_sent_once(db):
    contents = ["Cláusula padrão repetida em várias páginas do contrato.", "Texto único desta página.",
                "Cláusula padrão repetida em várias páginas do contrato."]
    document = make_document(db, contents)
    provider = ScriptedProvider()
    result = embed_document(db, provider, settings(), document.id)
    assert provider.batches == [[contents[0], contents[1]]]  # dois textos distintos, não três
    assert (result.generated, result.reused) == (2, 1)
    rows = rows_of(db, document.id)
    assert len(rows) == 3 and rows[0].embedding == rows[2].embedding


def test_text_already_embedded_in_another_document_is_copied_not_recomputed(db):
    contents = texts_for(3)
    first, second = make_document(db, contents), make_document(db, contents + ["Um trecho exclusivo do segundo."])
    provider = ScriptedProvider()
    embed_document(db, provider, settings(), first.id)
    provider.batches.clear()
    result = embed_document(db, provider, settings(), second.id)
    assert provider.batches == [["Um trecho exclusivo do segundo."]]  # só o texto novo vai ao provedor
    assert (result.generated, result.reused, result.remaining) == (1, 3, 0)
    assert len(rows_of(db, second.id)) == 4


def test_reuse_does_not_cross_models(db):
    contents = texts_for(2)
    first, second = make_document(db, contents), make_document(db, contents)
    embed_document(db, ScriptedProvider(model="modelo-a"), settings(), first.id)
    other = ScriptedProvider(model="modelo-b")
    result = embed_document(db, other, settings(), second.id)
    assert result.generated == 2 and result.reused == 0 and len(other.batches[0]) == 2


def test_switching_models_replaces_the_vectors(db):
    document = make_document(db, texts_for(3))
    embed_document(db, ScriptedProvider(model="modelo-a"), settings(), document.id)
    result = embed_document(db, ScriptedProvider(model="modelo-b"), settings(), document.id)
    assert result.generated == 3
    rows = rows_of(db, document.id)
    assert len(rows) == 3 and {r.model for r in rows} == {"modelo-b"}


def test_documents_that_are_not_completed_or_do_not_exist_are_left_alone(db):
    provider = ScriptedProvider()
    pending = make_document(db, texts_for(2), status="pending")
    assert embed_document(db, provider, settings(), pending.id).status == "skipped"
    assert embed_document(db, provider, settings(), uuid.uuid4()).status == "deleted"
    assert provider.batches == [] and rows_of(db, pending.id) == []


def test_document_without_chunks_is_complete_with_no_calls(db):
    document = make_document(db, [])
    provider = ScriptedProvider()
    assert embed_document(db, provider, settings(), document.id).status == "completed"
    assert provider.batches == []


# --- falhas do provedor ---------------------------------------------------------------------
def test_transient_failures_are_retried_with_doubling_backoff(db):
    document = make_document(db, texts_for(2))
    provider = ScriptedProvider([EmbeddingTransientError("ocupado"), EmbeddingTransientError("ocupado")])
    sleeps = Sleeps()
    result = embed_document(db, provider, settings(embedding_max_attempts=3), document.id, sleep=sleeps)
    assert result.status == "completed" and result.provider_calls == 3 and result.generated == 2
    assert sleeps.waits == [0.5, 1.0]
    assert len(rows_of(db, document.id)) == 2


def test_exhausted_retries_leave_the_document_completed_and_resumable(db):
    contents = texts_for(2)
    document = make_document(db, contents)
    always = [EmbeddingTransientError("CPF 123.456.789-00")] * 3
    sleeps = Sleeps()
    result = embed_document(db, ScriptedProvider(always), settings(embedding_max_attempts=3), document.id, sleep=sleeps)

    assert result.status == "failed" and result.error == "EmbeddingTransientError"
    assert result.provider_calls == 3 and result.remaining == 2 and result.generated == 0
    assert sleeps.waits == [0.5, 1.0]  # sem espera depois da última tentativa
    assert "123.456" not in repr(result)
    assert db.get(Document, document.id).status == "completed" and db.get(Document, document.id).error_message is None
    assert rows_of(db, document.id) == []

    recovered = embed_document(db, FakeEmbeddingProvider(), settings(), document.id)  # o provedor voltou
    assert recovered.status == "completed" and recovered.generated == 2 and len(rows_of(db, document.id)) == 2


def test_failure_in_a_later_batch_keeps_the_earlier_ones_and_resumes_from_there(db):
    document = make_document(db, texts_for(5))
    broken = ScriptedProvider([None, RuntimeError("falha inesperada")])
    result = embed_document(db, broken, settings(embedding_batch_size=2), document.id)
    assert result.status == "failed" and result.error == "RuntimeError"
    assert (result.generated, result.remaining) == (2, 3)
    assert len(rows_of(db, document.id)) == 2  # o primeiro lote foi confirmado sozinho
    assert broken.script == [] and len(broken.batches) == 2  # erro inesperado não é repetido

    healthy = ScriptedProvider()
    resumed = embed_document(db, healthy, settings(embedding_batch_size=2), document.id)
    assert resumed.status == "completed" and resumed.generated == 3
    assert [len(b) for b in healthy.batches] == [2, 1]  # só o que faltava
    assert len(rows_of(db, document.id)) == 5


def test_wrong_dimension_from_the_provider_is_rejected_and_never_stored(db):
    document = make_document(db, texts_for(2))
    provider = ScriptedProvider(dimensions=8, model="modelo-curto")  # o provedor diz 8; o esquema exige 384
    result = embed_document(db, provider, settings(), document.id)
    assert result.status == "failed" and result.error == "EmbeddingConfigError" and result.remaining == 2
    assert provider.batches == [] and rows_of(db, document.id) == []  # recusado antes de qualquer chamada


def test_provider_returning_the_wrong_number_of_vectors_is_rejected(db):
    class Short(FakeEmbeddingProvider):
        def embed_passages(self, texts):
            return super().embed_passages(texts)[:-1]

    document = make_document(db, texts_for(3))
    result = embed_document(db, Short(), settings(), document.id)
    assert result.status == "failed" and result.error == "EmbeddingError" and rows_of(db, document.id) == []
    assert result.provider_calls == 1  # erro de contrato não é repetido


# --- concorrência ----------------------------------------------------------------------------
def test_second_task_for_the_same_document_in_this_process_backs_off(db, session_factory):
    document = make_document(db, texts_for(3))
    inner: list = []

    def concurrent_attempt(_texts):
        with session_factory() as other:
            inner.append(embed_document(other, FakeEmbeddingProvider(), settings(), document.id))

    provider = ScriptedProvider(on_call=concurrent_attempt)
    outer = embed_document(db, provider, settings(), document.id)
    assert [r.status for r in inner] == ["busy"] and outer.status == "completed"
    assert len(provider.batches) == 1 and len(rows_of(db, document.id)) == 3


def test_vectors_written_by_another_process_meanwhile_are_not_duplicated(db, session_factory):
    document = make_document(db, texts_for(3))

    def other_process_writes_first(texts):
        with session_factory() as other:  # simula a API e a CLI trabalhando no mesmo documento
            for chunk in other.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)):
                other.add(ChunkEmbedding(
                    chunk_id=chunk.id, model="fake-hash-v1", dimensions=384,
                    content_sha256=text_sha256(chunk.content), embedding=FakeEmbeddingProvider().embed_query(chunk.content),
                ))
            other.commit()

    result = embed_document(db, ScriptedProvider(on_call=other_process_writes_first), settings(), document.id)
    assert result.status == "completed" and result.remaining == 0
    assert len(rows_of(db, document.id)) == 3  # nenhum erro de chave duplicada, nenhuma linha extra


@requires_postgres
def test_many_threads_on_one_document_produce_one_set_of_vectors(session_factory):
    with session_factory() as setup:
        document_id = make_document(setup, texts_for(6)).id
    provider = ScriptedProvider(delay=0.15)
    results, errors = [], []

    def worker():
        try:
            with session_factory() as session:
                results.append(embed_document(session, provider, settings(), document_id))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not errors and len(results) == 6
    assert {r.status for r in results} <= {"completed", "busy"}
    assert len(provider.batches) == 1  # uma única chamada ao provedor, apesar de seis tarefas
    with session_factory() as check:
        assert len(rows_of(check, document_id)) == 6


@requires_postgres
def test_two_executions_that_bypass_the_local_guard_still_store_each_vector_once(session_factory):
    """Simula dois processos: a trava em memória não vale entre eles, o ON CONFLICT vale."""
    with session_factory() as setup:
        document_id = make_document(setup, texts_for(6)).id
    barrier = threading.Barrier(2, timeout=10)
    provider = ScriptedProvider(on_call=lambda _texts: barrier.wait())  # ambos calculam antes de qualquer gravação
    results, errors = [], []

    def worker():
        try:
            with session_factory() as session:
                results.append(embedding_tasks._embed(session, provider, settings(), document_id, time.sleep))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not errors and len(results) == 2 and len(provider.batches) == 2  # os dois chamaram o provedor
    assert all(r.status == "completed" and r.remaining == 0 for r in results)
    with session_factory() as check:
        assert len(rows_of(check, document_id)) == 6
        assert check.scalar(select(func.count()).select_from(ChunkEmbedding)) == 6


# --- reaproveitamento no reprocessamento ------------------------------------------------------
def test_restore_copies_vectors_only_to_chunks_with_identical_text(db):
    document = make_document(db, ["Texto A estável.", "Texto B que vai mudar.", "Texto C estável."])
    provider = ScriptedProvider()
    embed_document(db, provider, settings(), document.id)
    old_vectors = {r.content_sha256: r.embedding for r in rows_of(db, document.id)}

    saved = snapshot_embeddings(db, document.id)
    assert set(saved) == set(old_vectors)
    from sqlalchemy import delete
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    new_texts = ["Texto A estável.", "Texto B agora diferente.", "Texto C estável."]
    new_chunks = [
        DocumentChunk(document_id=document.id, page_number=i + 1, chunk_index=i, content=t,
                      character_count=len(t), start_offset=0, end_offset=len(t))
        for i, t in enumerate(new_texts)
    ]
    db.add_all(new_chunks)
    db.flush()
    assert restore_embeddings(db, new_chunks, saved) == 2
    db.commit()
    assert len(rows_of(db, document.id)) == 2

    provider.batches.clear()
    result = embed_document(db, provider, settings(), document.id)
    assert provider.batches == [["Texto B agora diferente."]]  # só o trecho alterado chega ao provedor
    assert (result.generated, result.remaining) == (1, 0)
    by_text = {c.content: r for c, r in zip(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id).order_by(DocumentChunk.chunk_index)), rows_of(db, document.id))}
    assert by_text["Texto A estável."].embedding == pytest.approx(old_vectors[text_sha256("Texto A estável.")], abs=1e-5)


def runner_dispatcher(dispatcher, session_factory, provider):
    """Liga o fim do processamento à geração de embeddings, como faz a API (aqui, de forma imediata)."""
    runner = EmbeddingRunner(session_factory, provider, lambda: settings(), sleep=Sleeps())
    dispatcher.processor = DocumentProcessor(session_factory, on_completed=runner.run)
    return runner


def test_a_processed_document_gets_embeddings_automatically(client, dispatcher, session_factory, db):
    provider = ScriptedProvider()
    runner_dispatcher(dispatcher, session_factory, provider)
    doc = ok(client, content=unique_pdf([long_text(), "Segunda página com texto suficiente para um trecho."]))
    assert doc["status"] == "completed" and doc["chunk_count"] > 2
    rows = rows_of(db, uuid.UUID(doc["id"]))
    assert len(rows) == doc["chunk_count"] and {r.model for r in rows} == {"fake-hash-v1"}


def test_reprocessing_the_same_pdf_reuses_every_vector_without_calling_the_provider(client, dispatcher, session_factory, db):
    provider = ScriptedProvider()
    runner_dispatcher(dispatcher, session_factory, provider)
    doc = ok(client, content=unique_pdf([long_text(), "Segunda página com texto suficiente para um trecho."]))
    document_id = uuid.UUID(doc["id"])
    before_chunks = set(db.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)))
    before = {r.content_sha256: r.embedding for r in rows_of(db, document_id)}
    calls_before = len(provider.batches)
    assert calls_before >= 1

    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 202
    assert client.get(f"/api/documents/{doc['id']}").json()["status"] == "completed"

    db.expire_all()
    after_chunks = set(db.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)))
    assert after_chunks.isdisjoint(before_chunks)  # os trechos foram recriados com ids novos...
    rows = rows_of(db, document_id)
    assert len(rows) == len(after_chunks)
    assert {r.chunk_id for r in rows} == after_chunks  # ...e todos já têm vetor
    assert {r.content_sha256: r.embedding for r in rows} == before  # os mesmos vetores
    assert len(provider.batches) == calls_before  # nenhuma chamada nova ao provedor


def test_rebuild_chunks_also_keeps_the_vectors(db):
    document = make_document(db, texts_for(3))
    provider = ScriptedProvider()
    embed_document(db, provider, settings(), document.id)
    old_chunks = set(db.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == document.id)))
    documents_service.rebuild_chunks(db, get_settings(), document.id)  # mesma configuração: textos idênticos
    new_chunks = set(db.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == document.id)))
    assert new_chunks and new_chunks.isdisjoint(old_chunks)
    assert {r.chunk_id for r in rows_of(db, document.id)} == new_chunks
    assert embed_document(db, provider, settings(), document.id).provider_calls == 0


def test_a_failing_embedding_hook_never_fails_the_document(client, dispatcher, session_factory):
    def broken_hook(_document_id):
        raise RuntimeError("falha ao enfileirar")

    dispatcher.processor = DocumentProcessor(session_factory, on_completed=broken_hook)
    doc = ok(client)
    assert doc["status"] == "completed" and doc["chunk_count"] > 0 and doc["error_message"] is None


def test_provider_outage_after_processing_leaves_the_document_usable_then_embed_pending_finishes_it(
    client, dispatcher, session_factory, db, capsys
):
    outage = ScriptedProvider([EmbeddingTransientError("fora do ar")] * 3)
    runner_dispatcher(dispatcher, session_factory, outage)
    doc = ok(client)
    document_id = uuid.UUID(doc["id"])
    assert doc["status"] == "completed" and doc["chunk_count"] > 0  # texto e trechos utilizáveis
    assert rows_of(db, document_id) == []

    healthy = ScriptedProvider()
    code = cli.main(["embed-pending"], session_factory=session_factory, settings=settings(),
                    provider_factory=lambda _s: healthy, sleep=Sleeps())
    assert code == 0 and "1 documento(s) tratado(s)" in capsys.readouterr().out
    assert len(rows_of(db, document_id)) == doc["chunk_count"]


# --- pendências e retomada --------------------------------------------------------------------
class RecordingDispatcher:
    def __init__(self) -> None:
        self.submitted: list[uuid.UUID] = []

    def submit(self, document_id) -> None:
        self.submitted.append(document_id)


def test_pending_documents_are_derived_from_chunks_without_a_vector(db):
    done = make_document(db, texts_for(2))
    partial = make_document(db, texts_for(3))
    untouched = make_document(db, texts_for(1))
    queued = make_document(db, texts_for(2), status="pending")
    empty = make_document(db, [])
    provider = FakeEmbeddingProvider()
    embed_document(db, provider, settings(), done.id)
    embed_document(db, provider, settings(embedding_batch_size=1), partial.id)
    db.execute(ChunkEmbedding.__table__.delete().where(ChunkEmbedding.chunk_id == db.scalars(
        select(DocumentChunk.id).where(DocumentChunk.document_id == partial.id).order_by(DocumentChunk.chunk_index)).first()))
    db.commit()

    assert documents_pending_embedding(db, "fake-hash-v1") == [partial.id, untouched.id]  # na ordem de criação
    assert queued.id not in documents_pending_embedding(db, "fake-hash-v1")  # só `completed`
    assert empty.id not in documents_pending_embedding(db, "fake-hash-v1")
    # Trocar de modelo torna tudo pendente de novo.
    assert set(documents_pending_embedding(db, "outro-modelo")) == {done.id, partial.id, untouched.id}


def test_startup_recovery_submits_only_documents_with_pending_chunks(db, session_factory):
    complete, missing = make_document(db, texts_for(2)), make_document(db, texts_for(2))
    embed_document(db, FakeEmbeddingProvider(), settings(), complete.id)
    recording = RecordingDispatcher()
    assert recover_pending_embeddings(session_factory, recording, "fake-hash-v1") == 1
    assert recording.submitted == [missing.id]


def test_api_startup_resumes_pending_embeddings_in_the_background(db, session_factory, monkeypatch):
    document = make_document(db, texts_for(4))
    monkeypatch.setattr("app.main.SessionLocal", session_factory)
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    get_settings.cache_clear()
    try:
        with TestClient(app):
            assert app.state.embedding_dispatcher is not None
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with session_factory() as check:
                    if len(rows_of(check, document.id)) == 4:
                        break
                time.sleep(0.05)
        with session_factory() as check:
            assert len(rows_of(check, document.id)) == 4
        assert app.state.embedding_dispatcher is None  # encerrado junto com a aplicação
    finally:
        get_settings.cache_clear()


def test_api_starts_without_embeddings_when_disabled_or_misconfigured(db, session_factory, monkeypatch, tmp_path):
    make_document(db, texts_for(2))
    monkeypatch.setattr("app.main.SessionLocal", session_factory)
    get_settings.cache_clear()
    with TestClient(app):
        assert app.state.embedding_dispatcher is None  # padrão: desligado

    monkeypatch.setenv("EMBEDDINGS_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("EMBEDDING_MODEL_PATH", str(tmp_path / "sem-modelo"))  # arquivos ausentes: a API sobe mesmo assim
    get_settings.cache_clear()
    try:
        with TestClient(app) as test_client:
            assert app.state.embedding_dispatcher is None
            assert test_client.get("/api/health").status_code == 200
    finally:
        get_settings.cache_clear()
    with session_factory() as check:
        assert check.scalar(select(func.count()).select_from(ChunkEmbedding)) == 0


# --- comando embed-pending ---------------------------------------------------------------------
def run_cli(session_factory, provider, *argv, **config):
    return cli.main(["embed-pending", *argv], session_factory=session_factory, settings=settings(**config),
                    provider_factory=lambda _s: provider, sleep=Sleeps())


def test_embed_pending_generates_what_is_missing_and_is_idempotent(db, session_factory, capsys):
    first, second = make_document(db, texts_for(3)), make_document(db, texts_for(3) + ["Mais um trecho."])
    provider = ScriptedProvider()
    assert run_cli(session_factory, provider) == 0
    out = capsys.readouterr().out
    assert "2 documento(s) tratado(s), 4 vetor(es) gerado(s), 3 trecho(s) reaproveitado(s), 0 falha(s)." in out
    assert len(rows_of(db, first.id)) == 3 and len(rows_of(db, second.id)) == 4

    calls = len(provider.batches)
    assert run_cli(session_factory, provider) == 0
    assert "0 documento(s) tratado(s), 0 vetor(es) gerado(s)" in capsys.readouterr().out
    assert len(provider.batches) == calls


def test_embed_pending_can_target_one_document(db, session_factory, capsys):
    target, other = make_document(db, texts_for(2)), make_document(db, ["Outro documento com texto próprio."])
    assert run_cli(session_factory, ScriptedProvider(), "--document-id", str(target.id)) == 0
    assert len(rows_of(db, target.id)) == 2 and rows_of(db, other.id) == []


def test_embed_pending_reports_failures_with_exit_code_1_and_no_document_text(db, session_factory, capsys):
    document = make_document(db, ["Conteúdo sigiloso do paciente João."])
    provider = ScriptedProvider([EmbeddingTransientError("segredo")] * 3)
    assert run_cli(session_factory, provider) == 1
    captured = capsys.readouterr()
    assert "1 falha(s)" in captured.out and "EmbeddingTransientError" in captured.err
    assert "sigiloso" not in captured.out + captured.err and "segredo" not in captured.out + captured.err
    assert rows_of(db, document.id) == []
    assert run_cli(session_factory, ScriptedProvider()) == 0  # a próxima execução termina o trabalho
    assert len(rows_of(db, document.id)) == 1


def test_embed_pending_refuses_to_run_when_disabled_or_when_the_provider_is_unavailable(session_factory, capsys, tmp_path):
    assert cli.main(["embed-pending"], session_factory=session_factory, settings=Settings(_env_file=None)) == 2
    assert "desligados" in capsys.readouterr().err

    assert cli.main(["embed-pending"], session_factory=session_factory,
                    settings=Settings(_env_file=None, embeddings_enabled=True, embedding_provider="local",
                                      embedding_model_path=str(tmp_path / "sem-modelo"))) == 2
    assert "Arquivo do modelo ausente" in capsys.readouterr().err

    def unavailable(_settings):
        raise EmbeddingConfigError("indisponível")

    assert cli.main(["embed-pending"], session_factory=session_factory, settings=settings(), provider_factory=unavailable) == 2
