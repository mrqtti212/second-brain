import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import cli
from app.core.config import get_settings
from app.models import Document, DocumentChunk, DocumentPage
from app.services import documents as documents_service
from tests.conftest import make, stored_files
from tests.docs_helpers import all_chunks, chunks_of, long_text, ok, upload
from tests.pdfs import unique_pdf


def pages_of(client, document_id: str) -> dict[int, str]:
    body = client.get(f"/api/documents/{document_id}/content").json()
    return {p["page_number"]: p["text"] for p in body["pages"]}


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


# --- geração na importação ----------------------------------------------------
def test_upload_generates_chunks_traceable_to_their_pages(client):
    doc = ok(client, content=unique_pdf([long_text(), "Segunda página curta, mas com conteúdo útil suficiente.", "oi"]))
    assert doc["status"] == "completed" and doc["page_count"] == 3
    items = all_chunks(client, doc["id"])
    assert doc["chunk_count"] == len(items) > 2

    pages = pages_of(client, doc["id"])
    assert [c["chunk_index"] for c in items] == list(range(len(items)))  # sequencial, sem buracos
    numbers = [c["page_number"] for c in items]
    assert numbers == sorted(numbers)  # a ordem dos trechos segue a das páginas
    assert set(numbers) == {1, 2}  # a página 3 ("oi") não tem conteúdo útil
    for c in items:
        assert c["character_count"] == len(c["content"]) <= get_settings().chunk_max_chars
        assert pages[c["page_number"]][c["start_offset"] : c["end_offset"]] == c["content"]


def test_chunks_of_consecutive_pages_are_never_mixed(client):
    doc = ok(client, content=unique_pdf([long_text(20), long_text(20)]))
    pages = pages_of(client, doc["id"])
    for c in all_chunks(client, doc["id"]):
        assert c["content"] in pages[c["page_number"]]
    first_on_page_2 = next(c for c in all_chunks(client, doc["id"]) if c["page_number"] == 2)
    assert first_on_page_2["start_offset"] == 0  # sem sobreposição vinda da página anterior


def test_chunks_overlap_within_the_same_page(client):
    doc = ok(client, content=unique_pdf([long_text()]))
    items = all_chunks(client, doc["id"])
    assert len(items) >= 3
    for previous, current in zip(items, items[1:], strict=False):
        overlap = previous["end_offset"] - current["start_offset"]
        assert 0 < overlap <= get_settings().chunk_overlap_chars


def test_configuration_is_read_from_the_environment(client, monkeypatch):
    content = unique_pdf([long_text()])
    default_count = ok(client, content=content)["chunk_count"]
    monkeypatch.setenv("CHUNK_MAX_CHARS", "300")
    monkeypatch.setenv("CHUNK_OVERLAP_CHARS", "40")
    get_settings.cache_clear()
    smaller = ok(client, content=unique_pdf([long_text()]))
    assert smaller["chunk_count"] > default_count
    assert max(c["character_count"] for c in all_chunks(client, smaller["id"])) <= 300


def test_invalid_chunk_settings_are_rejected(monkeypatch):
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(chunk_max_chars=300, chunk_overlap_chars=300)
    with pytest.raises(ValidationError):
        Settings(chunk_max_chars=300, chunk_min_chars=400)
    assert (Settings().chunk_max_chars, Settings().chunk_overlap_chars, Settings().chunk_min_chars) == (1200, 200, 50)


def test_document_with_only_short_pages_has_text_but_no_chunks(client):
    doc = ok(client, content=unique_pdf(["curto", "também curto"]))
    assert doc["status"] == "completed" and doc["has_text"] is True and doc["chunk_count"] == 0
    assert chunks_of(client, doc["id"]) == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_document_without_text_has_no_chunks(client):
    doc = ok(client, content=unique_pdf(["", ""]))
    assert doc["has_text"] is False and doc["chunk_count"] == 0


# --- endpoint de chunks -----------------------------------------------------------
def test_chunk_endpoint_paginates_and_filters_by_page(client):
    doc = ok(client, content=unique_pdf([long_text(), long_text(30)]))
    total = doc["chunk_count"]
    first = chunks_of(client, doc["id"], limit=3)
    assert first["total"] == total and len(first["items"]) == 3 and first["offset"] == 0
    rest = chunks_of(client, doc["id"], limit=200, offset=3)["items"]
    assert [c["chunk_index"] for c in first["items"] + rest] == list(range(total))
    page_two = chunks_of(client, doc["id"], page_number=2)
    assert page_two["total"] > 0 and {c["page_number"] for c in page_two["items"]} == {2}
    assert chunks_of(client, doc["id"], page_number=9)["items"] == []


