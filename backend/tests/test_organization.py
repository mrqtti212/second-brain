import uuid

import pytest

from tests.conftest import make

RESOURCES = {
    "categories": {"name": "Estudos", "description": "Material de estudo", "color": "#3366ff"},
    "projects": {"name": "Tese", "description": "Doutorado"},
    "tags": {"name": "python", "color": "#22cc88"},
}
NOTE_FIELD = {"categories": "category_id", "projects": "project_id"}


@pytest.fixture(params=list(RESOURCES))
def resource(request):
    return request.param, RESOURCES[request.param]


def test_crud(client, resource):
    name, payload = resource
    base = f"/api/{name}"
    created = make(client, base, **payload)
    assert uuid.UUID(created["id"]) and created["created_at"]
    assert created["name"] == payload["name"] and created["notes_count"] == 0

    assert client.get(f"{base}/{created['id']}").json()["id"] == created["id"]
    assert [i["id"] for i in client.get(base).json()] == [created["id"]]

    patched = client.patch(f"{base}/{created['id']}", json={"name": "Renomeado"})
    assert patched.status_code == 200 and patched.json()["name"] == "Renomeado"

    assert client.delete(f"{base}/{created['id']}").status_code == 204
    assert client.get(f"{base}/{created['id']}").status_code == 404
    assert client.delete(f"{base}/{created['id']}").status_code == 404
    assert client.patch(f"{base}/{created['id']}", json={"name": "x"}).status_code == 404


def test_required_name_and_validation(client, resource):
    name, _ = resource
    base = f"/api/{name}"
    assert client.post(base, json={}).status_code == 422
    assert client.post(base, json={"name": "   "}).status_code == 422
    assert client.post(base, json={"name": "x" * 81}).status_code == 422
    created = make(client, base, name="ok")
    assert client.patch(f"{base}/{created['id']}", json={"name": None}).status_code == 422
    assert client.patch(f"{base}/{created['id']}", json={"name": ""}).status_code == 422


def test_invalid_color_is_rejected(client):
    for base in ("/api/categories", "/api/tags"):
        assert client.post(base, json={"name": "c", "color": "red"}).status_code == 422
        assert client.post(base, json={"name": "c", "color": "#12345"}).status_code == 422


def test_name_is_unique_ignoring_case(client, resource):
    name, payload = resource
    base = f"/api/{name}"
    make(client, base, **payload)
    for duplicate in (payload["name"], payload["name"].upper(), f"  {payload['name']}  "):
        response = client.post(base, json={"name": duplicate})
        assert response.status_code == 409, duplicate
        assert "Já existe" in response.json()["detail"]


def test_rename_to_existing_name_conflicts(client, resource):
    name, _ = resource
    base = f"/api/{name}"
    make(client, base, name="Um")
    other = make(client, base, name="Dois")
    assert client.patch(f"{base}/{other['id']}", json={"name": "um"}).status_code == 409
    # renomear para o próprio nome (com outra caixa) é permitido
    assert client.patch(f"{base}/{other['id']}", json={"name": "DOIS"}).status_code == 200


def test_patch_can_clear_optional_fields(client):
    cat = make(client, "/api/categories", name="C", description="d", color="#112233")
    body = client.patch(
        f"/api/categories/{cat['id']}", json={"description": None, "color": None}
    ).json()
    assert body["description"] is None and body["color"] is None and body["name"] == "C"


def test_notes_count(client, resource):
    name, payload = resource
    item = make(client, f"/api/{name}", **payload)
    key = {"categories": "category_id", "projects": "project_id"}.get(name)
    for i in range(2):
        body = {"title": f"n{i}"}
        body.update({key: item["id"]} if key else {"tag_ids": [item["id"]]})
        make(client, "/api/notes", **body)
    assert client.get(f"/api/{name}/{item['id']}").json()["notes_count"] == 2
    assert client.get(f"/api/{name}").json()[0]["notes_count"] == 2


def test_delete_preserves_notes(client, resource):
    name, payload = resource
    item = make(client, f"/api/{name}", **payload)
    key = NOTE_FIELD.get(name)
    body = {"title": "sobrevive"}
    body.update({key: item["id"]} if key else {"tag_ids": [item["id"]]})
    note = make(client, "/api/notes", **body)

    assert client.delete(f"/api/{name}/{item['id']}").status_code == 204
    after = client.get(f"/api/notes/{note['id']}")
    assert after.status_code == 200
    data = after.json()
    assert data["category"] is None and data["project"] is None and data["tags"] == []
