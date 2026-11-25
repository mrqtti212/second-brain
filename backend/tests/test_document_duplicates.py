import hashlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.models import Document, DocumentChunk, DocumentPage
from app.services import documents as documents_service
from tests.conftest import make, requires_postgres, stored_files
from tests.docs_helpers import long_text, ok, upload
from tests.pdfs import make_pdf, unique_pdf


def doc_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Document))


def test_second_upload_of_the_same_file_is_a_structured_409(client, storage_dir, db):
    pdf = unique_pdf([long_text()])
    original = ok(client, content=pdf, name="contrato.pdf")

    response = upload(client, content=pdf, name="contrato.pdf")
    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "Este arquivo já foi importado."
    assert body["code"] == "duplicate_document"
    assert body["existing_document"] == {
        "id": original["id"],
        "title": original["title"],
        "original_filename": "contrato.pdf",
        "created_at": body["existing_document"]["created_at"],
    }
    assert body["existing_document"]["created_at"]
    assert doc_count(db) == 1
    assert len(stored_files(storage_dir)) == 1  # nada novo no disco e nenhum temporário


def test_same_content_under_a_different_name_is_a_duplicate(client, db):
    pdf = unique_pdf([long_text()])
    original = ok(client, content=pdf, name="original.pdf", title="Título original")
    response = upload(client, content=pdf, name="outro_nome_completamente_diferente.pdf", title="Outro título")
    assert response.status_code == 409
    assert response.json()["existing_document"]["id"] == original["id"]
    assert response.json()["existing_document"]["original_filename"] == "original.pdf"
    assert doc_count(db) == 1


def test_duplicate_does_not_modify_the_original_document(client, db):
    cat = make(client, "/api/categories", name="C")
    pdf = unique_pdf([long_text()])
    original = ok(client, content=pdf, title="Intacto")
    pages_before = db.scalar(select(func.count()).select_from(DocumentPage))
    chunks_before = db.scalar(select(func.count()).select_from(DocumentChunk))

    assert upload(client, content=pdf, title="Novo título", category_id=cat["id"]).status_code == 409

    after = client.get(f"/api/documents/{original['id']}").json()
    assert after["title"] == "Intacto" and after["category"] is None
    assert after["updated_at"] == original["updated_at"] and after["sha256"] == original["sha256"]
    assert db.scalar(select(func.count()).select_from(DocumentPage)) == pages_before
    assert db.scalar(select(func.count()).select_from(DocumentChunk)) == chunks_before
    assert client.get(f"/api/documents/{original['id']}/file").content == pdf  # arquivo original preservado


def test_files_with_different_bytes_are_not_duplicates_even_if_visually_identical(client, db):
    text = [long_text(5)]
    first = ok(client, content=make_pdf(text))
    second = upload(client, content=make_pdf(text) + b"\n")  # mesmo texto, 1 byte a mais
    assert second.status_code == 201
    assert second.json()["sha256"] != first["sha256"]
    assert doc_count(db) == 2


def test_same_name_with_different_content_is_accepted(client):
    ok(client, content=unique_pdf(["Primeiro conteúdo com texto suficiente para o teste."]), name="relatorio.pdf")
    assert upload(client, content=unique_pdf(["Segundo conteúdo, bem diferente do primeiro."]), name="relatorio.pdf").status_code == 201


def test_hash_comes_from_the_received_bytes_not_from_the_client(client):
    pdf = unique_pdf([long_text(3)])
    doc = ok(client, content=pdf)
    assert doc["sha256"] == hashlib.sha256(pdf).hexdigest()


def test_reupload_is_allowed_after_the_document_is_deleted(client, storage_dir):
    pdf = unique_pdf([long_text(3)])
    first = ok(client, content=pdf)
    assert upload(client, content=pdf).status_code == 409
    assert client.delete(f"/api/documents/{first['id']}").status_code == 204
    again = upload(client, content=pdf)
    assert again.status_code == 201 and again.json()["id"] != first["id"]
    assert len(stored_files(storage_dir)) == 1