def test_chunk_endpoint_errors(client):
    missing = uuid.uuid4()
    assert client.get(f"/api/documents/{missing}/chunks").json() == {"detail": "Documento não encontrado."}
    doc = ok(client)
    for bad in ("limit=0", "limit=201", "offset=-1", "page_number=0"):
        assert client.get(f"/api/documents/{doc['id']}/chunks?{bad}").status_code == 422
    assert client.get("/api/documents/not-a-uuid/chunks").status_code == 422


def test_chunk_count_appears_in_detail_and_listing(client):
    doc = ok(client)
    assert client.get(f"/api/documents/{doc['id']}").json()["chunk_count"] == doc["chunk_count"] > 0
    assert client.get("/api/documents").json()["items"][0]["chunk_count"] == doc["chunk_count"]


# --- falhas e consistência -----------------------------------------------------------
def test_chunking_failure_marks_document_failed_without_partial_data(client, storage_dir, db, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("falha na segmentação em /home/segredo")

    monkeypatch.setattr(documents_service.chunker, "chunk_pages", boom)
    doc = ok(client)
    assert doc["status"] == "failed" and doc["has_text"] is False and doc["chunk_count"] == 0
    assert "dividir o texto em trechos" in doc["error_message"] and "RuntimeError" in doc["error_message"]
    assert "/home/segredo" not in doc["error_message"]
    assert count(db, DocumentPage) == 0 and count(db, DocumentChunk) == 0  # tudo ou nada
    assert len(stored_files(storage_dir)) == 1  # original preservado
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200


def test_extraction_failure_still_leaves_no_pages_or_chunks(client, db, monkeypatch):
    monkeypatch.setattr(documents_service.pdf, "extract_text", lambda _r: (_ for _ in ()).throw(RuntimeError("x")))
    doc = ok(client)
    assert doc["status"] == "failed" and "extrair o texto" in doc["error_message"]
    assert count(db, DocumentPage) == 0 and count(db, DocumentChunk) == 0


def test_chunk_persistence_failure_leaves_a_failed_document_without_partial_data(client, storage_dir, db, monkeypatch):
    def bad_rows(document_id, specs):
        # página inexistente: a FK composta do banco recusa o chunk
        return [DocumentChunk(document_id=document_id, page_number=99, chunk_index=0, content="x", character_count=1, start_offset=0, end_offset=1)]

    monkeypatch.setattr(documents_service, "_chunk_rows", bad_rows)
    doc = ok(client)
    monkeypatch.undo()
    # O PDF já tinha sido aceito: o documento fica `failed`, sem páginas nem chunks (tudo ou nada),
    # com o original preservado e a falha registrada.
    assert doc["status"] == "failed" and doc["chunk_count"] == 0 and doc["has_text"] is False
    assert "gravar o resultado" in doc["error_message"] and "IntegrityError" in doc["error_message"]
    assert count(db, Document) == 1 and count(db, DocumentPage) == 0 and count(db, DocumentChunk) == 0
    assert len(stored_files(storage_dir)) == 1
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200


# --- reprocessamento ----------------------------------------------------------------------
def test_rebuild_is_idempotent_and_never_duplicates(client, db):
    doc = ok(client)
    document_id = uuid.UUID(doc["id"])
    before = [(c["chunk_index"], c["page_number"], c["content"]) for c in all_chunks(client, doc["id"])]
    for _ in range(3):
        assert documents_service.rebuild_chunks(db, get_settings(), document_id) == len(before)
    after = [(c["chunk_index"], c["page_number"], c["content"]) for c in all_chunks(client, doc["id"])]
    assert after == before and count(db, DocumentChunk) == len(before)


def test_rebuild_applies_new_configuration_without_leftovers(client, db, monkeypatch):
    doc = ok(client)
    old = doc["chunk_count"]
    monkeypatch.setenv("CHUNK_MAX_CHARS", "400")
    monkeypatch.setenv("CHUNK_OVERLAP_CHARS", "50")
    get_settings.cache_clear()
    new = documents_service.rebuild_chunks(db, get_settings(), uuid.UUID(doc["id"]))
    assert new > old and count(db, DocumentChunk) == new
    assert [c["chunk_index"] for c in all_chunks(client, doc["id"])] == list(range(new))


def test_failed_rebuild_keeps_the_previous_chunks(client, db, monkeypatch):
    doc = ok(client)
    monkeypatch.setattr(documents_service.chunker, "chunk_pages", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        documents_service.rebuild_chunks(db, get_settings(), uuid.UUID(doc["id"]))
    monkeypatch.undo()
    assert count(db, DocumentChunk) == doc["chunk_count"]


def test_rebuild_unknown_document(db):
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        documents_service.rebuild_chunks(db, get_settings(), uuid.uuid4())


def test_command_regenerates_missing_chunks_for_existing_documents(client, db, session_factory, capsys):
    legacy = ok(client)  # simula um documento anterior à segmentação: sem chunks
    healthy = ok(client)
    db.execute(text("DELETE FROM document_chunks WHERE document_id = :id"), {"id": legacy["id"].replace("-", "") if db.get_bind().dialect.name == "sqlite" else legacy["id"]})
    db.commit()
    assert documents_service.documents_without_chunks(db) == [uuid.UUID(legacy["id"])]
    assert client.get(f"/api/documents/{legacy['id']}").json()["chunk_count"] == 0

    assert cli.main(["rebuild-chunks", "--missing-only"], session_factory=session_factory) == 0
    assert "1 documento(s) processado(s)" in capsys.readouterr().out
    assert client.get(f"/api/documents/{legacy['id']}").json()["chunk_count"] == legacy["chunk_count"]
    assert client.get(f"/api/documents/{healthy['id']}").json()["chunk_count"] == healthy["chunk_count"]
    assert documents_service.documents_without_chunks(db) == []

    # repetir não duplica
    total = count(db, DocumentChunk)
    assert cli.main(["rebuild-chunks", "--all"], session_factory=session_factory) == 0
    assert cli.main(["rebuild-chunks", "--document-id", legacy["id"]], session_factory=session_factory) == 0
    assert count(db, DocumentChunk) == total


def test_command_requires_an_explicit_target_and_reports_failures(client, session_factory, capsys):
    with pytest.raises(SystemExit):
        cli.main(["rebuild-chunks"], session_factory=session_factory)
    assert cli.main(["rebuild-chunks", "--document-id", str(uuid.uuid4())], session_factory=session_factory) == 1
    assert "1 falha(s)" in capsys.readouterr().out


# --- exclusão e integridade -------------------------------------------------------------------
def test_deleting_a_document_removes_its_chunks_only(client, db):
    keep, gone = ok(client), ok(client)
    assert client.delete(f"/api/documents/{gone['id']}").status_code == 204
    remaining = db.scalars(select(DocumentChunk.document_id).distinct()).all()
    assert remaining == [uuid.UUID(keep["id"])]
    assert count(db, DocumentChunk) == keep["chunk_count"]


def test_deleting_a_page_removes_the_chunks_that_came_from_it(client, db):
    doc = ok(client, content=unique_pdf([long_text(), long_text(20)]))
    page_one = sum(1 for c in all_chunks(client, doc["id"]) if c["page_number"] == 1)
    db.execute(DocumentPage.__table__.delete().where(DocumentPage.page_number == 1))
    db.commit()
    assert count(db, DocumentChunk) == doc["chunk_count"] - page_one
    assert db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.page_number == 1)) == 0


