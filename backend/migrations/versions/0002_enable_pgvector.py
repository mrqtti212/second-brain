"""enable pgvector extension

Apenas habilita a extensão. Nenhuma coluna de embedding existe na Fase 1.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
