"""Segmentação de texto em trechos (chunks) com sobreposição.

Função pura, sem banco, sem IA e sem dependências externas.

Estratégia
----------
* Cada página é segmentada **separadamente**: um chunk nunca mistura páginas, e a
  sobreposição só existe entre chunks da mesma página.
* Páginas com menos de `min_chars` caracteres úteis (sem contar espaços nas pontas)
  são ignoradas.
* Cada chunk tem no máximo `max_chars` caracteres. O ponto de corte é escolhido na
  segunda metade da janela, nesta ordem de preferência: parágrafo (linha em branco),
  fim de frase, quebra de linha, espaço. Sem nenhum deles, procura qualquer espaço
  na janela. Só um "token" maior que a janela inteira (ex.: uma URL gigante sem
  espaços) é cortado no meio.
* O chunk seguinte começa até `overlap_chars` antes do fim do anterior, avançado
  para o início de uma palavra (nunca no meio dela). Por isso a sobreposição real
  pode ser um pouco menor que o configurado.
* `content` é exatamente `texto_da_página[start_offset:end_offset]`: nada é
  normalizado, e o trecho nunca começa nem termina com espaço em branco.

Limitações: o tamanho é medido em caracteres, não em tokens de modelo; títulos e
listas não são reconhecidos como estrutura; o último chunk de uma página pode ser
quase só sobreposição quando o texto restante é curto.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

_PARAGRAPH = re.compile(r"\n[ \t\r\f\v]*\n")
_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]»]*\s")
_WHITESPACE = re.compile(r"\s")


@dataclass(frozen=True)
class ChunkingConfig:
    max_chars: int = 1200
    overlap_chars: int = 200
    min_chars: int = 50

    def __post_init__(self) -> None:
        if self.max_chars < 1:
            raise ValueError("max_chars deve ser positivo.")
        if not 0 <= self.overlap_chars < self.max_chars:
            raise ValueError("overlap_chars deve estar entre 0 e max_chars - 1.")
        if not 1 <= self.min_chars <= self.max_chars:
            raise ValueError("min_chars deve estar entre 1 e max_chars.")


@dataclass(frozen=True)
class ChunkSpec:
    page_number: int
    chunk_index: int  # sequencial no documento inteiro, a partir de 0
    content: str
    start_offset: int  # posição em `text` da página (inclusive)
    end_offset: int  # posição em `text` da página (exclusivo)


def _skip_whitespace(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _find_end(text: str, start: int, config: ChunkingConfig) -> int:
    """Fim (exclusivo) do chunk que começa em `start`, ainda com espaços finais."""
    limit = start + config.max_chars
    if limit >= len(text):
        return len(text)

    window = text[start : limit + 1]  # +1: enxerga o caractere logo após o limite
    min_end = max(1, config.max_chars // 2)

    def last(matches: list[int]) -> int | None:
        valid = [m for m in matches if m >= min_end]
        return start + valid[-1] if valid else None

    for finder in (
        lambda: last([m.start() for m in _PARAGRAPH.finditer(window)]),
        lambda: last([m.end() - 1 for m in _SENTENCE_END.finditer(window)]),
        lambda: last([i for i, ch in enumerate(window) if ch == "\n"]),
        lambda: last([m.start() for m in _WHITESPACE.finditer(window)]),
    ):
        found = finder()
        if found is not None:
            return found

    # Nenhum ponto natural na segunda metade: aceita um espaço em qualquer lugar.
    spaces = [m.start() for m in _WHITESPACE.finditer(window) if m.start() >= 1]
    return start + spaces[-1] if spaces else limit  # token gigante: corte rígido


def _next_start(text: str, start: int, end: int, overlap: int) -> int:
    """Início do próximo chunk: `overlap` caracteres antes de `end`, no começo de uma palavra."""
    if overlap == 0:
        return _skip_whitespace(text, end)
    candidate = max(end - overlap, start + 1)  # sempre avança
    while candidate < end and not (text[candidate - 1].isspace() and not text[candidate].isspace()):
        candidate += 1
    return _skip_whitespace(text, end) if candidate >= end else candidate


def split_page(text: str, config: ChunkingConfig) -> list[tuple[int, int]]:
    """Intervalos (início, fim) dos chunks de uma página. Vazio se a página não tiver conteúdo útil."""
    useful_end = len(text.rstrip())
    if len(text.strip()) < config.min_chars:
        return []

    spans: list[tuple[int, int]] = []
    start = _skip_whitespace(text, 0)
    while start < useful_end:
        end = min(_find_end(text, start, config), useful_end)
        while end > start and text[end - 1].isspace():
            end -= 1
        if end <= start:  # defesa: nunca produz trecho vazio nem trava
            break
        spans.append((start, end))
        if end >= useful_end:
            break
        start = _next_start(text, start, end, config.overlap_chars)
    return spans


def chunk_pages(pages: Sequence[tuple[int, str]], config: ChunkingConfig) -> list[ChunkSpec]:
    """Segmenta as páginas `(page_number, texto)` na ordem recebida.

    `chunk_index` é sequencial no documento, então a ordem dos chunks acompanha a
    ordem das páginas.
    """
    chunks: list[ChunkSpec] = []
    for page_number, text in pages:
        for start, end in split_page(text, config):
            chunks.append(
                ChunkSpec(
                    page_number=page_number,
                    chunk_index=len(chunks),
                    content=text[start:end],
                    start_offset=start,
                    end_offset=end,
                )
            )
    return chunks
