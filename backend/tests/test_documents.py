import hashlib
import io
import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import Document, DocumentPage, document_tags
from app.services import documents as documents_service
from app.services import storage as storage_module
from tests.conftest import make, stored_files
from tests.pdfs import CORRUPT_PDF, NOT_A_PDF, make_encrypted_pdf, make_pdf, unique_pdf


def upload(client, content=None, name="relatorio.pdf", content_type="application/pdf", **fields):
    content = unique_pdf(["Primeira página", "Segunda página"]) if content is None else content
    data = {k: v for k, v in fields.items() if v is not None}
    return client.post("/api/documents", files={"file": (name, content, content_type)}, data=data)


def ok(client, **kwargs):
    """Importa e devolve o documento no estado final (o despachante de teste é imediato)."""
    response = upload(client, **kwargs)
    assert response.status_code == 201, response.text
    return client.get(f"/api/documents/{response.json()['id']}").json()


# --- upload ---------------------------------------------------------------
def test_upload_valid_pdf(client, storage_dir):
    pdf = make_pdf(["Olá mundo", "Segunda página com texto"])
    doc = ok(client, content=pdf, name="Meu Relatório.pdf")

    assert doc["status"] == "completed" and doc["has_text"] is True and doc["error_message"] is None
    assert doc["page_count"] == 2
    assert doc["title"] == "Meu Relatório"
    assert doc["original_filename"] == "Meu Relatório.pdf"
    assert doc["size_bytes"] == len(pdf)
    assert doc["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert doc["content_type"] == "application/pdf"
    assert uuid.UUID(doc["id"]) and doc["created_at"] and doc["updated_at"]
    # a resposta não revela chave nem caminho de armazenamento
    assert "storage_key" not in doc and "path" not in doc
    assert str(storage_dir) not in str(doc)


def test_original_file_is_stored_unchanged_with_internal_name(client, storage_dir, db):
    pdf = make_pdf(["conteúdo"])
    doc = ok(client, content=pdf, name="../../etc/passwd.pdf")
    files = stored_files(storage_dir)
    assert len(files) == 1 and files[0].endswith(".pdf")
    key = db.scalar(select(Document.storage_key).where(Document.id == uuid.UUID(doc["id"])))
    assert files[0] == key and "passwd" not in key and ".." not in key
    assert (storage_dir / key).read_bytes() == pdf
    assert doc["original_filename"] == "passwd.pdf"  # diretórios descartados


def test_extracted_text_persisted_per_page(client, db):
    doc = ok(client, content=make_pdf(["Alfa bravo", "", "Charlie delta"]))
    pages = db.scalars(
        select(DocumentPage).where(DocumentPage.document_id == uuid.UUID(doc["id"])).order_by(DocumentPage.page_number)
    ).all()
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert [p.text for p in pages] == ["Alfa bravo", "", "Charlie delta"]


def test_custom_title_and_organization(client):
    cat = make(client, "/api/categories", name="Estudos")
    proj = make(client, "/api/projects", name="Tese")
    t1 = make(client, "/api/tags", name="a")
    t2 = make(client, "/api/tags", name="b")
    response = client.post(
        "/api/documents",
        files={"file": ("x.pdf", make_pdf(["texto"]), "application/pdf")},
        data={"title": "  Título próprio ", "category_id": cat["id"], "project_id": proj["id"], "tag_ids": [t1["id"], t2["id"]]},
    )
    assert response.status_code == 201, response.text
    doc = response.json()
    assert doc["title"] == "Título próprio"
    assert doc["category"]["name"] == "Estudos" and doc["project"]["name"] == "Tese"
    assert [t["name"] for t in doc["tags"]] == ["a", "b"]


def test_pdf_without_text_is_completed_not_failed(client):
    doc = ok(client, content=make_pdf(["", ""]))
    assert doc["status"] == "completed" and doc["has_text"] is False and doc["page_count"] == 2
    assert doc["error_message"] is None
    content = client.get(f"/api/documents/{doc['id']}/content").json()
    assert content["has_text"] is False and [p["text"] for p in content["pages"]] == ["", ""]


# --- rejeições ------------------------------------------------------------
def test_rejects_empty_file(client, storage_dir):
    response = upload(client, content=b"")
    assert response.status_code == 422 and "vazio" in response.json()["detail"]
    assert stored_files(storage_dir) == []


@pytest.mark.parametrize("content", [NOT_A_PDF, b"texto simples sem assinatura"])
def test_rejects_content_that_is_not_a_pdf_even_if_named_pdf(client, storage_dir, db, content):
    response = upload(client, content=content, name="inocente.pdf")
    assert response.status_code == 422 and "não é um PDF" in response.json()["detail"]
    assert stored_files(storage_dir) == []
    assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_rejects_corrupt_pdf(client, storage_dir, db):
    response = upload(client, content=CORRUPT_PDF)
    assert response.status_code == 422
    assert "corrompido" in response.json()["detail"]
    assert stored_files(storage_dir) == []  # nenhum temporário abandonado
    assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_rejects_password_protected_pdf(client, storage_dir):
    response = upload(client, content=make_encrypted_pdf())
    assert response.status_code == 422 and "senha" in response.json()["detail"]
    assert stored_files(storage_dir) == []


@pytest.mark.parametrize(
    "name,content_type",
    [
        ("programa.exe", "application/x-msdownload"),
        ("imagem.png", "image/png"),
        ("texto.txt", "text/plain"),
        ("documento.pdf.exe", "application/pdf"),  # extensão final decide
        ("semextensao", "application/pdf"),
        ("relatorio.pdf", "text/plain"),  # extensão ok, tipo declarado errado
        ("relatorio.pdf", "application/octet-stream"),
    ],
)
def test_rejects_unsupported_formats(client, storage_dir, name, content_type):
    response = upload(client, name=name, content_type=content_type)
    assert response.status_code == 415, response.text
    assert stored_files(storage_dir) == []


def test_extension_is_case_insensitive(client):
    assert upload(client, name="MAIUSCULO.PDF").status_code == 201


def test_rejects_file_over_limit_and_leaves_no_residue(client, storage_dir, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    big = b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10)
    response = upload(client, content=big)
    assert response.status_code == 413
    assert "limite de 1 MB" in response.json()["detail"]
    assert stored_files(storage_dir) == []


def test_limit_is_checked_before_body_when_content_length_is_declared(client, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    response = client.post(
        "/api/documents", content=b"x", headers={"content-length": str(5 * 1024 * 1024), "content-type": "multipart/form-data; boundary=x"}
    )
    assert response.status_code == 413


def test_rejects_pdf_with_too_many_pages(client, storage_dir, monkeypatch):
    monkeypatch.setenv("MAX_DOCUMENT_PAGES", "2")
    get_settings.cache_clear()
    response = upload(client, content=make_pdf(["a", "b", "c"]))
    assert response.status_code == 422 and "limite é 2" in response.json()["detail"]
    assert stored_files(storage_dir) == []


def test_rejects_invalid_references_without_storing(client, storage_dir):
    missing = str(uuid.uuid4())
    for field in ("category_id", "project_id"):
        assert upload(client, **{field: missing}).status_code == 422
    assert upload(client, tag_ids=[missing]).status_code == 422
    assert stored_files(storage_dir) == []


def test_missing_file_field_is_422(client):
    assert client.post("/api/documents", data={"title": "x"}).status_code == 422


def test_limits_endpoint(client):
    body = client.get("/api/documents/limits").json()
    assert body == {"max_upload_bytes": 20 * 1024 * 1024, "max_pages": 500}


# --- falhas durante o processamento --------------------------------------
def test_extraction_failure_keeps_a_failed_document_with_diagnosis(client, storage_dir, monkeypatch):
    def boom(_reader):
        raise RuntimeError("página quebrada em /home/secreto/arquivo")

    monkeypatch.setattr(documents_service.pdf, "extract_text", boom)
    doc = ok(client)
    assert doc["status"] == "failed" and doc["has_text"] is False
    assert "RuntimeError" in doc["error_message"]
    assert "/home/secreto" not in doc["error_message"]  # sem vazar detalhes internos
    assert doc["page_count"] == 2
    assert len(stored_files(storage_dir)) == 1  # original preservado para reprocessamento futuro
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200


def test_database_failure_during_upload_leaves_no_file_or_record(client, storage_dir, db, monkeypatch):
    from sqlalchemy.orm import Session

    original_commit = Session.commit

    def failing_commit(self):
        if any(isinstance(obj, Document) for obj in self.identity_map.values()):  # já enviado via flush
            raise RuntimeError("banco indisponível")
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        upload(client)
    monkeypatch.undo()
    assert stored_files(storage_dir) == []  # nem definitivo nem temporário
    assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_storage_failure_when_placing_file_leaves_no_record(client, storage_dir, db, monkeypatch):
    def fail(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(storage_module.os, "link", fail)
    response = upload(client)
    assert response.status_code == 500
    assert response.json() == {"detail": "Falha ao acessar o armazenamento de arquivos."}  # sem caminhos
    assert stored_files(storage_dir) == []
    assert db.scalar(select(func.count()).select_from(Document)) == 0


# --- consulta -------------------------------------------------------------
def test_get_and_list_documents(client, db):
    from datetime import datetime, timedelta, timezone

    a = ok(client, name="alfa.pdf")
    b = ok(client, name="beta.pdf")
    # SQLite só tem resolução de segundos: fixa datas distintas para a ordenação ser determinística.
    db.query(Document).filter(Document.id == uuid.UUID(a["id"])).update(
        {"created_at": datetime.now(timezone.utc) - timedelta(days=1)}
    )
    db.commit()
    assert client.get(f"/api/documents/{a['id']}").json()["id"] == a["id"]
    page = client.get("/api/documents").json()
    assert page["total"] == 2 and page["limit"] == 20 and page["offset"] == 0
    assert [d["id"] for d in page["items"]] == [b["id"], a["id"]]  # mais recente primeiro
    assert client.get("/api/documents?order=asc").json()["items"][0]["id"] == a["id"]
    assert client.get("/api/documents?sort=updated_at").status_code == 200
    assert client.get("/api/documents?sort=title").status_code == 422


def test_list_filters_and_pagination(client):
    cat = make(client, "/api/categories", name="C")
    proj = make(client, "/api/projects", name="P")
    tag = make(client, "/api/tags", name="t")
    ok(client, name="contrato_cliente.pdf", category_id=cat["id"], tag_ids=[tag["id"]])
    ok(client, name="fatura.pdf", project_id=proj["id"])
    ok(client, name="avulso.pdf")

    names = lambda url: {d["original_filename"] for d in client.get(url).json()["items"]}  # noqa: E731
    assert names("/api/documents?q=contrato") == {"contrato_cliente.pdf"}
    assert names("/api/documents?q=CLIENTE") == {"contrato_cliente.pdf"}  # sem diferenciar caixa
    assert names(f"/api/documents?category_id={cat['id']}") == {"contrato_cliente.pdf"}
    assert names(f"/api/documents?project_id={proj['id']}") == {"fatura.pdf"}
    assert names(f"/api/documents?tag_id={tag['id']}") == {"contrato_cliente.pdf"}
    assert names(f"/api/documents?q=fatura&category_id={cat['id']}") == set()
    assert client.get("/api/documents?q=zzz").json() == {"items": [], "total": 0, "limit": 20, "offset": 0}

    first = client.get("/api/documents?limit=2&offset=0").json()
    last = client.get("/api/documents?limit=2&offset=2").json()
    assert first["total"] == 3 and len(first["items"]) == 2 and len(last["items"]) == 1
    assert client.get("/api/documents?limit=0").status_code == 422


def test_name_search_treats_wildcards_literally(client):
    ok(client, name="relatorio_final.pdf")
    ok(client, name="relatorioXfinal.pdf")
    assert client.get("/api/documents?q=o_f").json()["total"] == 1
    assert client.get("/api/documents?q=%25").json()["total"] == 0


def test_content_endpoint_returns_pages_in_order(client):
    doc = ok(client, content=make_pdf(["um", "dois", "três"]))
    body = client.get(f"/api/documents/{doc['id']}/content").json()
    assert body["page_count"] == 3 and body["status"] == "completed" and body["has_text"] is True
    assert body["pages"] == [
        {"page_number": 1, "text": "um"},
        {"page_number": 2, "text": "dois"},
        {"page_number": 3, "text": "três"},
    ]


def test_download_original(client):
    pdf = make_pdf(["conteúdo do original"])
    doc = ok(client, content=pdf, name="Relatório Final.pdf")
    response = client.get(f"/api/documents/{doc['id']}/file")
    assert response.status_code == 200
    assert response.content == pdf
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment") and "Relat" in disposition
    assert response.headers["x-content-type-options"] == "nosniff"


def test_download_filename_cannot_inject_headers(client):
    doc = ok(client, name='a"b\r\nX-Evil: 1.pdf')
    disposition = client.get(f"/api/documents/{doc['id']}/file").headers["content-disposition"]
    assert "\r" not in disposition and "\n" not in disposition


def test_unknown_document_is_404_everywhere(client):
    missing = uuid.uuid4()
    for suffix in ("", "/content", "/file"):
        response = client.get(f"/api/documents/{missing}{suffix}")
        assert response.status_code == 404 and response.json() == {"detail": "Documento não encontrado."}
    assert client.delete(f"/api/documents/{missing}").status_code == 404
    assert client.patch(f"/api/documents/{missing}", json={"title": "x"}).status_code == 404
    assert client.get("/api/documents/not-a-uuid").status_code == 422


def test_download_with_missing_file_reports_inconsistency(client, storage_dir):
    doc = ok(client)
    for f in storage_dir.glob("*.pdf"):
        f.unlink()
    response = client.get(f"/api/documents/{doc['id']}/file")
    assert response.status_code == 404
    assert "não foi encontrado" in response.json()["detail"] and str(storage_dir) not in response.text
    assert client.get(f"/api/documents/{doc['id']}").status_code == 200  # metadados seguem acessíveis


def test_corrupted_storage_key_never_reaches_filesystem(client, db):
    doc = ok(client)
    db.query(Document).update({"storage_key": "../../../etc/passwd"})
    db.commit()
    response = client.get(f"/api/documents/{doc['id']}/file")
    assert response.status_code == 500 and "etc" not in response.text


# --- edição e relacionamentos --------------------------------------------
def test_patch_preserves_relationships_when_omitted(client):
    cat = make(client, "/api/categories", name="C")
    proj = make(client, "/api/projects", name="P")
    tag = make(client, "/api/tags", name="t")
    doc = ok(client, category_id=cat["id"], project_id=proj["id"], tag_ids=[tag["id"]])
    url = f"/api/documents/{doc['id']}"

    body = client.patch(url, json={"title": "Novo título"}).json()
    assert body["title"] == "Novo título"
    assert body["category"]["id"] == cat["id"] and body["project"]["id"] == proj["id"]
    assert [t["id"] for t in body["tags"]] == [tag["id"]]

    body = client.patch(url, json={"category_id": None, "tag_ids": []}).json()
    assert body["category"] is None and body["tags"] == [] and body["project"]["id"] == proj["id"]
    assert client.patch(url, json={"title": "  "}).status_code == 422
    assert client.patch(url, json={"category_id": str(uuid.uuid4())}).status_code == 422


def test_deleting_organization_items_preserves_documents(client):
    cat = make(client, "/api/categories", name="C")
    proj = make(client, "/api/projects", name="P")
    tag = make(client, "/api/tags", name="t")
    doc = ok(client, category_id=cat["id"], project_id=proj["id"], tag_ids=[tag["id"]])
    assert client.get(f"/api/categories/{cat['id']}").json()["documents_count"] == 1
    assert client.get(f"/api/tags/{tag['id']}").json()["documents_count"] == 1
    for resource, item in (("categories", cat), ("projects", proj), ("tags", tag)):
        assert client.delete(f"/api/{resource}/{item['id']}").status_code == 204
    body = client.get(f"/api/documents/{doc['id']}").json()
    assert body["category"] is None and body["project"] is None and body["tags"] == []


# --- exclusão -------------------------------------------------------------
def test_delete_removes_record_pages_associations_and_file(client, storage_dir, db):
    tag = make(client, "/api/tags", name="t")
    doc = ok(client, tag_ids=[tag["id"]])
    assert len(stored_files(storage_dir)) == 1
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204

    assert client.get(f"/api/documents/{doc['id']}").status_code == 404
    assert stored_files(storage_dir) == []  # sem arquivo, sem `.deleting`, sem temporários
    assert db.scalar(select(func.count()).select_from(Document)) == 0
    assert db.scalar(select(func.count()).select_from(DocumentPage)) == 0
    assert db.scalar(select(func.count()).select_from(document_tags)) == 0
    assert client.get(f"/api/tags/{tag['id']}").status_code == 200  # etiqueta preservada


def test_delete_does_not_touch_other_documents(client, storage_dir):
    keep = ok(client, content=make_pdf(["fica"]))
    gone = ok(client, content=make_pdf(["sai"]))
    client.delete(f"/api/documents/{gone['id']}")
    assert len(stored_files(storage_dir)) == 1
    assert client.get(f"/api/documents/{keep['id']}/file").status_code == 200


def test_delete_with_missing_file_still_removes_record(client, storage_dir, db):
    doc = ok(client)
    for f in storage_dir.glob("*.pdf"):
        f.unlink()
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_delete_fails_loudly_when_file_cannot_be_removed(client, storage_dir, db, monkeypatch):
    doc = ok(client)

    def deny(*_a, **_k):
        raise PermissionError("sem permissão")

    monkeypatch.setattr(storage_module.os, "replace", deny)
    response = client.delete(f"/api/documents/{doc['id']}")
    assert response.status_code == 500
    assert response.json() == {"detail": "Não foi possível remover o arquivo do documento."}
    monkeypatch.undo()
    # nada mudou: registro e arquivo continuam, e o download funciona
    assert db.scalar(select(func.count()).select_from(Document)) == 1
    assert len(stored_files(storage_dir)) == 1
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200


def test_delete_restores_file_when_database_commit_fails(client, storage_dir, db, monkeypatch):
    from sqlalchemy.orm import Session

    doc = ok(client)
    original_commit = Session.commit

    def failing_commit(self):
        if self.deleted:
            raise RuntimeError("banco indisponível")
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        client.delete(f"/api/documents/{doc['id']}")
    monkeypatch.undo()
    assert db.scalar(select(func.count()).select_from(Document)) == 1
    assert [f for f in stored_files(storage_dir) if f.endswith(".pdf")] and not [
        f for f in stored_files(storage_dir) if f.endswith(".deleting")
    ]
    assert client.get(f"/api/documents/{doc['id']}/file").status_code == 200


def test_storage_rejects_unsafe_keys():
    from pathlib import Path

    from app.core.errors import StorageError

    store = storage_module.LocalStorage(Path("/tmp/storage-test-root"))
    for bad in ["../x.pdf", "a/b.pdf", "/etc/passwd", "x.pdf", "A" * 32 + ".pdf", ""]:
        with pytest.raises(StorageError):
            store.path_for(bad)


def test_staging_stream_reads_in_chunks_and_cleans_up(tmp_path):
    store = storage_module.LocalStorage(tmp_path / "s")
    with store.stage(io.BytesIO(make_pdf(["x"])), 10_000_000) as staged:
        assert staged.path.exists()
        key = staged.commit()
    assert not staged.path.exists() and (tmp_path / "s" / key).exists()


def test_document_listing_has_no_n_plus_one(client, session_factory):
    from sqlalchemy import event

    cat = make(client, "/api/categories", name="C")
    tags = [make(client, "/api/tags", name=f"t{i}")["id"] for i in range(3)]

    def count(url):
        engine = session_factory().get_bind()
        seen: list[str] = []
        listener = lambda _c, _cur, statement, *_a: seen.append(statement)  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            assert client.get(url).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(seen)

    for _ in range(2):
        ok(client, category_id=cat["id"], tag_ids=tags)
    few = (count("/api/documents"), count("/api/search?type=document"))
    for _ in range(10):
        ok(client, category_id=cat["id"], tag_ids=tags)
    assert (count("/api/documents"), count("/api/search?type=document")) == few