def test_documents_without_text_and_failed_ones_also_deduplicate(client, monkeypatch):
    blank = unique_pdf(["", ""])
    ok(client, content=blank)
    assert upload(client, content=blank).status_code == 409

    monkeypatch.setattr(documents_service.pdf, "extract_text", lambda _r: (_ for _ in ()).throw(RuntimeError("x")))
    broken = unique_pdf([long_text(3)])
    assert ok(client, content=broken)["status"] == "failed"
    monkeypatch.undo()
    duplicate = upload(client, content=broken)
    assert duplicate.status_code == 409  # exclua o documento com falha para tentar de novo


def test_invalid_files_are_still_rejected_before_any_hash_logic(client):
    assert upload(client, content=b"").status_code == 422
    assert upload(client, content=b"%PDF-1.4 lixo").status_code == 422


def test_database_enforces_unique_sha256(client, db):
    original = ok(client)
    db.add(
        Document(
            title="x", original_filename="x.pdf", storage_key="a" * 32 + ".pdf", content_type="application/pdf",
            size_bytes=1, sha256=original["sha256"], status="completed", has_text=False,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert doc_count(db) == 1


def test_lost_race_is_resolved_by_the_unique_index(client, storage_dir, db, monkeypatch):
    """Simula duas requisições que passam pela checagem prévia antes de qualquer commit."""
    pdf = unique_pdf([long_text()])
    original = ok(client, content=pdf)
    real = documents_service.find_by_hash
    calls = {"n": 0}

    def blind_first_lookup(session, sha):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(session, sha)  # a checagem prévia "não vê" o vencedor

    monkeypatch.setattr(documents_service, "find_by_hash", blind_first_lookup)
    response = upload(client, content=pdf, name="perdedor.pdf")
    assert response.status_code == 409
    assert response.json()["existing_document"]["id"] == original["id"]
    assert calls["n"] == 2
    assert doc_count(db) == 1
    assert len(stored_files(storage_dir)) == 1  # o arquivo do perdedor foi removido
    assert db.scalar(select(func.count()).select_from(DocumentPage)) == original["page_count"]


@requires_postgres
def test_two_simultaneous_uploads_of_the_same_file_create_exactly_one_document(client, storage_dir, db, monkeypatch):
    pdf = unique_pdf([long_text()])
    barrier = threading.Barrier(2)
    seen = threading.local()
    real = documents_service.find_by_hash

    def synchronized(session, sha):
        found = real(session, sha)
        if not getattr(seen, "waited", False):  # só na checagem prévia de cada requisição
            seen.waited = True
            barrier.wait(timeout=15)  # as duas passam pela checagem antes de qualquer commit
        return found

    monkeypatch.setattr(documents_service, "find_by_hash", synchronized)

    def send(name: str) -> int:
        with TestClient(app) as local:
            return local.post("/api/documents", files={"file": (name, pdf, "application/pdf")}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(send, ["a.pdf", "b.pdf"]))

    assert statuses == [201, 409]
    assert doc_count(db) == 1
    files = stored_files(storage_dir)
    assert len(files) == 1 and files[0].endswith(".pdf")  # sem arquivo órfão nem temporário
    assert db.scalar(select(func.count()).select_from(DocumentChunk)) > 0
    assert db.scalar(select(func.count()).select_from(DocumentPage)) == 1  # PDF de 1 página: não duplicou as páginas


@requires_postgres
def test_many_simultaneous_uploads_of_the_same_file(client, storage_dir, db):
    pdf = unique_pdf([long_text()])

    def send(i: int) -> int:
        with TestClient(app) as local:
            return local.post("/api/documents", files={"file": (f"c{i}.pdf", pdf, "application/pdf")}).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(send, range(6)))
    assert statuses.count(201) == 1 and statuses.count(409) == 5
    assert doc_count(db) == 1 and len(stored_files(storage_dir)) == 1
