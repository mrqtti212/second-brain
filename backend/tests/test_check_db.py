"""`check-db`: conferência SOMENTE LEITURA do banco (nunca cria tabelas nem aplica migrations)."""

import sqlite3
from pathlib import Path

from app import cli
from app.core.config import Settings
from app.db.check import NEEDS_MIGRATIONS, READY, UNREACHABLE, check_database, expected_head

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def with_version(path: Path, version: str | None) -> Path:
    connection = sqlite3.connect(path)
    if version is not None:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (version,))
    connection.execute("CREATE TABLE marcador (id INTEGER)")  # garante que o arquivo é um banco válido
    connection.commit()
    connection.close()
    return path


def tables(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()


def test_expected_head_is_the_newest_migration_file():
    newest = max(p.name.split("_")[0] for p in MIGRATIONS.glob("0*.py"))
    assert expected_head() == newest


def test_ready_when_the_database_is_at_the_expected_revision(tmp_path):
    db = with_version(tmp_path / "ok.db", expected_head())
    status = check_database(sqlite_url(db))
    assert status.code == READY and status.ready and expected_head() in status.message


def test_empty_database_asks_for_migrations_and_is_left_untouched(tmp_path):
    db = with_version(tmp_path / "vazio.db", None)
    before = tables(db)
    status = check_database(sqlite_url(db))
    assert status.code == NEEDS_MIGRATIONS and "alembic upgrade head" in status.message and "vazio" in status.message
    assert tables(db) == before  # nem a tabela alembic_version foi criada: a conferência não escreve nada


def test_outdated_database_reports_both_revisions(tmp_path):
    status = check_database(sqlite_url(with_version(tmp_path / "velho.db", "0005")))
    assert status.code == NEEDS_MIGRATIONS and "0005" in status.message and expected_head() in status.message
    assert "alembic upgrade head" in status.message


def test_unknown_revision_is_not_treated_as_outdated(tmp_path):
    status = check_database(sqlite_url(with_version(tmp_path / "novo.db", "9999")))
    assert status.code == NEEDS_MIGRATIONS and "desconhecida" in status.message and "9999" in status.message
    assert "alembic upgrade head" not in status.message  # migrar para frente não resolveria


def test_unreachable_database_does_not_leak_the_password():
    status = check_database("postgresql+psycopg://usuario:SENHA-SECRETA@127.0.0.1:1/banco")
    assert status.code == UNREACHABLE
    assert "SENHA-SECRETA" not in status.message and "usuario" not in status.message
    assert "127.0.0.1:1/banco" in status.message and "docker compose up -d db" in status.message


def test_cli_command_prints_and_returns_the_status_code(tmp_path, capsys):
    ok = Settings(_env_file=None, database_url=sqlite_url(with_version(tmp_path / "ok.db", expected_head())))
    assert cli.main(["check-db"], settings=ok) == READY
    assert "Banco pronto" in capsys.readouterr().out

    empty = Settings(_env_file=None, database_url=sqlite_url(with_version(tmp_path / "vazio.db", None)))
    assert cli.main(["check-db"], settings=empty) == NEEDS_MIGRATIONS
    assert "alembic upgrade head" in capsys.readouterr().err

    down = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@127.0.0.1:1/x")
    assert cli.main(["check-db"], settings=down) == UNREACHABLE
    assert "Não foi possível conectar" in capsys.readouterr().err
