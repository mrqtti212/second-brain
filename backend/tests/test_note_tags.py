import uuid

from sqlalchemy import func, select

from app.models import Note, Tag, note_tags
from tests.conftest import make


def _rows(db):
    return db.scalar(select(func.count()).select_from(note_tags))


def test_add_and_remove_tag_are_idempotent(client, db):
    tag = make(client, "/api/tags", name="t")
    note = make(client, "/api/notes", title="n")
    url = f"/api/notes/{note['id']}/tags/{tag['id']}"

    for _ in range(2):  # repetir não duplica a associação
        response = client.put(url)
        assert response.status_code == 200
        assert [t["id"] for t in response.json()["tags"]] == [tag["id"]]
    assert _rows(db) == 1

    for _ in range(2):
        response = client.delete(url)
        assert response.status_code == 200 and response.json()["tags"] == []
    assert _rows(db) == 0


def test_tag_subresource_errors(client):
    note = make(client, "/api/notes", title="n")
    assert client.put(f"/api/notes/{note['id']}/tags/{uuid.uuid4()}").status_code == 404
    tag = make(client, "/api/tags", name="t")
    assert client.put(f"/api/notes/{uuid.uuid4()}/tags/{tag['id']}").status_code == 404
    assert client.delete(f"/api/notes/{uuid.uuid4()}/tags/{tag['id']}").status_code == 404


def test_deleting_note_removes_associations_but_keeps_tags(client, db):
    tag = make(client, "/api/tags", name="t")
    note = make(client, "/api/notes", title="n", tag_ids=[tag["id"]])
    assert _rows(db) == 1
    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert _rows(db) == 0
    assert db.scalar(select(func.count()).select_from(Tag)) == 1


def test_deleting_tag_removes_only_associations(client, db):
    tag = make(client, "/api/tags", name="t")
    keep = make(client, "/api/tags", name="keep")
    note = make(client, "/api/notes", title="n", tag_ids=[tag["id"], keep["id"]])
    assert client.delete(f"/api/tags/{tag['id']}").status_code == 204
    assert _rows(db) == 1
    assert db.scalar(select(func.count()).select_from(Note)) == 1
    body = client.get(f"/api/notes/{note['id']}").json()
    assert [t["name"] for t in body["tags"]] == ["keep"]


def test_no_orphan_rows_after_deleting_everything(client, db):
    tag = make(client, "/api/tags", name="t")
    note = make(client, "/api/notes", title="n", tag_ids=[tag["id"]])
    client.delete(f"/api/notes/{note['id']}")
    client.delete(f"/api/tags/{tag['id']}")
    assert _rows(db) == 0


def test_database_enforces_unique_association(client, db):
    from sqlalchemy.exc import IntegrityError

    tag = make(client, "/api/tags", name="t")
    note = make(client, "/api/notes", title="n", tag_ids=[tag["id"]])
    try:
        db.execute(note_tags.insert().values(note_id=uuid.UUID(note["id"]), tag_id=uuid.UUID(tag["id"])))
        db.commit()
        raised = False
    except IntegrityError:
        db.rollback()
        raised = True
    assert raised
