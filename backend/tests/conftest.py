"""Fixtures de teste.

Por padrão usa SQLite em memória (CRUD e integridade). Com TEST_DATABASE_URL
apontando para um PostgreSQL, toda a suíte roda nele, incluindo a busca textual.
O banco de teste é APAGADO e recriado a cada teste, por isso o nome deve
terminar em `_test`.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_dispatcher
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.processing import DocumentProcessor

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL and not TEST_DATABASE_URL.split("?")[0].endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL deve apontar para um banco cujo nome termina em _test.")

requires_postgres = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="Defina TEST_DATABASE_URL (PostgreSQL) para este teste."
)


@pytest.fixture()
def session_factory() -> Iterator[sessionmaker[Session]]:
    if TEST_DATABASE_URL:
        engine = create_engine(TEST_DATABASE_URL)
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_connection, _record):  # SQLite ignora FKs por padrão
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


class TestDispatcher:
    """Despachante de teste. Imediato por padrão (o processamento termina antes de o POST voltar,
    como se o segundo plano fosse instantâneo); em modo manual os testes decidem quando executar."""

    __test__ = False  # não é uma classe de testes para o pytest

    def __init__(self, processor: DocumentProcessor) -> None:
        self.processor = processor
        self.mode = "inline"
        self.submitted: list[uuid.UUID] = []  # tudo que foi enviado, em ordem
        self.queue: list[uuid.UUID] = []  # aguardando `run_all` (modo manual)
        self.errors: list[BaseException] = []

    def manual(self) -> "TestDispatcher":
        self.mode = "manual"
        return self

    def submit(self, document_id: uuid.UUID) -> None:
        self.submitted.append(document_id)
        if self.mode == "inline":
            self._run(document_id)
        else:
            self.queue.append(document_id)

    def _run(self, document_id: uuid.UUID) -> str | None:
        try:
            return self.processor.process(document_id)
        except BaseException as exc:  # noqa: BLE001 - o pool real também engole; o teste confere no final
            self.errors.append(exc)
            return None

    def run_all(self) -> list[str | None]:
        ids, self.queue = self.queue, []
        return [self._run(i) for i in ids]


@pytest.fixture()
def dispatcher(session_factory) -> Iterator[TestDispatcher]:
    test_dispatcher = TestDispatcher(DocumentProcessor(session_factory))
    yield test_dispatcher
    assert not test_dispatcher.errors, f"erro inesperado no processamento: {test_dispatcher.errors!r}"


@pytest.fixture()
def client(session_factory, dispatcher) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def db(session_factory) -> Iterator[Session]:
    """Sessão direta para inspecionar o estado do banco nos testes."""
    with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch) -> Iterator[Path]:
    """Todo teste usa um diretório temporário: o armazenamento real nunca é tocado."""
    root = tmp_path / "documents"
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(root))
    monkeypatch.setenv("DOCUMENT_PROCESSING_ENABLED", "false")  # o pool real não sobe nos testes
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


@pytest.fixture()
def storage_dir(isolated_storage) -> Path:
    return isolated_storage


def stored_files(root: Path) -> list[str]:
    """Arquivos definitivos e temporários que existem no armazenamento."""
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# --- helpers ---------------------------------------------------------------
def make(client: TestClient, path: str, **body) -> dict:
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    return response.json()
