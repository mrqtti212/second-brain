#!/usr/bin/env bash
# Sobe o PostgreSQL com pgvector e aguarda ficar saudável.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "Crie o .env a partir do .env.example primeiro." >&2; exit 1; }
docker compose up -d --wait db
