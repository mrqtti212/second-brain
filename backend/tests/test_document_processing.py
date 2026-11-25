"""Processamento em segundo plano: estados, falhas, reprocessamento, concorrência e retomada."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app import cli
from app.api.deps import get_dispatcher
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models import Document, DocumentChunk, DocumentPage
from app.services import documents as documents_service
from app.services import pdf as pdf_module
from app.services import processing
from app.services.processing import DocumentProcessor, ThreadPoolDispatcher, recover_interrupted
from tests.conftest import make, requires_postgres, stored_files
from tests.docs_helpers import all_chunks, long_text, upload
from tests.pdfs import unique_pdf


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def accept(client, dispatcher, **kwargs) -> dict:
    """Upload com o segundo plano parado: devolve o documento como foi aceito (`pending`)."""
    dispatcher.manual()
    response = upload(client, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def detail(client, document_id) -> dict:
    return client.get(f"/api/documents/{document_id}").json()


def snapshot(client, document_id) -> dict:
    """Tudo que o usuário vê do conteúdo: páginas, trechos e campos derivados."""
    d = detail(client, document_id)
    return {
        "pages": client.get(f"/api/documents/{document_id}/content").json()["pages"],
        "chunks": all_chunks(client, document_id),
        "fields": (d["page_count"], d["chunk_count"], d["has_text"]),
    }


def fail_extraction(monkeypatch, message="boom"):
    monkeypatch.setattr(pdf_module, "extract_text", lambda _r: (_ for _ in ()).throw(RuntimeError(message)))


# --- upload devolve antes do processamento --------------------------------------------
def test_upload_returns_pending_before_any_extraction(client, dispatcher, storage_dir, monkeypatch):
    monkeypatch.setattr(pdf_module, "extract_text", lambda _r: pytest.fail("a extração não pode rodar durante o upload"))
    doc = accept(client, dispatcher)

    assert doc["status"] == "pending"
    assert doc["has_text"] is False and doc["chunk_count"] == 0 and doc["error_message"] is None
    assert doc["page_count"] == 2  # a estrutura é validada (e as páginas contadas) de forma síncrona
    assert uuid.UUID(doc["id"])
    assert dispatcher.submitted == [uuid.UUID(doc["id"])] and dispatcher.queue == dispatcher.submitted
    assert len(stored_files(storage_dir)) == 1  # original já guardado


def test_accepted_document_is_observable_and_downloadable_while_pending(client, dispatcher):
    pdf = unique_pdf([long_text()])
    response = (dispatcher.manual(), upload(client, content=pdf))[1]
    assert response.headers["location"] == f"/api/documents/{response.json()['id']}"
    document_id = response.json()["id"]

    assert detail(client, document_id)["status"] == "pending"
    assert client.get(f"/api/documents/{document_id}/content").json()["pages"] == []
    assert client.get(f"/api/documents/{document_id}/chunks").json()["items"] == []
    assert client.get(f"/api/documents/{document_id}/file").content == pdf
    assert client.get("/api/documents?status=pending").json()["total"] == 1
    assert client.get("/api/documents?status=completed").json()["total"] == 0


def test_invalid_pdf_is_still_rejected_synchronously_and_nothing_is_queued(client, dispatcher, storage_dir):
    dispatcher.manual()
    assert upload(client, content=b"%PDF-1.4\nlixo").status_code == 422
    assert upload(client, content=b"").status_code == 422
    assert dispatcher.submitted == [] and stored_files(storage_dir) == []


def test_background_run_completes_the_document(client, dispatcher, db):
    doc = accept(client, dispatcher)
    assert dispatcher.run_all() == ["completed"]
    done = detail(client, doc["id"])
    assert done["status"] == "completed" and done["has_text"] is True and done["error_message"] is None
    assert done["chunk_count"] > 2 and done["page_count"] == 2
    assert count(db, DocumentPage) == 2 and count(db, DocumentChunk) == done["chunk_count"]
    assert [c["chunk_index"] for c in all_chunks(client, doc["id"])] == list(range(done["chunk_count"]))


def test_state_is_processing_while_the_work_runs(client, dispatcher, db, monkeypatch):
    doc = accept(client, dispatcher)
    seen = []
    real = pdf_module.extract_text

    def spy(reader):
        db.rollback()
        seen.append(db.scalar(select(Document.status)))
        # durante o trabalho o conteúdo ainda não existe para o cliente
        seen.append(client.get(f"/api/documents/{doc['id']}/chunks").json()["total"])
        return real(reader)

    monkeypatch.setattr(pdf_module, "extract_text", spy)
    dispatcher.run_all()
    assert seen == ["processing", 0]
    assert detail(client, doc["id"])["status"] == "completed"


def test_completed_is_only_reported_when_pages_and_chunks_are_persisted(client, dispatcher, db):
    doc = accept(client, dispatcher)
    dispatcher.run_all()
    assert detail(client, doc["id"])["status"] == "completed"
    assert count(db, DocumentPage) == detail(client, doc["id"])["page_count"]
    assert count(db, DocumentChunk) == detail(client, doc["id"])["chunk_count"] > 0


# --- falhas -------------------------------------------------------------------------------
def test_extraction_failure_marks_failed_and_keeps_the_original(client, dispatcher, storage_dir, db, monkeypatch):
    doc = accept(client, dispatcher)
    fail_extraction(monkeypatch, "falha em /home/segredo/x.pdf")
    assert dispatcher.run_all() == ["failed"]
    failed = detail(client, doc["id"])
    assert failed["status"] == "failed" and failed["has_text"] is False and failed["chunk_count"] == 0
    assert "extrair o texto" in failed["error_message"] and "RuntimeError" in failed["error_message"]
    assert "/home/segredo" not in failed["error_message"]  # nenhum detalhe interno
    assert count(db, DocumentPage) == 0 and count(db, DocumentChunk) == 0
    assert len(stored_files(storage_dir)) == 1
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200


def test_chunking_failure_marks_failed_without_partial_data(client, dispatcher, db, monkeypatch):
    doc = accept(client, dispatcher)
    monkeypatch.setattr(processing.chunker, "chunk_pages", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    dispatcher.run_all()
    failed = detail(client, doc["id"])
    assert failed["status"] == "failed" and "dividir o texto em trechos" in failed["error_message"]
    assert count(db, DocumentPage) == 0 and count(db, DocumentChunk) == 0


def test_failure_while_storing_the_result_marks_failed_without_partial_data(client, dispatcher, db, monkeypatch):
    doc = accept(client, dispatcher)
    monkeypatch.setattr(documents_service, "_chunk_rows", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    dispatcher.run_all()
    failed = detail(client, doc["id"])
    assert failed["status"] == "failed" and "gravar o resultado" in failed["error_message"]
    assert count(db, DocumentPage) == 0 and count(db, DocumentChunk) == 0  # páginas não ficaram sozinhas


def test_failed_document_can_be_reprocessed_and_completes(client, dispatcher, monkeypatch, db):
    doc = accept(client, dispatcher)
    fail_extraction(monkeypatch)
    dispatcher.run_all()
    monkeypatch.undo()

    response = client.post(f"/api/documents/{doc['id']}/reprocess")
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending" and body["error_message"] is None and body["id"] == doc["id"]
    assert dispatcher.run_all() == ["completed"]
    final = detail(client, doc["id"])
    assert final["status"] == "completed" and final["chunk_count"] > 0
    assert count(db, DocumentPage) == 2 and count(db, DocumentChunk) == final["chunk_count"]  # uma só vez


# --- reprocessamento de documento concluído ---------------------------------------------
def test_completed_document_keeps_its_content_until_the_new_version_is_ready(client, dispatcher, db, monkeypatch):
    doc = accept(client, dispatcher)
    dispatcher.run_all()
    before = snapshot(client, doc["id"])

    monkeypatch.setenv("CHUNK_MAX_CHARS", "400")
    monkeypatch.setenv("CHUNK_OVERLAP_CHARS", "50")
    get_settings.cache_clear()
    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 202
    assert detail(client, doc["id"])["status"] == "pending"
    assert snapshot(client, doc["id"]) == before  # nada mudou enquanto aguarda

    dispatcher.run_all()
    after = snapshot(client, doc["id"])
    assert detail(client, doc["id"])["status"] == "completed"
    assert after["fields"][1] > before["fields"][1]  # novos limites => mais trechos
    assert after["pages"] == before["pages"]
    assert [c["chunk_index"] for c in after["chunks"]] == list(range(len(after["chunks"])))
    assert count(db, DocumentChunk) == len(after["chunks"]) and count(db, DocumentPage) == 2  # sem sobras


def test_reprocess_is_idempotent_when_repeated_after_completion(client, dispatcher, db):
    doc = accept(client, dispatcher)
    dispatcher.run_all()
    before = snapshot(client, doc["id"])
    for _ in range(3):
        assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 202
        dispatcher.run_all()
    after = snapshot(client, doc["id"])
    assert [(c["chunk_index"], c["page_number"], c["content"]) for c in after["chunks"]] == [
        (c["chunk_index"], c["page_number"], c["content"]) for c in before["chunks"]
    ]
    assert after["pages"] == before["pages"] and count(db, DocumentPage) == 2 and count(db, DocumentChunk) == len(before["chunks"])


def test_running_the_same_task_twice_does_nothing_the_second_time(client, dispatcher, db):
    doc = accept(client, dispatcher)
    document_id = uuid.UUID(doc["id"])
    assert dispatcher.processor.process(document_id) == "completed"
    chunks = count(db, DocumentChunk)
    assert dispatcher.processor.process(document_id) == "skipped"  # já concluído: não reprocessa sozinho
    assert count(db, DocumentChunk) == chunks and count(db, DocumentPage) == 2


# --- falha numa nova tentativa preserva o que era válido -----------------------------------
def test_failed_retry_preserves_previously_valid_data(client, dispatcher, db, monkeypatch):
    doc = accept(client, dispatcher)
    dispatcher.run_all()
    before = snapshot(client, doc["id"])

    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 202
    fail_extraction(monkeypatch)
    assert dispatcher.run_all() == ["failed"]
    monkeypatch.undo()

    failed = detail(client, doc["id"])
    assert failed["status"] == "failed" and "A versão anterior foi mantida." in failed["error_message"]
    assert snapshot(client, doc["id"]) == before  # páginas, trechos (mesmos ids) e campos intactos
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200

    # nova tentativa posterior funciona e limpa o erro
    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 202
    assert dispatcher.run_all() == ["completed"]
    assert detail(client, doc["id"])["error_message"] is None


def test_failure_in_the_middle_of_the_swap_rolls_everything_back(client, dispatcher, db, monkeypatch):
    doc = accept(client, dispatcher)
    dispatcher.run_all()
    before = snapshot(client, doc["id"])

    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 202
    # as linhas antigas já foram apagadas dentro da transação quando isto explode
    monkeypatch.setattr(documents_service, "_chunk_rows", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert dispatcher.run_all() == ["failed"]
    monkeypatch.undo()

    assert snapshot(client, doc["id"]) == before
    assert count(db, DocumentPage) == 2 and count(db, DocumentChunk) == len(before["chunks"])
    assert "gravar o resultado" in detail(client, doc["id"])["error_message"]


# --- pedidos repetidos e concorrentes ------------------------------------------------------------------
def test_reprocess_requests_while_pending_are_refused_without_new_tasks(client, dispatcher):
    doc = accept(client, dispatcher)  # pending
    for _ in range(3):
        response = client.post(f"/api/documents/{doc['id']}/reprocess")
        assert response.status_code == 409
        assert response.json()["code"] == "already_processing" and response.json()["status"] == "pending"
    assert len(dispatcher.submitted) == 1  # só a tarefa do upload

    dispatcher.run_all()
    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 202
    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 409  # pending de novo
    assert len(dispatcher.submitted) == 2


def test_reprocess_requests_while_processing_are_refused(client, dispatcher, monkeypatch):
    doc = accept(client, dispatcher)
    answers = []
    real = pdf_module.extract_text

    def spy(reader):
        answers.append(client.post(f"/api/documents/{doc['id']}/reprocess"))
        return real(reader)

    monkeypatch.setattr(pdf_module, "extract_text", spy)
    dispatcher.run_all()
    assert [(r.status_code, r.json().get("status")) for r in answers] == [(409, "processing")]
    assert len(dispatcher.submitted) == 1 and detail(client, doc["id"])["status"] == "completed"


@requires_postgres
def test_simultaneous_reprocess_requests_start_exactly_one_task(client, dispatcher, db):
    doc = accept(client, dispatcher)
    dispatcher.run_all()
    submitted_before = len(dispatcher.submitted)
    barrier = threading.Barrier(6)

    def request(_):
        with TestClient(app) as local:
            barrier.wait(timeout=15)
            return local.post(f"/api/documents/{doc['id']}/reprocess").status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(request, range(6)))
    assert sorted(statuses) == [202] + [409] * 5
    assert len(dispatcher.submitted) == submitted_before + 1  # uma única tarefa criada
    dispatcher.run_all()
    assert count(db, DocumentPage) == 2 and detail(client, doc["id"])["status"] == "completed"


def test_reprocess_of_unknown_document_is_404(client, dispatcher):
    assert client.post(f"/api/documents/{uuid.uuid4()}/reprocess").json() == {"detail": "Documento não encontrado."}
    assert client.post(f"/api/documents/{uuid.uuid4()}/reprocess").status_code == 404
    assert client.post("/api/documents/not-a-uuid/reprocess").status_code == 422
    assert dispatcher.submitted == []


def test_reprocess_without_the_original_file_is_a_clear_safe_conflict(client, dispatcher, storage_dir):
    doc = accept(client, dispatcher)
    dispatcher.run_all()
    for f in storage_dir.glob("*.pdf"):
        f.unlink()
    response = client.post(f"/api/documents/{doc['id']}/reprocess")
    assert response.status_code == 409 and response.json()["code"] == "original_file_missing"
    assert "arquivo original" in response.json()["detail"] and str(storage_dir) not in response.text
    assert detail(client, doc["id"])["status"] == "completed"  # nada mudou
    assert len(dispatcher.submitted) == 1


def test_original_lost_after_queueing_fails_the_task_and_keeps_old_data(client, dispatcher, storage_dir):
    doc = accept(client, dispatcher)
    dispatcher.run_all()
    before = snapshot(client, doc["id"])
    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 202
    for f in storage_dir.glob("*.pdf"):
        f.unlink()
    assert dispatcher.run_all() == ["failed"]
    failed = detail(client, doc["id"])
    assert failed["status"] == "failed" and "arquivo original não foi encontrado" in failed["error_message"]
    assert snapshot(client, doc["id"]) == before


# --- duplicatas e exclusão ----------------------------------------------------------------------------------
def test_duplicate_detection_still_works_while_the_first_is_pending(client, dispatcher, storage_dir, db):
    pdf = unique_pdf([long_text()])
    first = accept(client, dispatcher, content=pdf)
    response = upload(client, content=pdf, name="outro-nome.pdf")
    assert response.status_code == 409 and response.json()["existing_document"]["id"] == first["id"]
    assert count(db, Document) == 1 and len(stored_files(storage_dir)) == 1
    assert len(dispatcher.submitted) == 1  # a duplicata não gera tarefa


def test_deleting_a_pending_document_leaves_nothing_behind(client, dispatcher, storage_dir, db):
    doc = accept(client, dispatcher)
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    assert dispatcher.run_all() == ["skipped"]  # a tarefa encontra o documento sumido e não faz nada
    assert count(db, Document) == 0 and count(db, DocumentPage) == 0 and count(db, DocumentChunk) == 0
    assert stored_files(storage_dir) == []


def test_deleting_a_document_during_processing_leaves_no_orphans(client, dispatcher, storage_dir, db, monkeypatch):
    doc = accept(client, dispatcher)
    real = pdf_module.extract_text

    def delete_meanwhile(reader):
        assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
        return real(reader)

    monkeypatch.setattr(pdf_module, "extract_text", delete_meanwhile)
    assert dispatcher.run_all() == ["deleted"]
    assert count(db, Document) == 0 and count(db, DocumentPage) == 0 and count(db, DocumentChunk) == 0
    assert stored_files(storage_dir) == []


def test_deleting_after_processing_removes_pages_and_chunks(client, dispatcher, storage_dir, db):
    doc = accept(client, dispatcher)
    dispatcher.run_all()
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    assert count(db, DocumentPage) == 0 and count(db, DocumentChunk) == 0 and stored_files(storage_dir) == []


def test_metadata_edit_works_in_every_state(client, dispatcher):
    tag = make(client, "/api/tags", name="t")
    doc = accept(client, dispatcher)  # pending
    assert client.patch(f"/api/documents/{doc['id']}", json={"title": "Em fila", "tag_ids": [tag["id"]]}).status_code == 200
    dispatcher.run_all()
    after = detail(client, doc["id"])
    assert after["title"] == "Em fila" and [t["name"] for t in after["tags"]] == ["t"] and after["status"] == "completed"


# --- sessões ---------------------------------------------------------------------------------------------------
class RecordingSession(Session):
    created: list["RecordingSession"] = []

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.threads: set[int] = set()
        self.closed = False
        self.created.append(self)

    def close(self):
        self.closed = True
        super().close()

    def execute(self, *a, **k):
        self.threads.add(threading.get_ident())
        return super().execute(*a, **k)


def recording_factory(session_factory) -> sessionmaker:
    RecordingSession.created = []
    return sessionmaker(bind=session_factory.kw["bind"], class_=RecordingSession, autoflush=False, expire_on_commit=False)


def test_each_task_uses_its_own_session_distinct_from_the_requests(client, dispatcher, session_factory):
    factory = recording_factory(session_factory)

    def tagged_db():
        db = factory()
        db.info["role"] = "request"
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = tagged_db
    processor = DocumentProcessor(factory)
    dispatcher.processor = processor
    docs = [accept(client, dispatcher) for _ in range(3)]
    request_sessions = {id(s) for s in RecordingSession.created if s.info.get("role") == "request"}
    dispatcher.run_all()

    worker_sessions = [s for s in RecordingSession.created if s.info.get("role") != "request"]
    assert len(worker_sessions) == len(docs)  # exatamente uma sessão por tarefa
    assert len({id(s) for s in worker_sessions}) == len(docs)  # nenhuma reaproveitada entre tarefas
    assert not ({id(s) for s in worker_sessions} & request_sessions)  # nenhuma é a da requisição
    assert all(s.closed for s in worker_sessions)  # e todas foram encerradas


@requires_postgres
def test_thread_pool_runs_documents_in_parallel_with_one_session_per_thread(client, dispatcher, session_factory):
    docs = [accept(client, dispatcher, content=unique_pdf([long_text(10 + i)])) for i in range(4)]
    dispatcher.queue.clear()
    factory = recording_factory(session_factory)
    pool = ThreadPoolDispatcher(DocumentProcessor(factory), workers=3)
    try:
        for d in docs:
            pool.submit(uuid.UUID(d["id"]))
        deadline = time.time() + 30
        while time.time() < deadline and any(detail(client, d["id"])["status"] != "completed" for d in docs):
            time.sleep(0.1)
    finally:
        pool.shutdown()
    assert all(detail(client, d["id"])["status"] == "completed" for d in docs)
    sessions = [s for s in RecordingSession.created]
    assert all(len(s.threads) == 1 for s in sessions)  # cada sessão usada por uma única thread
    assert len({id(s) for s in sessions}) == len(sessions) >= len(docs)


@requires_postgres
def test_a_slow_document_does_not_block_the_others(client, dispatcher, session_factory, monkeypatch):
    slow = accept(client, dispatcher, content=unique_pdf([long_text()]))  # 1 página
    fast = accept(client, dispatcher, content=unique_pdf([long_text(5), long_text(6)]))  # 2 páginas
    dispatcher.queue.clear()
    release, entered = threading.Event(), threading.Event()
    real = pdf_module.extract_text

    def maybe_block(reader):
        if len(reader.pages) == 1:
            entered.set()
            release.wait(timeout=30)
        return real(reader)

    monkeypatch.setattr(pdf_module, "extract_text", maybe_block)
    pool = ThreadPoolDispatcher(DocumentProcessor(session_factory), workers=2)
    try:
        pool.submit(uuid.UUID(slow["id"]))
        assert entered.wait(timeout=15)
        pool.submit(uuid.UUID(fast["id"]))
        deadline = time.time() + 20
        while time.time() < deadline and detail(client, fast["id"])["status"] != "completed":
            time.sleep(0.1)
        assert detail(client, fast["id"])["status"] == "completed"  # terminou com o outro ainda preso
        assert detail(client, slow["id"])["status"] == "processing"
        release.set()
        deadline = time.time() + 20
        while time.time() < deadline and detail(client, slow["id"])["status"] != "completed":
            time.sleep(0.1)
        assert detail(client, slow["id"])["status"] == "completed"
    finally:
        release.set()
        pool.shutdown()


# --- retomada após reinício -------------------------------------------------------------------------------------
def test_recovery_requeues_pending_and_interrupted_documents_only(client, dispatcher, session_factory, db):
    pending = accept(client, dispatcher)
    interrupted = accept(client, dispatcher)
    done = accept(client, dispatcher)
    failed = accept(client, dispatcher)
    dispatcher.queue.clear()
    db.execute(text("UPDATE documents SET status='processing' WHERE id = :i"), {"i": interrupted["id"].replace("-", "") if db.get_bind().dialect.name == "sqlite" else interrupted["id"]})
    db.execute(text("UPDATE documents SET status='completed' WHERE id = :i"), {"i": done["id"].replace("-", "") if db.get_bind().dialect.name == "sqlite" else done["id"]})
    db.execute(text("UPDATE documents SET status='failed' WHERE id = :i"), {"i": failed["id"].replace("-", "") if db.get_bind().dialect.name == "sqlite" else failed["id"]})
    db.commit()

    sent_before = len(dispatcher.submitted)
    assert recover_interrupted(session_factory, dispatcher) == 2
    assert {str(i) for i in dispatcher.submitted[sent_before:]} == {pending["id"], interrupted["id"]}
    assert detail(client, interrupted["id"])["status"] == "pending"  # processing voltou para a fila
    assert detail(client, done["id"])["status"] == "completed" and detail(client, failed["id"])["status"] == "failed"

    assert dispatcher.run_all() == ["completed", "completed"]
    assert recover_interrupted(session_factory, dispatcher) == 0  # nada mais a retomar


def test_recovery_can_leave_processing_documents_alone(client, dispatcher, session_factory, db):
    doc = accept(client, dispatcher)
    dispatcher.queue.clear()
    db.execute(text("UPDATE documents SET status='processing'"))
    db.commit()
    assert recover_interrupted(session_factory, dispatcher, include_processing=False) == 0
    assert detail(client, doc["id"])["status"] == "processing"


def test_process_pending_command_processes_what_was_left_behind(client, dispatcher, session_factory, db, capsys):
    first = accept(client, dispatcher)
    second = accept(client, dispatcher)
    dispatcher.queue.clear()
    db.execute(text("UPDATE documents SET status='processing' WHERE sha256 = (SELECT sha256 FROM documents ORDER BY created_at DESC, id LIMIT 1)"))
    db.commit()
    stuck = db.scalar(select(func.count()).select_from(Document).where(Document.status == "processing"))
    assert stuck == 1

    assert cli.main(["process-pending"], session_factory=session_factory) == 0
    assert "1 documento(s) enviado(s)" in capsys.readouterr().out  # só o pending; processing exige a opção
    assert db.scalar(select(func.count()).select_from(Document).where(Document.status == "completed")) == 1

    assert cli.main(["process-pending", "--include-processing"], session_factory=session_factory) == 0
    assert "1 documento(s) enviado(s)" in capsys.readouterr().out
    assert detail(client, first["id"])["status"] == detail(client, second["id"])["status"] == "completed"
    assert count(db, DocumentChunk) > 0


def test_service_is_disabled_without_a_dispatcher(client, dispatcher, storage_dir, db):
    app.dependency_overrides.pop(get_dispatcher)  # sem o override de teste: a aplicação não criou o pool
    response = upload(client)
    assert response.status_code == 503 and "desativado" in response.json()["detail"]
    assert count(db, Document) == 0 and stored_files(storage_dir) == []  # nada foi gravado


def test_lifespan_creates_and_stops_the_pool_when_enabled(monkeypatch):
    monkeypatch.setenv("DOCUMENT_PROCESSING_ENABLED", "true")
    monkeypatch.setenv("RECOVER_ON_STARTUP", "false")  # não toca no banco real
    get_settings.cache_clear()
    with TestClient(app):
        assert isinstance(app.state.dispatcher, ThreadPoolDispatcher)
        pool = app.state.dispatcher
    assert pool._pool._shutdown  # encerrado ao sair
    del app.state.dispatcher


def test_status_filter_validation(client):
    assert client.get("/api/documents?status=whatever").status_code == 422
    assert client.get("/api/documents?status=failed").json()["total"] == 0
