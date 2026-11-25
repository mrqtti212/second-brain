import uuid

from tests.conftest import make


def create(client, title="Minha nota", content="Conteúdo", **extra):
    return make(client, "/api/notes", title=title, content=content, **extra)


def test_create_and_get_note(client):
    note = create(client)
    assert uuid.UUID(note["id"])
    assert note["title"] == "Minha nota"
    assert note["created_at"] and note["updated_at"]
    assert note["category"] is None and note["project"] is None and note["tags"] == []

    response = client.get(f"/api/notes/{note['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == note["id"]


def test_create_without_content_defaults_to_empty(client):
    response = client.post("/api/notes", json={"title": "Só título"})
    assert response.status_code == 201
    assert response.json()["content"] == ""


def test_create_with_relationships(client):
    cat = make(client, "/api/categories", name="Estudos")
    proj = make(client, "/api/projects", name="Tese")
    tag = make(client, "/api/tags", name="python")
    note = create(client, category_id=cat["id"], project_id=proj["id"], tag_ids=[tag["id"]])
    assert note["category"]["name"] == "Estudos"
    assert note["project"]["name"] == "Tese"
    assert [t["name"] for t in note["tags"]] == ["python"]


def test_list_notes_includes_relationships(client):
    tag = make(client, "/api/tags", name="a")
    create(client, "A", tag_ids=[tag["id"]])
    create(client, "B")
    body = client.get("/api/notes").json()
    assert {n["title"] for n in body} == {"A", "B"}
    assert [t["name"] for n in body if n["title"] == "A" for t in n["tags"]] == ["a"]


def test_list_pagination_validation(client):
    assert client.get("/api/notes?limit=0").status_code == 422
    assert client.get("/api/notes?offset=-1").status_code == 422


def test_update_title_and_content(client):
    note = create(client, "Antes", "Texto")
    response = client.patch(f"/api/notes/{note['id']}", json={"title": "Depois", "content": "Novo"})
    assert response.status_code == 200
    body = response.json()
    assert (body["title"], body["content"]) == ("Depois", "Novo")
    assert body["updated_at"] >= note["updated_at"]


def test_partial_update_preserves_relationships(client):
    cat = make(client, "/api/categories", name="Estudos")
    proj = make(client, "/api/projects", name="Tese")
    tag = make(client, "/api/tags", name="python")
    note = create(client, category_id=cat["id"], project_id=proj["id"], tag_ids=[tag["id"]])

    body = client.patch(f"/api/notes/{note['id']}", json={"title": "Novo título"}).json()
    assert body["title"] == "Novo título"
    assert body["category"]["id"] == cat["id"]
    assert body["project"]["id"] == proj["id"]
    assert [t["id"] for t in body["tags"]] == [tag["id"]]

    body = client.patch(f"/api/notes/{note['id']}", json={"content": "x"}).json()
    assert body["category"] and body["project"] and body["tags"]


def test_patch_changes_and_clears_relationships(client):
    cat = make(client, "/api/categories", name="A")
    cat2 = make(client, "/api/categories", name="B")
    tag1 = make(client, "/api/tags", name="t1")
    tag2 = make(client, "/api/tags", name="t2")
    note = create(client, category_id=cat["id"], tag_ids=[tag1["id"]])
    url = f"/api/notes/{note['id']}"

    body = client.patch(url, json={"category_id": cat2["id"], "tag_ids": [tag2["id"]]}).json()
    assert body["category"]["id"] == cat2["id"]
    assert [t["id"] for t in body["tags"]] == [tag2["id"]]

    body = client.patch(url, json={"category_id": None, "tag_ids": []}).json()
    assert body["category"] is None and body["tags"] == []


def test_invalid_references_are_rejected(client):
    missing = str(uuid.uuid4())
    assert client.post("/api/notes", json={"title": "x", "category_id": missing}).status_code == 422
    assert client.post("/api/notes", json={"title": "x", "project_id": missing}).status_code == 422
    assert client.post("/api/notes", json={"title": "x", "tag_ids": [missing]}).status_code == 422
    note = create(client)
    assert client.patch(f"/api/notes/{note['id']}", json={"category_id": missing}).status_code == 422
    # nada foi alterado pela tentativa inválida
    assert client.get(f"/api/notes/{note['id']}").json()["category"] is None


def test_duplicate_tag_ids_are_collapsed(client):
    tag = make(client, "/api/tags", name="dup")
    note = create(client, tag_ids=[tag["id"], tag["id"]])
    assert len(note["tags"]) == 1


def test_update_rejects_blank_title(client):
    note = create(client)
    assert client.patch(f"/api/notes/{note['id']}", json={"title": "   "}).status_code == 422
    assert client.patch(f"/api/notes/{note['id']}", json={"title": ""}).status_code == 422


def test_delete_note(client):
    note = create(client)
    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert client.get(f"/api/notes/{note['id']}").status_code == 404
    assert client.delete(f"/api/notes/{note['id']}").status_code == 404


def test_not_found_and_invalid_id(client):
    assert client.get(f"/api/notes/{uuid.uuid4()}").status_code == 404
    assert client.get("/api/notes/not-a-uuid").status_code == 422
    assert client.patch(f"/api/notes/{uuid.uuid4()}", json={"title": "x"}).status_code == 404


def test_create_validation(client):
    assert client.post("/api/notes", json={}).status_code == 422
    assert client.post("/api/notes", json={"title": "   "}).status_code == 422
    assert client.post("/api/notes", json={"title": "x" * 256}).status_code == 422


def test_title_is_trimmed(client):
    assert create(client, "  espaço  ")["title"] == "espaço"


def test_error_responses_do_not_leak_internals(client):
    body = client.get(f"/api/notes/{uuid.uuid4()}").json()
    assert body == {"detail": "Nota não encontrada."}


def _count_queries(session_factory, client, url):
    from sqlalchemy import event

    engine = session_factory().get_bind()
    statements: list[str] = []

    def on_execute(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        assert client.get(url).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)
    return len(statements)


def test_listing_has_no_n_plus_one(client, session_factory):
    cat = make(client, "/api/categories", name="C")
    proj = make(client, "/api/projects", name="P")
    tags = [make(client, "/api/tags", name=f"t{i}")["id"] for i in range(3)]

    def add(n):
        for i in range(n):
            create(client, f"n{i}", category_id=cat["id"], project_id=proj["id"], tag_ids=tags)

    add(2)
    few = _count_queries(session_factory, client, "/api/notes")
    few_search = _count_queries(session_factory, client, "/api/search")
    add(15)
    many = _count_queries(session_factory, client, "/api/notes")
    many_search = _count_queries(session_factory, client, "/api/search")
    assert few == many  # o número de queries não cresce com o número de notas
    assert few_search == many_search
