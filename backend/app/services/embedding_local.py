"""Provedor de embeddings local: `intfloat/multilingual-e5-small` em ONNX, só em CPU.

Privacidade: o modelo é carregado de um diretório local, a execução fixa `CPUExecutionProvider`
(o `onnxruntime` também lista provedores de nuvem; nenhum é usado) e este módulo não abre
conexão de rede. Texto de documento nunca entra em mensagens de erro nem em logs.

Formato do modelo (E5): trechos recebem o prefixo `passage: ` e consultas `query: `. A saída do
ONNX é `last_hidden_state [lote, tokens, 384]`; o vetor é a média dos tokens ponderada pela
máscara de atenção, normalizada em L2 (o mesmo que o pooling e o `Normalize` do modelo original).
Textos acima de 512 tokens são truncados.

`onnxruntime`, `tokenizers` e `numpy` são dependências opcionais (`requirements-embeddings.txt`) e
só são importados aqui dentro, quando o provedor é criado.
"""

import logging
import os
import threading
from collections.abc import Sequence
from pathlib import Path

from app.core.config import Settings
from app.services.embedding_model import (
    MODEL_DIMENSIONS,
    MODEL_ID,
    MODEL_NAME,
    ModelFileError,
    verify_model_dir,
)
from app.services.embeddings import EmbeddingConfigError, EmbeddingError

logger = logging.getLogger("second_brain.embeddings")

PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "
MAX_TOKENS = 512
DOWNLOAD_HINT = "Instale as dependências (pip install -r requirements-embeddings.txt) e o modelo (python -m app.cli download-embedding-model)."


class LocalOnnxEmbeddingProvider:
    model = MODEL_ID
    dimensions = MODEL_DIMENSIONS

    def __init__(self, model_dir: Path, *, threads: int = 0) -> None:
        try:
            import numpy
            import onnxruntime
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise EmbeddingConfigError(f"Dependências do provedor local ausentes ({exc.name}). {DOWNLOAD_HINT}") from None
        try:
            verify_model_dir(model_dir)
        except ModelFileError as exc:
            raise EmbeddingConfigError(f"{exc} {DOWNLOAD_HINT}") from None

        self._np = numpy
        self._lock = threading.Lock()  # o tokenizador guarda configuração de preenchimento
        try:
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = threads or min(os.cpu_count() or 1, 4)
            self._session = onnxruntime.InferenceSession(
                str(model_dir / "model.onnx"), options, providers=["CPUExecutionProvider"]
            )
            self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingConfigError(f"Não foi possível carregar o modelo local ({type(exc).__name__}).") from None
        if self._session.get_providers() != ["CPUExecutionProvider"]:
            raise EmbeddingConfigError("O modelo local deve rodar apenas em CPUExecutionProvider.")
        output = self._session.get_outputs()[0]
        if output.shape[-1] != MODEL_DIMENSIONS:
            raise EmbeddingConfigError(f"O modelo produz {output.shape[-1]} dimensões; o esperado é {MODEL_DIMENSIONS}.")
        self._output_name = output.name
        self._input_names = {i.name for i in self._session.get_inputs()}
        pad_id = self._tokenizer.token_to_id("<pad>")
        self._tokenizer.enable_padding(pad_id=pad_id if pad_id is not None else 1, pad_token="<pad>")
        self._tokenizer.enable_truncation(max_length=MAX_TOKENS)

    def _embed(self, prefix: str, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        np = self._np
        try:
            with self._lock:
                encodings = self._tokenizer.encode_batch([prefix + text for text in texts])
            ids = np.array([e.ids for e in encodings], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._input_names:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self._session.run([self._output_name], feed)[0]  # [lote, tokens, 384]
            weights = mask[:, :, None].astype(hidden.dtype)
            pooled = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
            norms = np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            vectors = pooled / norms
            if not np.isfinite(vectors).all():
                raise EmbeddingError("O modelo produziu valores não finitos.")
            return vectors.astype(np.float64).tolist()
        except EmbeddingError:
            raise
        except Exception as exc:  # noqa: BLE001 - só o tipo é registrado: a mensagem original pode citar o texto
            logger.warning("Falha na inferência do modelo local (%s)", type(exc).__name__)
            raise EmbeddingError(f"Falha na inferência do modelo local ({type(exc).__name__}).") from None

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(PASSAGE_PREFIX, texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed(QUERY_PREFIX, [text])[0]


# Uma instância por processo e por configuração: carregar o modelo custa alguns segundos e cerca de 1 GB de memória.
_instances: dict[tuple[str, int], LocalOnnxEmbeddingProvider] = {}
_instances_lock = threading.Lock()


def get_local_provider(settings: Settings) -> LocalOnnxEmbeddingProvider:
    if settings.embedding_model != MODEL_NAME:
        raise EmbeddingConfigError(f"O provedor local só suporta {MODEL_NAME} (EMBEDDING_MODEL={settings.embedding_model}).")
    model_dir = Path(settings.embedding_model_path).expanduser().resolve()
    key = (str(model_dir), settings.embedding_threads)
    with _instances_lock:
        provider = _instances.get(key)
        if provider is None:
            provider = _instances[key] = LocalOnnxEmbeddingProvider(model_dir, threads=settings.embedding_threads)
    return provider


def clear_provider_cache() -> None:
    with _instances_lock:
        _instances.clear()
