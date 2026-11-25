"""Frontend compilado servido pela API (opcional, desligado por padrão). Não usa banco."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.fixture()
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>Second Brain</title><div id=root></div>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    return root


def client_for(monkeypatch, path: str | None) -> TestClient:
    if path is None:
        monkeypatch.delenv("FRONTEND_DIST_PATH", raising=False)
    else:
        monkeypatch.setenv("FRONTEND_DIST_PATH", path)
    get_settings.cache_clear()
    return TestClient(create_app())  # sem `with`: não precisa do ciclo de vida (nem de banco)


def test_default_is_disabled(monkeypatch):
    assert Settings(_env_file=None).frontend_dist_path == ""
    response = client_for(monkeypatch, None).get("/")
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}


def test_serves_index_assets_and_client_routes(monkeypatch, dist):
    client = client_for(monkeypatch, str(dist))
    home = client.get("/")
    assert home.status_code == 200 and "Second Brain" in home.text and home.headers["content-type"].startswith("text/html")
    for route in ("/library", "/documents/new", "/notes/123/edit"):  # rotas do React Router
        response = client.get(route)
        assert response.status_code == 200 and "<div id=root>" in response.text, route
    assert client.get("/assets/app.js").text == "console.log('app')"
    assert client.get("/favicon.svg").status_code == 200


def test_missing_files_are_404_not_the_html_page(monkeypatch, dist):
    client = client_for(monkeypatch, str(dist))
    for path in ("/assets/missing.js", "/nope.png", "/assets/missing.css"):
        assert client.get(path).status_code == 404, path


def test_api_and_docs_keep_priority_over_the_frontend(monkeypatch, dist):
    client = client_for(monkeypatch, str(dist))
    limits = client.get("/api/documents/limits")
    assert limits.status_code == 200 and "max_upload_bytes" in limits.json()
    unknown = client.get("/api/nao-existe")
    assert unknown.status_code == 404 and unknown.headers["content-type"].startswith("application/json")
    assert "<div id=root>" not in unknown.text
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200 and "swagger" in client.get("/docs").text.lower()


def test_only_get_is_served_and_path_traversal_is_contained(monkeypatch, dist, tmp_path):
    (tmp_path / "segredo.txt").write_text("SEGREDO-FORA-DA-PASTA", encoding="utf-8")
    client = client_for(monkeypatch, str(dist))
    assert client.post("/library").status_code == 405
    for attempt in ("/../segredo.txt", "/%2e%2e/segredo.txt", "/..%2fsegredo.txt", "/assets/../../segredo.txt"):
        assert "SEGREDO-FORA-DA-PASTA" not in client.get(attempt).text, attempt


def test_folder_without_index_is_not_mounted_and_warns(monkeypatch, tmp_path, caplog):
    empty = tmp_path / "vazia"
    empty.mkdir()
    with caplog.at_level(logging.WARNING, logger="second_brain"):
        client = client_for(monkeypatch, str(empty))
    assert client.get("/").status_code == 404
    assert "não tem index.html" in caplog.text and str(empty.resolve()) in caplog.text


def test_relative_path_is_resolved_from_the_working_directory(monkeypatch, dist):
    monkeypatch.chdir(dist.parent)
    assert client_for(monkeypatch, "dist").get("/library").status_code == 200
