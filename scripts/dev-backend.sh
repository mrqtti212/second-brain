#!/usr/bin/env bash
# Aplica migrations e inicia a API com recarga automática.
set -euo pipefail
cd "$(dirname "$0")/../backend"
source .venv/bin/activate
alembic upgrade head
exec uvicorn app.main:app --reload --port 8000
