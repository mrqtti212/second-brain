"""Verifica se o banco está pronto para o aplicativo. SOMENTE LEITURA: nunca cria tabelas e
nunca aplica migrations; só informa o que falta e o comando para resolver."""

from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[2]
READY, UNREACHABLE, NEEDS_MIGRATIONS = 0, 2, 3


@dataclass(frozen=True)
class DbStatus:
    code: int  # 0 pronto, 2 sem conexão, 3 migrations ausentes ou incompatíveis
    message: str

    @property
    def ready(self) -> bool:
        return self.code == READY


def _script() -> ScriptDirectory:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return ScriptDirectory.from_config(config)


def expected_head() -> str:
    head = _script().get_current_head()
    assert head is not None
    return head


def check_database(database_url: str) -> DbStatus:
    url = make_url(database_url)
    where = f"{url.host or url.database}{':' + str(url.port) if url.port else ''}{'/' + url.database if url.host and url.database else ''}"
    connect_args = {"connect_timeout": 5} if url.get_backend_name() == "postgresql" else {}
    engine = create_engine(url, poolclass=NullPool, connect_args=connect_args)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current = MigrationContext.configure(connection).get_current_revision()
    except Exception as exc:  # noqa: BLE001 - a mensagem original pode conter a senha da URL: só o tipo é mostrado
        return DbStatus(
            UNREACHABLE,
            f"Não foi possível conectar ao banco em {where} ({type(exc).__name__}).\n"
            "  Suba o PostgreSQL com pgvector (docker compose up -d db) ou confira o DATABASE_URL no .env.",
        )
    finally:
        engine.dispose()

    head = expected_head()
    if current is None:
        return DbStatus(
            NEEDS_MIGRATIONS,
            f"O banco em {where} está acessível, mas vazio (nenhuma migration aplicada).\n"
            "  Aplique com: cd backend && alembic upgrade head   (este script não faz isso por você).",
        )
    if current == head:
        return DbStatus(READY, f"Banco pronto em {where} (migrations em dia, revisão {head}).")
    try:
        _script().get_revision(current)
        known = True
    except Exception:  # noqa: BLE001
        known = False
    if known:
        return DbStatus(
            NEEDS_MIGRATIONS,
            f"O banco em {where} está na revisão {current}, mas o aplicativo espera {head}.\n"
            "  Aplique com: cd backend && alembic upgrade head   (este script não faz isso por você).",
        )
    return DbStatus(
        NEEDS_MIGRATIONS,
        f"O banco em {where} está numa revisão desconhecida para este código ({current}); o esperado é {head}.\n"
        "  Ele pode ter sido migrado por uma versão mais nova do aplicativo. Nada foi alterado.",
    )
