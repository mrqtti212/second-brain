"""Arquivos do modelo de embeddings local: revisão fixa, hashes esperados e instalação verificada.

Nada aqui roda sozinho. `install_model` só é chamado pelo comando manual
`python -m app.cli download-embedding-model`; o servidor nunca baixa nada. Os únicos dados que
trafegam são os arquivos públicos do modelo (nenhum texto de documento).
"""

import hashlib
import shutil
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MODEL_NAME = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
MODEL_DIMENSIONS = 384
# Gravado em `chunk_embeddings.model`: incluir a revisão impede misturar vetores de pesos diferentes.
MODEL_ID = f"{MODEL_NAME}@{MODEL_REVISION[:8]}"


@dataclass(frozen=True)
class ModelFile:
    name: str  # nome no diretório local
    remote: str  # caminho no repositório do modelo
    sha256: str


MODEL_FILES = (
    ModelFile("model.onnx", "onnx/model.onnx", "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665"),
    ModelFile("tokenizer.json", "tokenizer.json", "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"),
    ModelFile("config.json", "config.json", "69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959"),
)


class ModelFileError(Exception):
    """Arquivo ausente, corrompido ou com hash diferente do esperado."""


def huggingface_url(remote: str) -> str:
    return f"https://huggingface.co/{MODEL_NAME}/resolve/{MODEL_REVISION}/{remote}"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_model_dir(directory: Path) -> None:
    """Confere que os três arquivos existem e têm o SHA-256 esperado. Levanta `ModelFileError`."""
    for item in MODEL_FILES:
        path = directory / item.name
        if not path.is_file():
            raise ModelFileError(f"Arquivo do modelo ausente: {path}")
        if sha256_of(path) != item.sha256:
            raise ModelFileError(f"O SHA-256 de {item.name} não confere com o esperado para a revisão {MODEL_REVISION[:8]}.")


def _fetch(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as out:  # noqa: S310 - https fixo
        shutil.copyfileobj(response, out, 1024 * 1024)


def install_model(
    destination: Path,
    *,
    source_dir: Path | None = None,
    url_for: Callable[[str], str] = huggingface_url,
    log: Callable[[str], None] = print,
) -> None:
    """Instala os arquivos do modelo em `destination`, aceitando cada um só depois de verificar o SHA-256.

    Com `source_dir`, copia de uma cópia local (nada é baixado); sem ele, baixa da revisão fixa.
    Um arquivo já presente e correto é mantido. Um arquivo que não confere é descartado e nunca
    chega ao nome final.
    """
    destination.mkdir(parents=True, exist_ok=True)
    for item in MODEL_FILES:
        final = destination / item.name
        if final.is_file() and sha256_of(final) == item.sha256:
            log(f"ok (já presente): {item.name}")
            continue
        partial = destination / f"{item.name}.part"
        try:
            if source_dir is not None:
                origin = next((p for p in (source_dir / item.remote, source_dir / item.name) if p.is_file()), None)
                if origin is None:
                    raise ModelFileError(f"{item.name} não encontrado em {source_dir}")
                shutil.copyfile(origin, partial)
            else:
                log(f"baixando {item.remote} (revisão {MODEL_REVISION[:8]})")
                _fetch(url_for(item.remote), partial)
            if sha256_of(partial) != item.sha256:
                raise ModelFileError(f"SHA-256 de {item.name} não confere; o arquivo foi descartado.")
            partial.replace(final)
            log(f"ok (verificado): {item.name}")
        finally:
            partial.unlink(missing_ok=True)
