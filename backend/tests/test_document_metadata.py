import uuid

import pytest

from tests.conftest import make, requires_postgres
from tests.docs_helpers import all_chunks, long_text, ok
from tests.pdfs import unique_pdf


def patch(client, doc_id, **body):
    return client.patch(f"/api/documents/{doc_id}", json=body)


@pytest.fixture()
def org(client):
    return {
        "cat": make(client, "/api/categories", name="Jurídico"),
        "cat2": make(client, "/api/categories", name="Estudos"),
        "proj": make(client, "/api/projects", name="Fusão"),
        "t1": make(client, "/api/tags", name="urgente"),
        "t2": make(client, "/api/tags", name="revisar"),
    }


def test_edit_title_category_project_and_tags(client, org):
    doc = ok(client)
    response = patch(client, doc["id"], title="  Novo título  ", category_id=org["cat"]["id"], project_id=org["proj"]["id"], tag_ids=[org["t1"]["id"], org["t2"]["id"]])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Novo título"
    assert body["category"]["id"] == org["cat"]["id"] and body["project"]["id"] == org["proj"]["id"]
    assert sorted(t["name"] for t in body["tags"]) == ["revisar", "urgente"]
    assert body["updated_at"] >= doc["updated_at"]
    assert client.get(f"/api/documents/{doc['id']}").json()["title"] == "Novo título"
    assert client.get("/api/documents").json()["items"][0]["title"] == "Novo título"


def test_omitted_fields_are_preserved(client, org):
    doc = ok(client, category_id=org["cat"]["id"], project_id=org["proj"]["id"], tag_ids=[org["t1"]["id"]], title="Original")
    body = patch(client, doc["id"], title="Só o título muda").json()
    assert body["category"]["id"] == org["cat"]["id"] and body["project"]["id"] == org["proj"]["id"]
    assert [t["id"] for t in body["tags"]] == [org["t1"]["id"]]
    body = patch(client, doc["id"], category_id=org["cat2"]["id"]).json()
    assert body["title"] == "Só o título muda" and body["project"]["id"] == org["proj"]["id"] and len(body["tags"]) == 1


def test_category_and_project_can_be_cleared(client, org):
    doc = ok(client, category_id=org["cat"]["id"], project_id=org["proj"]["id"])
    body = patch(client, doc["id"], category_id=None).json()
    assert body["category"] is None and body["project"]["id"] == org["proj"]["id"]
    body = patch(client, doc["id"], project_id=None).json()
    assert body["category"] is None and body["project"] is None
    assert client.get(f"/api/documents?category_id={org['cat']['id']}").json()["total"] == 0


def test_tags_are_replaced_cleared_and_deduplicated(client, org):
    doc = ok(client, tag_ids=[org["t1"]["id"]])
    body = patch(client, doc["id"], tag_ids=[org["t2"]["id"], org["t2"]["id"]]).json()
    assert [t["id"] for t in body["tags"]] == [org["t2"]["id"]]  # trocou e não duplicou
    assert client.get(f"/api/documents?tag_id={org['t1']['id']}").json()["total"] == 0
    assert client.get(f"/api/documents?tag_id={org['t2']['id']}").json()["total"] == 1
    assert patch(client, doc["id"], tag_ids=[]).json()["tags"] == []


def test_unknown_ids_are_rejected_and_change_nothing(client, org):
    doc = ok(client, category_id=org["cat"]["id"], title="Intacto")
    missing = str(uuid.uuid4())
    for body in ({"category_id": missing}, {"project_id": missing}, {"tag_ids": [missing]}, {"tag_ids": [org["t1"]["id"], missing]}):
        assert patch(client, doc["id"], title="Mudou?", **body).status_code == 422
    after = client.get(f"/api/documents/{doc['id']}").json()
    assert after["title"] == "Intacto" and after["category"]["id"] == org["cat"]["id"] and after["tags"] == []


@pytest.mark.parametrize("field,value", [
    ("id", str(uuid.uuid4())), ("storage_key", "x" * 32 + ".pdf"), ("sha256", "0" * 64), ("original_filename", "outro.pdf"),
    ("status", "failed"), ("page_count", 99), ("chunk_count", 99), ("content_type", "text/plain"), ("size_bytes", 1),
])
def test_identity_and_file_fields_cannot_be_changed(client, field, value):
    doc = ok(client)
    assert patch(client, doc["id"], **{field: value}).status_code == 422
    after = client.get(f"/api/documents/{doc['id']}").json()
    assert after["id"] == doc["id"] and after["sha256"] == doc["sha256"] and after["original_filename"] == doc["original_filename"]


def test_invalid_titles_are_rejected(client):
    doc = ok(client, title="Bom")
    assert patch(client, doc["id"], title="   ").status_code == 422
    assert patch(client, doc["id"], title="").status_code == 422
    assert patch(client, doc["id"], title="x" * 256).status_code == 422
    assert client.get(f"/api/documents/{doc['id']}").json()["title"] == "Bom"


def test_unknown_document_is_404(client):
    assert patch(client, uuid.uuid4(), title="x").json() == {"detail": "Documento não encontrado."}


def test_editing_keeps_file_text_pages_and_chunks(client, org):
    pdf = unique_pdf([long_text(), "Segunda página com conteúdo útil o bastante."])
    doc = ok(client, content=pdf)
    content_before = client.get(f"/api/documents/{doc['id']}/content").json()["pages"]
    chunks_before = all_chunks(client, doc["id"])

    body = patch(client, doc["id"], title="Outro", category_id=org["cat"]["id"], tag_ids=[org["t1"]["id"]]).json()

    assert body["chunk_count"] == doc["chunk_count"] and body["page_count"] == doc["page_count"]
    assert body["status"] == "completed" and body["has_text"] is True and body["sha256"] == doc["sha256"]
    assert client.get(f"/api/documents/{doc['id']}/content").json()["pages"] == content_before
    assert all_chunks(client, doc["id"]) == chunks_before  # mesmos ids, ordem e conteúdo
    assert client.get(f"/api/documents/{doc['id']}/file").content == pdf


def test_organization_rules_still_apply_to_the_items_used(client, org):
    # a unicidade de nomes continua valendo: não dá para criar categoria repetida para usá-la no documento
    assert client.post("/api/categories", json={"name": "jurídico"}).status_code == 409


@requires_postgres
def test_search_reflects_edits(client, org):
    doc = ok(client, content=unique_pdf([long_text()]), title="Contrato antigo", tag_ids=[org["t1"]["id"]])

    def found(q):
        return [i["id"] for i in client.get("/api/search", params={"q": q, "type": "document"}).json()["items"]]

    assert found("antigo") == [doc["id"]] and found("urgente") == [doc["id"]]
    patch(client, doc["id"], title="Contrato revisado", tag_ids=[org["t2"]["id"]], category_id=org["cat"]["id"], project_id=org["proj"]["id"])
    assert found("antigo") == [] and found("urgente") == []
    assert found("revisado") == [doc["id"]] and found("revisar") == [doc["id"]]
    assert found("jurídico") == [doc["id"]] and found("fusão") == [doc["id"]]
    assert found("segmentação") == [doc["id"]]  # o texto extraído continua pesquisável
    patch(client, doc["id"], category_id=None)
    assert found("jurídico") == []
