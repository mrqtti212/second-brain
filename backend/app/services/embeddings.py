"""Provedores de embeddings: contrato, validação e um provedor falso para testes.

O provedor real (local, ONNX) fica em `embedding_local.py`; aqui há o contrato e o provedor falso. O contrato diferencia trechos de documentos
(`embed_passages`) de consultas (`embed_query`) porque modelos como o E5 usam prefixos
diferentes para cada um. Nenhuma mensagem de erro deste módulo inclui o texto recebido.
"""

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.core.config import Settings


class EmbeddingError(Exception):
    """Falha ao gerar ou validar embeddings. A mensagem nunca contém o texto dos documentos."""


class EmbeddingConfigError(EmbeddingError):
    """Configuração de embeddings inválida ou provedor indisponível."""


class EmbeddingTransientError(EmbeddingError):
    """Falha provavelmente passageira (tempo esgotado, serviço ocupado): vale tentar de novo.

    Só este tipo é repetido pelas tarefas de geração. Qualquer outro erro do provedor, como uma
    dimensão errada, é definitivo para aquela execução e não é repetido.
    """


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Contrato de um provedor. As implementações devem ser seguras para uso em várias threads."""

    model: str  # identificador gravado em `chunk_embeddings.model`
    dimensions: int  # tamanho de cada vetor devolvido

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """Um vetor por texto, na mesma ordem. Lista vazia devolve lista vazia."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Vetor de uma consulta de busca."""
        ...


def text_sha256(text: str) -> str:
    """Hash do texto de um trecho (`chunk_embeddings.content_sha256`)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_vectors(provider: EmbeddingProvider, texts: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
    """Confere o que um provedor devolveu: quantidade, dimensão e valores finitos.

    Existe para que um provedor com defeito nunca grave lixo no banco. Levanta `EmbeddingError`
    sem copiar texto nem valores na mensagem.
    """
    if len(vectors) != len(texts):
        raise EmbeddingError(f"O provedor devolveu {len(vectors)} vetores para {len(texts)} textos.")
    for position, vector in enumerate(vectors):
        if len(vector) != provider.dimensions:
            raise EmbeddingError(
                f"Vetor {position} com {len(vector)} dimensões; o esperado é {provider.dimensions}."
            )
        if not all(math.isfinite(x) for x in vector):
            raise EmbeddingError(f"Vetor {position} contém valores não finitos.")


_TOKEN = re.compile(r"\w+", re.UNICODE)


class FakeEmbeddingProvider:
    """Provedor determinístico para testes. Não é semântico, só lexical, e não usa rede nem modelo.

    Cada palavra (minúscula) soma ou subtrai 1 em duas posições do vetor, escolhidas pelo SHA-256 da
    palavra; o resultado é normalizado (norma 1). Textos com palavras em comum ficam próximos por
    cosseno, textos sem nenhuma palavra em comum ficam quase ortogonais, e o mesmo texto sempre dá o
    mesmo vetor. `embed_query` e `embed_passages` usam a mesma função (sem prefixos).
    """

    def __init__(self, dimensions: int = 384, model: str = "fake-hash-v1") -> None:
        if dimensions < 2:
            raise ValueError("dimensions deve ser pelo menos 2.")
        self.dimensions = dimensions
        self.model = model
        self.passage_calls = 0  # quantas chamadas de lote e quantos textos, para os testes conferirem
        self.passage_texts = 0
        self.query_calls = 0

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _TOKEN.findall(text.lower()) or [text]  # texto sem palavras ainda gera um vetor útil
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for offset in (0, 4):
                index = int.from_bytes(digest[offset : offset + 3], "big") % self.dimensions
                vector[index] += 1.0 if digest[offset + 3] & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0.0:  # cancelamento exato: cai para um vetor unitário fixo derivado do texto
            vector[int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:3], "big") % self.dimensions] = 1.0
            return vector
        return [x / norm for x in vector]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        self.passage_calls += 1
        self.passage_texts += len(texts)
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return self._embed(text)


def build_provider(settings: Settings) -> EmbeddingProvider | None:
    """Provedor configurado, ou `None` quando os embeddings estão desligados (o padrão)."""
    if not settings.embeddings_enabled:
        return None
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider(dimensions=settings.embedding_dimensions)
    from app.services.embedding_local import get_local_provider  # importa o ML só quando for usado

    return get_local_provider(settings)
