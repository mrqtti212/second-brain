"""Busca unificada de notas e documentos. Testes com termo exigem PostgreSQL."""

import uuid

from tests.conftest import make, requires_postgres
from tests.pdfs import unique_pdf


def doc(client, pages=("texto",), name="arquivo.pdf", **fields):
    data = {k: v for k, v in fields.items() if v is not None}
    response = client.post(
        "/api/documents", files={"file": (name, unique_pdf(list(pages)), "application/pdf")}, data=data
    )
    assert response.status_code == 201, response.text
    return client.get(f"/api/documents/{response.json()['id']}").json()  # estado final


def note(client, title, content="", **extra):
    return make(client, "/api/notes", title=title, content=content, **extra)


def search(client, **params):
    response = client.get("/api/search", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def keys(page):
    return [(i["type"], i["title"]) for i in page["items"]]


# --- sem termo: funciona em qualquer banco -------------------------------
def test_listing_mixes_notes_and_documents_and_filters_by_type(client):
    note(client, "Uma nota")
    doc(client, name="contrato.pdf")
    page = search(client)
    assert page["total"] == 2 and {i["type"] for i in page["items"]} == {"note", "document"}
    assert keys(search(client, type="note")) == [("note", "Uma nota")]
    assert keys(search(client, type="document")) == [("document", "contrato")]
    assert client.get("/api/search?type=video").status_code == 422


def test_document_result_shape_and_first_page_snippet(client):
    cat = make(client, "/api/categories", name="C")
    tag = make(client, "/api/tags", name="t")
    created = doc(client, pages=("Primeira página do contrato", "outra"), name="c.pdf", category_id=cat["id"], tag_ids=[tag["id"]])
    item = search(client, type="document")["items"][0]
    assert item["id"] == created["id"] and item["type"] == "document"
    assert item["status"] == "completed" and item["page_count"] == 2 and item["has_text"] is True
    assert item["category"]["name"] == "C" and [t["name"] for t in item["tags"]] == ["t"]
    assert item["snippet"] == "Primeira página do contrato" and item["score"] is None


def test_filters_apply_to_documents_without_duplicates(client):
    cat = make(client, "/api/categories", name="C")
    proj = make(client, "/api/projects", name="P")
    t1 = make(client, "/api/tags", name="t1")
    t2 = make(client, "/api/tags", name="t2")
    doc(client, name="a.pdf", category_id=cat["id"], project_id=proj["id"], tag_ids=[t1["id"], t2["id"]])
    doc(client, name="b.pdf", category_id=cat["id"])
    note(client, "n", category_id=cat["id"], tag_ids=[t1["id"]])

    assert search(client, category_id=cat["id"])["total"] == 3
    assert keys(search(client, project_id=proj["id"])) == [("document", "a")]
    assert search(client, tag_id=t1["id"])["total"] == 2  # documento a + nota n
    both = search(client, tag_id=[t1["id"], t2["id"]])
    assert keys(both) == [("document", "a")] and both["total"] == 1  # sem duplicatas
    assert search(client, category_id=str(uuid.uuid4()))["items"] == []


def test_pagination_spans_notes_and_documents(client):
    for i in range(3):
        note(client, f"nota {i}")
        doc(client, name=f"doc{i}.pdf")
    first = search(client, limit=4, offset=0)
    second = search(client, limit=4, offset=4)
    assert first["total"] == 6 and len(first["items"]) == 4 and len(second["items"]) == 2
    ids = [i["id"] for i in first["items"] + second["items"]]
    assert len(set(ids)) == 6


# --- com termo: PostgreSQL ------------------------------------------------
@requires_postgres
def test_finds_document_by_title_and_filename(client):
    doc(client, pages=("nada relevante",), name="Plano_Estratégico_2026.pdf", title="Plano de expansão")
    doc(client, pages=("outro assunto",), name="outro.pdf")
    assert keys(search(client, q="expansão")) == [("document", "Plano de expansão")]
    assert keys(search(client, q="estratégico")) == [("document", "Plano de expansão")]  # nome do arquivo (peso B)


@requires_postgres
def test_finds_document_by_extracted_text_with_highlight(client):
    doc(client, pages=("Introdução geral", "A cláusula de rescisão prevê multa."), name="contrato.pdf")
    doc(client, pages=("nada a ver",), name="x.pdf")
    page = search(client, q="rescisão")
    assert keys(page) == [("document", "contrato")]
    assert "rescisão" in page["items"][0]["snippet"]
    assert page["items"][0]["score"] > 0


@requires_postgres
def test_text_search_uses_portuguese_stemming_for_documents(client):
    doc(client, pages=("Os contratos assinados",), name="a.pdf")
    assert keys(search(client, q="contrato")) == [("document", "a")]


@requires_postgres
def test_combined_results_are_ranked_together_and_filterable_by_type(client):
    note(client, "Resumo", "fala de blockchain no meio do texto")
    doc(client, pages=("conteúdo",), name="blockchain.pdf", title="Blockchain")
    page = search(client, q="blockchain")
    assert {i["type"] for i in page["items"]} == {"note", "document"}
    assert page["items"][0]["type"] == "document"  # título (peso A) vence conteúdo (peso C)
    assert keys(search(client, q="blockchain", type="note")) == [("note", "Resumo")]
    assert keys(search(client, q="blockchain", type="document")) == [("document", "Blockchain")]


@requires_postgres
def test_finds_document_by_category_project_and_tag_names(client):
    cat = make(client, "/api/categories", name="Jurídico")
    proj = make(client, "/api/projects", name="Fusão")
    tag = make(client, "/api/tags", name="urgente")
    doc(client, name="a.pdf", category_id=cat["id"])
    doc(client, name="b.pdf", project_id=proj["id"])
    doc(client, name="c.pdf", tag_ids=[tag["id"]])
    doc(client, name="d.pdf")
    assert keys(search(client, q="jurídico")) == [("document", "a")]
    assert keys(search(client, q="fusão")) == [("document", "b")]
    assert keys(search(client, q="urgente")) == [("document", "c")]


@requires_postgres
def test_query_with_filters_and_pagination_for_documents(client):
    cat = make(client, "/api/categories", name="C")
    for i in range(5):
        doc(client, pages=("relatório mensal",), name=f"r{i}.pdf", category_id=cat["id"] if i < 3 else None)
    assert search(client, q="relatório")["total"] == 5
    filtered = search(client, q="relatório", category_id=cat["id"], limit=2)
    assert filtered["total"] == 3 and len(filtered["items"]) == 2
    assert len(search(client, q="relatório", category_id=cat["id"], limit=2, offset=2)["items"]) == 1


@requires_postgres
def test_empty_results_and_odd_input_with_documents(client):
    doc(client)
    assert search(client, q="inexistente")["items"] == []
    for odd in ('"aberta', "a & | !", "'; DROP TABLE documents; --", "\\", "%_"):
        assert client.get("/api/search", params={"q": odd}).status_code == 200, odd
    assert search(client, type="document")["total"] == 1


@requires_postgres
def test_failed_and_textless_documents_are_still_found_by_name(client, monkeypatch):
    from app.services import documents as svc

    doc(client, pages=("",), name="escaneado_contrato.pdf")  # sem texto
    monkeypatch.setattr(svc.pdf, "extract_text", lambda _r: (_ for _ in ()).throw(RuntimeError("x")))
    failed = doc(client, name="quebrado_relatorio.pdf")
    monkeypatch.undo()
    assert failed["status"] == "failed"
    assert keys(search(client, q="escaneado")) == [("document", "escaneado_contrato")]
    assert keys(search(client, q="quebrado")) == [("document", "quebrado_relatorio")]


@requires_postgres
def test_index_follows_document_changes(client):
    tag = make(client, "/api/tags", name="alfa")
    d = doc(client, pages=("conteúdo qualquer",), name="x.pdf", tag_ids=[tag["id"]])
    assert keys(search(client, q="alfa")) == [("document", "x")]

    client.patch(f"/api/tags/{tag['id']}", json={"name": "bravo"})  # renomear etiqueta
    assert search(client, q="alfa")["items"] == [] and keys(search(client, q="bravo")) == [("document", "x")]

    client.patch(f"/api/documents/{d['id']}", json={"title": "Zeta final"})
    assert keys(search(client, q="zeta")) == [("document", "Zeta final")]
    assert keys(search(client, q="bravo")) == [("document", "Zeta final")]  # etiqueta preservada

    client.delete(f"/api/tags/{tag['id']}")  # excluir etiqueta tira do índice, mantém o documento
    assert search(client, q="bravo")["items"] == [] and keys(search(client, q="zeta")) == [("document", "Zeta final")]

    client.delete(f"/api/documents/{d['id']}")
    assert search(client, q="zeta")["items"] == []


@requires_postgres
def test_large_document_text_does_not_break_indexing(client):
    # ~420 mil caracteres distintos: acima do trecho indexado, abaixo do limite do upload.
    pages = [" ".join(f"termo{p}x{i}" for i in range(1800)) for p in range(20)]
    d = doc(client, pages=pages, name="grande.pdf")
    assert d["status"] == "completed" and d["page_count"] == 20
    assert keys(search(client, q="termo0x5")) == [("document", "grande")]


@requires_postgres
def test_documents_use_gin_index(session_factory):
    from sqlalchemy import text

    with session_factory() as db:
        defs = db.execute(text("SELECT indexdef FROM pg_indexes WHERE tablename='documents'")).scalars().all()
    assert any("USING gin (search_vector)" in d for d in defs)
