"""Armazenamento local de arquivos de documentos.

- O nome gravado em disco é gerado aqui (`<uuid4 hex>.pdf`); o nome enviado
  pelo usuário nunca participa do caminho.
- O envio é gravado em um arquivo temporário (`.tmp/`) e só vira definitivo
  por `os.link`, que não sobrescreve arquivo existente.
- A exclusão é em duas fases (renomear para `.deleting`, depois apagar), para
  que o registro no banco e o arquivo possam ser mantidos consistentes.
"""

import hashlib
import logging
import os
import re
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.core.config import get_settings
from app.core.errors import InvalidFileError, PayloadTooLargeError, StorageError

logger = logging.getLogger("second_brain.storage")

KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.pdf$")
CHUNK_SIZE = 1024 * 1024
PDF_SIGNATURE = b"%PDF-"
SIGNATURE_WINDOW = 1024  # a especificação admite lixo antes do cabeçalho, até 1 KiB


@dataclass
class StagedFile:
    path: Path
    size: int
    sha256: str
    _storage: "LocalStorage"
    _key: str | None = None

    def commit(self) -> str:
        """Move o arquivo temporário para o destino definitivo e devolve a chave."""
        if self._key is not None:
            return self._key
        self._key = self._storage._link_into_place(self.path)
        return self._key


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self._tmp = self.root / ".tmp"

    # --- caminhos ---------------------------------------------------------
    def path_for(self, key: str) -> Path:
        """Caminho absoluto de uma chave. Rejeita qualquer coisa fora do padrão gerado por nós."""
        if not KEY_PATTERN.fullmatch(key):
            raise StorageError("Chave de armazenamento inválida.")
        path = (self.root / key).resolve()
        if path.parent != self.root:  # defesa extra contra links simbólicos
            raise StorageError("Chave de armazenamento inválida.")
        return path

    def exists(self, key: str) -> bool:
        return self.path_for(key).is_file()

    # --- gravação ---------------------------------------------------------
    @contextmanager
    def stage(self, source: BinaryIO, max_bytes: int) -> Iterator[StagedFile]:
        """Grava o fluxo em um temporário, validando tamanho e assinatura.

        O temporário é sempre removido ao sair do bloco, mesmo se `commit()` já
        tiver criado o arquivo definitivo (que é outro link).
        """
        try:
            self._tmp.mkdir(parents=True, exist_ok=True)
            tmp = tempfile.NamedTemporaryFile(dir=self._tmp, prefix="upload-", delete=False)
        except OSError as exc:
            logger.error("Não foi possível preparar o armazenamento: %s", exc)
            raise StorageError() from exc

        path = Path(tmp.name)
        try:
            with tmp:
                size, digest = self._copy(source, tmp, max_bytes)
            yield StagedFile(path=path, size=size, sha256=digest, _storage=self)
        finally:
            path.unlink(missing_ok=True)

    def _copy(self, source: BinaryIO, target: BinaryIO, max_bytes: int) -> tuple[int, str]:
        hasher = hashlib.sha256()
        size = 0
        head = b""
        while chunk := source.read(CHUNK_SIZE):
            size += len(chunk)
            if size > max_bytes:
                limit_mb = max_bytes // (1024 * 1024)
                raise PayloadTooLargeError(f"O arquivo excede o limite de {limit_mb} MB.")
            if len(head) < SIGNATURE_WINDOW:
                head = (head + chunk)[:SIGNATURE_WINDOW]
            hasher.update(chunk)
            target.write(chunk)
        if size == 0:
            raise InvalidFileError("O arquivo está vazio.")
        if PDF_SIGNATURE not in head:
            raise InvalidFileError("O conteúdo do arquivo não é um PDF.")
        return size, hasher.hexdigest()

    def _link_into_place(self, tmp_path: Path) -> str:
        for _ in range(5):
            key = f"{uuid.uuid4().hex}.pdf"
            try:
                os.link(tmp_path, self.root / key)  # falha se já existir: nunca sobrescreve
                return key
            except FileExistsError:
                continue
            except OSError as exc:
                logger.error("Falha ao gravar arquivo definitivo: %s", exc)
                raise StorageError() from exc
        raise StorageError()

    # --- exclusão em duas fases ------------------------------------------
    def mark_for_deletion(self, key: str) -> Path | None:
        """Renomeia o arquivo para `.deleting`. Devolve None se ele já não existe."""
        path = self.path_for(key)
        tombstone = path.with_name(path.name + ".deleting")
        try:
            os.replace(path, tombstone)
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.error("Falha ao marcar arquivo para exclusão: %s", exc)
            raise StorageError("Não foi possível remover o arquivo do documento.") from exc
        return tombstone

    def restore(self, key: str, tombstone: Path) -> None:
        try:
            os.replace(tombstone, self.path_for(key))
        except OSError:
            logger.exception("Falha ao restaurar arquivo %s após erro", key)

    def purge(self, tombstone: Path) -> None:
        try:
            tombstone.unlink(missing_ok=True)
        except OSError:
            # O registro já foi removido; sobra apenas o arquivo `.deleting`, inacessível pela API.
            logger.warning("Não foi possível apagar %s", tombstone.name)

    def delete(self, key: str) -> None:
        """Remoção imediata (usada para desfazer uma importação que falhou)."""
        try:
            self.path_for(key).unlink(missing_ok=True)
        except OSError:
            logger.exception("Falha ao remover arquivo %s", key)


def get_storage() -> LocalStorage:
    return LocalStorage(Path(get_settings().document_storage_path))
