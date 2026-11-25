"""Serve o frontend compilado (Vite) pela própria API, com fallback para o React Router.

Opcional: só é montado quando `FRONTEND_DIST_PATH` aponta para uma pasta com `index.html`.
Sem isso, nada muda (a API continua sozinha e o frontend roda no servidor de desenvolvimento).
"""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    """Arquivos estáticos do frontend. Uma rota do React (ex.: `/library`) devolve o `index.html`;
    arquivos que não existem (`/assets/x.js`, `/foo.png`) e qualquer caminho sob a API continuam 404."""

    def __init__(self, *, directory: Path, reserved_prefixes: tuple[str, ...]) -> None:
        super().__init__(directory=directory, html=True)
        self._reserved = tuple(p.strip("/") for p in reserved_prefixes if p.strip("/"))

    def _is_client_route(self, path: str) -> bool:
        if any(path == p or path.startswith(p + "/") for p in self._reserved):
            return False
        return "." not in path.rsplit("/", 1)[-1]  # nome de arquivo (com extensão) que não existe: 404 de verdade

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or not self._is_client_route(path):
                raise
            return await super().get_response("index.html", scope)
