#!/usr/bin/env bash
# Inicia o Second Brain como um aplicativo: API + interface na mesma porta (padrão http://127.0.0.1:8000).
#
# O que ele FAZ: confere o ambiente, confere o banco (somente leitura), compila a interface se preciso
# e inicia a API servindo a interface.
# O que ele NÃO faz: não aplica migrations, não instala dependências e não sobe o banco.
# Se algo faltar, explica o que falta e para sem alterar nada.
#
# Uso:  ./scripts/run-app.sh            (compila a interface só se frontend/dist não existir)
#       ./scripts/run-app.sh --build    (força nova compilação da interface)
# Variáveis: PORT (8000), HOST (127.0.0.1). A configuração vem do .env (ver .env.example).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
FORCE_BUILD=0
case "${1:-}" in
  "") ;;
  --build) FORCE_BUILD=1 ;;
  *) echo "Uso: $0 [--build]" >&2; exit 2 ;;
esac

stop() {  # stop "problema" "como resolver" ...
  echo "✗ $1" >&2
  shift
  for line in "$@"; do echo "  $line" >&2; done
  echo "O aplicativo não foi iniciado. Nada foi alterado." >&2
  exit 1
}

PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || stop "O ambiente Python do backend não foi encontrado (backend/.venv)." \
  "Crie com: cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
[ -f "$ROOT/.env" ] || echo "• Aviso: não há .env na raiz; usando os valores padrão (veja .env.example)."

# 1. Banco: conferência somente leitura. Não migra.
echo "• Verificando o banco de dados (somente leitura)…"
cd "$ROOT/backend"
if ! "$PY" -m app.cli check-db; then
  echo "O aplicativo não foi iniciado. Nada foi alterado." >&2
  exit 1
fi

# 2. Interface compilada.
DIST="$ROOT/frontend/dist"
if [ "$FORCE_BUILD" = 1 ] || [ ! -f "$DIST/index.html" ]; then
  [ -d "$ROOT/frontend/node_modules" ] || stop "As dependências da interface não estão instaladas (frontend/node_modules)." \
    "Instale com: cd frontend && npm ci"
  command -v npm >/dev/null 2>&1 || stop "O npm não foi encontrado no PATH (necessário para compilar a interface)."
  echo "• Compilando a interface (npm run build)…"
  (cd "$ROOT/frontend" && npm run build --silent) || stop "A compilação da interface falhou." "Rode manualmente: cd frontend && npm run build"
else
  echo "• Interface já compilada em frontend/dist (use --build para recompilar)."
fi

# 3. API servindo a interface.
export FRONTEND_DIST_PATH="$DIST"
echo "• Second Brain em http://$HOST:$PORT  (Ctrl+C para parar)"
exec "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
