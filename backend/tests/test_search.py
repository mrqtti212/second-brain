"""Busca. Os testes com termo de busca exigem PostgreSQL (TEST_DATABASE_URL)."""

import uuid

from tests.conftest import make, requires_postgres


def note(client, title, content="", **extra):
    return make(client, "/api/notes", title=title, content=content, **extra)


def search(client, **params):
    response = client.get("/api/search", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def titles(page):
    return [i["title"] for i in page["items"]]


# --- Sem termo: funcionam em qualquer banco -------------------------------
def test_empty_query_lists_all_and_paginates(client):
    for i in range(5):
        note(client, f"n{i}")
    page = search(client)
    assert page["total"] == 5 and len(page["items"]) == 5
    assert all(i["score"] is None for i in page["items"])
    page = search(client, limit=2, offset=4)
    assert page["total"] == 5 and len(page["items"]) == 1
    assert search(client, q="   ")["total"] == 5  # só espaços = sem termo


def test_filters_without_query(client):
    cat = make(client, "/api/categories", name="C")
    proj = make(client, "/api/projects", name="P")
    t1 = make(client, "/api/tags", name="t1")
    t2 = make(client, "/api/tags", name="t2")
    note(client, "a", category_id=cat["id"], project_id=proj["id"], tag_ids=[t1["id"], t2["id"]])
    note(client, "b", category_id=cat["id"], tag_ids=[t1["id"]])
    note(client, "c", project_id=proj["id"])

    assert set(titles(search(client, category_id=cat["id"]))) == {"a", "b"}
    assert set(titles(search(client, project_id=proj["id"]))) == {"a", "c"}
    assert set(titles(search(client, tag_id=t1["id"]))) == {"a", "b"}
    # várias etiquetas = todas; combinação de filtros = interseção
    assert titles(search(client, tag_id=[t1["id"], t2["id"]])) == ["a"]
    assert titles(search(client, category_id=cat["id"], project_id=proj["id"])) == ["a"]
    # sem duplicatas mesmo com várias etiquetas
    assert search(client, tag_id=[t1["id"], t2["id"]])["total"] == 1
    assert search(client, category_id=str(uuid.uuid4()))["items"] == []


def test_result_shape(client):
    cat = make(client, "/api/categories", name="C")
    proj = make(client, "/api/projects", name="P")
    tag = make(client, "/api/tags", name="t")
    note(client, "x", "conteúdo longo", category_id=cat["id"], project_id=proj["id"], tag_ids=[tag["id"]])
    item = search(client)["items"][0]
    assert set(item) == {
        "type", "id", "title", "snippet", "updated_at", "category", "project", "tags", "score",
        "status", "page_count", "has_text",
    }
    assert item["type"] == "note"
    assert item["category"]["name"] == "C" and item["project"]["name"] == "P"
    assert [t["name"] for t in item["tags"]] == ["t"]
    assert item["snippet"] == "conteúdo longo"


def test_parameter_validation(client):
    assert client.get("/api/search?limit=0").status_code == 422
    assert client.get("/api/search?limit=101").status_code == 422
    assert client.get("/api/search?offset=-1").status_code == 422
    assert client.get("/api/search?category_id=abc").status_code == 422
    assert client.get("/api/search?q=" + "a" * 201).status_code == 422


def test_text_query_reports_unavailable_without_postgres(client, session_factory):
    if session_factory().get_bind().dialect.name == "postgresql":
        return
    response = client.get("/api/search?q=algo")
    assert response.status_code == 503
    assert response.json() == {"detail": "A busca textual requer PostgreSQL."}


# --- Com termo: PostgreSQL ------------------------------------------------
@requires_postgres
def test_finds_by_title_and_content(client):
    note(client, "Guia de Python", "Introdução")
    note(client, "Receitas", "Bolo de cenoura com python? não, com cobertura")
    note(client, "Outro", "nada relacionado")
    assert set(titles(search(client, q="python"))) == {"Guia de Python", "Receitas"}
    assert titles(search(client, q="cobertura")) == ["Receitas"]


@requires_postgres
def test_portuguese_stemming_and_case(client):
    note(client, "Minhas casas", "Estudo sobre construção")
    assert titles(search(client, q="CASA")) == ["Minhas casas"]
    assert titles(search(client, q="estudos")) == ["Minhas casas"]  # plural -> mesmo radical


@requires_postgres
def test_finds_by_tag_category_and_project_names(client):
    cat = make(client, "/api/categories", name="Culinária")
    proj = make(client, "/api/projects", name="Livro")
    tag = make(client, "/api/tags", name="sobremesa")
    note(client, "A", "x", tag_ids=[tag["id"]])
    note(client, "B", "x", category_id=cat["id"])
    note(client, "C", "x", project_id=proj["id"])
    note(client, "D", "x")
    assert titles(search(client, q="sobremesa")) == ["A"]
    assert titles(search(client, q="culinária")) == ["B"]
    assert titles(search(client, q="livro")) == ["C"]


@requires_postgres
def test_query_combined_with_filters(client):
    cat = make(client, "/api/categories", name="Tech")
    tag = make(client, "/api/tags", name="web")
    note(client, "Python web", "x", category_id=cat["id"], tag_ids=[tag["id"]])
    note(client, "Python dados", "x", category_id=cat["id"])
    note(client, "Python solto", "x")
    assert set(titles(search(client, q="python", category_id=cat["id"]))) == {"Python web", "Python dados"}
    assert titles(search(client, q="python", category_id=cat["id"], tag_id=tag["id"])) == ["Python web"]


@requires_postgres
def test_results_ordered_by_relevance(client):
    note(client, "Receitas", "python python python no conteúdo")
    note(client, "Python", "título casa com a busca")
    page = search(client, q="python")
    assert titles(page)[0] == "Python"  # título (peso A) vence conteúdo (peso C)
    scores = [i["score"] for i in page["items"]]
    assert scores == sorted(scores, reverse=True) and all(s > 0 for s in scores)


@requires_postgres
def test_snippet_highlights_terms(client):
    note(client, "N", "Texto inicial. " * 30 + "A palavra especial aparece aqui. " + "Fim. " * 30)
    snippet = search(client, q="especial")["items"][0]["snippet"]
    assert "especial" in snippet and len(snippet) < 400


@requires_postgres
def test_pagination_with_query(client):
    for i in range(7):
        note(client, f"python {i}")
    first = search(client, q="python", limit=3, offset=0)
    last = search(client, q="python", limit=3, offset=6)
    assert first["total"] == 7 and len(first["items"]) == 3 and len(last["items"]) == 1
    ids = [i["id"] for p in (first, search(client, q="python", limit=3, offset=3), last) for i in p["items"]]
    assert len(set(ids)) == 7


@requires_postgres
def test_no_results_and_odd_input_do_not_error(client):
    note(client, "Alguma coisa")
    assert search(client, q="inexistente")["items"] == []
    assert search(client, q="de")["total"] == 0  # só stopword
    for odd in ('"aspas abertas', "a & | ! ( )", ":*", "-", "'; DROP TABLE notes; --", "\\", "%_"):
        assert client.get("/api/search", params={"q": odd}).status_code == 200, odd
    assert search(client)["total"] == 1  # a tabela continua intacta


@requires_postgres
def test_search_index_follows_changes(client):
    tag = make(client, "/api/tags", name="alfa")
    n = note(client, "Nota", "x", tag_ids=[tag["id"]])
    assert titles(search(client, q="alfa")) == ["Nota"]

    client.patch(f"/api/tags/{tag['id']}", json={"name": "bravo"})  # renomear etiqueta
    assert search(client, q="alfa")["items"] == []
    assert titles(search(client, q="bravo")) == ["Nota"]

    client.patch(f"/api/notes/{n['id']}", json={"title": "Zeta", "content": "novo texto"})
    assert titles(search(client, q="zeta")) == ["Zeta"]
    assert titles(search(client, q="bravo")) == ["Zeta"]  # etiqueta preservada

    client.delete(f"/api/notes/{n['id']}/tags/{tag['id']}")
    assert search(client, q="bravo")["items"] == []

    client.put(f"/api/notes/{n['id']}/tags/{tag['id']}")
    client.delete(f"/api/tags/{tag['id']}")  # excluir etiqueta
    assert search(client, q="bravo")["items"] == []
    assert titles(search(client, q="zeta")) == ["Zeta"]  # nota preservada e pesquisável


@requires_postgres
def test_category_and_project_rename_and_delete_update_index(client):
    cat = make(client, "/api/categories", name="Antiga")
    proj = make(client, "/api/projects", name="Velho")
    note(client, "N", "x", category_id=cat["id"], project_id=proj["id"])
    client.patch(f"/api/categories/{cat['id']}", json={"name": "Nova"})
    client.patch(f"/api/projects/{proj['id']}", json={"name": "Moderno"})
    assert search(client, q="antiga")["items"] == []
    assert titles(search(client, q="nova")) == ["N"]
    assert titles(search(client, q="moderno")) == ["N"]
    client.delete(f"/api/categories/{cat['id']}")
    client.delete(f"/api/projects/{proj['id']}")
    assert search(client, q="nova")["items"] == [] and search(client, q="moderno")["items"] == []
    assert search(client)["total"] == 1


@requires_postgres
def test_uses_gin_index_on_search_vector(session_factory):
    from sqlalchemy import text

    with session_factory() as db:
        defs = db.execute(text("SELECT indexdef FROM pg_indexes WHERE tablename='notes'")).scalars().all()
    assert any("USING gin (search_vector)" in d for d in defs)