def test_deleting_organization_items_keeps_chunks(client, db):
    tag = make(client, "/api/tags", name="t")
    doc = ok(client, tag_ids=[tag["id"]])
    client.delete(f"/api/tags/{tag['id']}")
    assert count(db, DocumentChunk) == doc["chunk_count"]


def _chunk(document_id, **overrides):
    values = dict(document_id=document_id, page_number=1, chunk_index=900, content="texto", character_count=5, start_offset=0, end_offset=5)
    values.update(overrides)
    return DocumentChunk(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"page_number": 99},  # página de origem inexistente (FK composta)
        {"chunk_index": 0},  # índice repetido no documento
        {"chunk_index": -1},
        {"page_number": 0},
        {"character_count": 4},  # contagem diferente do conteúdo
        {"content": "   ", "character_count": 3},  # conteúdo em branco
        {"start_offset": 5, "end_offset": 5, "character_count": 0, "content": "x"},
        {"start_offset": -1, "end_offset": 4, "character_count": 5},
    ],
    ids=["pagina-inexistente", "indice-duplicado", "indice-negativo", "pagina-zero", "contagem", "em-branco", "offsets", "offset-negativo"],
)
def test_database_rejects_inconsistent_chunks(client, db, overrides):
    doc = ok(client, content=unique_pdf([long_text()]))
    db.add(_chunk(uuid.UUID(doc["id"]), **overrides))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert count(db, DocumentChunk) == doc["chunk_count"]


def test_database_rejects_a_second_chunk_at_the_same_position(client, db):
    doc = ok(client, content=unique_pdf([long_text()]))
    first = db.scalars(select(DocumentChunk).where(DocumentChunk.chunk_index == 0)).one()
    db.add(_chunk(first.document_id, page_number=first.page_number, start_offset=first.start_offset, end_offset=first.start_offset + 5))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert count(db, DocumentChunk) == doc["chunk_count"]
