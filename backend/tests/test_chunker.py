"""Segmentador de texto: função pura, sem banco."""

import pytest

from app.services.chunker import ChunkingConfig, chunk_pages, split_page

CFG = ChunkingConfig(max_chars=200, overlap_chars=50, min_chars=20)
SENTENCE = "Esta é uma frase de exemplo para o teste. "


def long_text(sentences: int = 40) -> str:
    return (SENTENCE * sentences).strip()


def spans_of(text: str, config: ChunkingConfig = CFG):
    return split_page(text, config)


def test_short_page_becomes_one_chunk():
    text = "Um texto curto, mas com conteúdo útil suficiente."
    chunks = chunk_pages([(3, text)], CFG)
    assert len(chunks) == 1
    c = chunks[0]
    assert (c.page_number, c.chunk_index, c.content) == (3, 0, text)
    assert (c.start_offset, c.end_offset) == (0, len(text))


@pytest.mark.parametrize("text", ["", "   ", "\n\n\t  \n", "curto demais"])
def test_pages_without_useful_content_are_ignored(text):
    assert chunk_pages([(1, text)], CFG) == []


def test_minimum_is_measured_without_surrounding_whitespace():
    assert chunk_pages([(1, "   " + "x" * 19 + "   ")], CFG) == []
    assert len(chunk_pages([(1, "   " + "x" * 20 + "   ")], CFG)) == 1


def test_long_page_is_split_into_chunks_within_the_limit():
    text = long_text()
    chunks = chunk_pages([(1, text)], CFG)
    assert len(chunks) > 3
    assert all(0 < len(c.content) <= CFG.max_chars for c in chunks)


def test_content_is_the_exact_slice_of_the_page_text():
    text = long_text()
    for c in chunk_pages([(1, text)], CFG):
        assert text[c.start_offset : c.end_offset] == c.content


def test_order_is_preserved_and_text_is_fully_covered_without_gaps():
    text = long_text()
    chunks = chunk_pages([(1, text)], CFG)
    starts = [c.start_offset for c in chunks]
    ends = [c.end_offset for c in chunks]
    assert starts == sorted(starts) and ends == sorted(ends)
    assert starts[0] == 0 and ends[-1] == len(text)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.start_offset <= previous.end_offset  # nada fica de fora entre dois trechos
        assert current.start_offset > previous.start_offset  # sempre avança


def test_consecutive_chunks_overlap_within_the_configured_amount():
    text = long_text()
    chunks = chunk_pages([(1, text)], CFG)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        overlap = previous.end_offset - current.start_offset
        assert 0 < overlap <= CFG.overlap_chars
        assert text[current.start_offset : previous.end_offset] in previous.content  # trecho repetido de fato


def test_zero_overlap_produces_contiguous_non_overlapping_chunks():
    text = long_text()
    chunks = chunk_pages([(1, text)], ChunkingConfig(max_chars=200, overlap_chars=0, min_chars=20))
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.start_offset >= previous.end_offset
        assert text[previous.end_offset : current.start_offset].strip() == ""  # só espaço entre eles


def test_words_are_never_cut_in_the_middle():
    words = ["palavra" + str(i) for i in range(300)]
    text = " ".join(words)
    chunks = chunk_pages([(1, text)], CFG)
    valid = set(words)
    for c in chunks:
        assert set(c.content.split()) <= valid  # nenhuma palavra truncada nas pontas


def test_prefers_paragraph_breaks():
    paragraph = "Este parágrafo tem um tamanho moderado e termina aqui mesmo."
    text = f"{paragraph}\n\n{paragraph}\n\n{paragraph}\n\n{paragraph}\n\n{paragraph}"
    chunks = chunk_pages([(1, text)], ChunkingConfig(max_chars=150, overlap_chars=0, min_chars=20))
    assert all(c.content.endswith("mesmo.") for c in chunks)
    assert all(c.content.startswith("Este") for c in chunks)


def test_prefers_sentence_end_over_a_plain_space():
    text = long_text()
    chunks = chunk_pages([(1, text)], CFG)
    assert all(c.content.endswith(".") for c in chunks)


def test_falls_back_to_line_breaks_then_spaces():
    lines = "\n".join("linha numero " + str(i) for i in range(60))  # sem pontuação
    chunks = chunk_pages([(1, lines)], ChunkingConfig(max_chars=120, overlap_chars=0, min_chars=20))
    assert len(chunks) > 1 and all(not c.content.endswith(" ") for c in chunks)
    assert all(lines[c.end_offset] == "\n" for c in chunks[:-1])


def test_token_longer_than_the_window_is_hard_cut_and_still_progresses():
    text = "a" * 1000
    chunks = chunk_pages([(1, text)], ChunkingConfig(max_chars=200, overlap_chars=50, min_chars=20))
    assert all(len(c.content) <= 200 for c in chunks)
    assert chunks[-1].end_offset == 1000
    assert len(chunks) < 20  # termina, sem laço infinito


def test_whitespace_and_line_breaks_are_kept_inside_but_trimmed_at_the_edges():
    text = "\n\n   Primeiro parágrafo com   espaços  internos.\n\n\n\nSegundo parágrafo\ttambém.   \n\n"
    chunks = chunk_pages([(1, text)], ChunkingConfig(max_chars=500, overlap_chars=50, min_chars=20))
    assert len(chunks) == 1
    content = chunks[0].content
    assert content == content.strip()
    assert content.startswith("Primeiro") and content.endswith("também.")
    assert "   espaços  internos" in content  # sem normalização
    assert text[chunks[0].start_offset : chunks[0].end_offset] == content


def test_no_chunk_starts_or_ends_with_whitespace_and_none_is_empty():
    text = ("Texto  com\n\nquebras \t e espaços.   " * 40).strip()
    for c in chunk_pages([(1, text)], CFG):
        assert c.content and c.content == c.content.strip()


def test_portuguese_accents_are_counted_as_characters():
    text = ("Ação, coração, informação e programação são palavras acentuadas. " * 12).strip()
    chunks = chunk_pages([(1, text)], CFG)
    assert len(chunks) > 1
    assert all(len(c.content) <= CFG.max_chars for c in chunks)  # caracteres, não bytes
    assert any("ç" in c.content and "ã" in c.content for c in chunks)
    assert all(text[c.start_offset : c.end_offset] == c.content for c in chunks)


def test_chunks_never_mix_pages_and_index_is_sequential_across_the_document():
    pages = [(1, long_text(10)), (2, "curto"), (3, long_text(10)), (4, "   "), (5, "Página final com texto útil bastante.")]
    texts = dict(pages)
    chunks = chunk_pages(pages, CFG)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    numbers = [c.page_number for c in chunks]
    assert numbers == sorted(numbers) and set(numbers) == {1, 3, 5}  # 2 e 4 ignoradas
    for c in chunks:
        assert texts[c.page_number][c.start_offset : c.end_offset] == c.content  # pertence à própria página
    first_of_page_3 = next(c for c in chunks if c.page_number == 3)
    assert first_of_page_3.start_offset == 0  # a sobreposição não atravessa páginas


def test_config_changes_the_result():
    text = long_text()
    small = chunk_pages([(1, text)], ChunkingConfig(max_chars=100, overlap_chars=20, min_chars=10))
    large = chunk_pages([(1, text)], ChunkingConfig(max_chars=400, overlap_chars=20, min_chars=10))
    assert len(small) > len(large)
    assert all(len(c.content) <= 100 for c in small) and all(len(c.content) <= 400 for c in large)
    more_overlap = chunk_pages([(1, text)], ChunkingConfig(max_chars=200, overlap_chars=120, min_chars=10))
    assert len(more_overlap) > len(chunk_pages([(1, text)], ChunkingConfig(max_chars=200, overlap_chars=20, min_chars=10)))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_chars": 0},
        {"max_chars": 100, "overlap_chars": 100},
        {"max_chars": 100, "overlap_chars": -1},
        {"max_chars": 100, "min_chars": 0},
        {"max_chars": 100, "min_chars": 101},
    ],
)
def test_invalid_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        ChunkingConfig(**{"max_chars": 100, "overlap_chars": 10, "min_chars": 5, **kwargs})


def test_is_deterministic():
    text = long_text()
    assert chunk_pages([(1, text)], CFG) == chunk_pages([(1, text)], CFG)


def test_default_values_match_the_documented_ones():
    config = ChunkingConfig()
    assert (config.max_chars, config.overlap_chars, config.min_chars) == (1200, 200, 50)
    chunks = chunk_pages([(1, long_text(120))], config)  # ~5 mil caracteres
    assert all(len(c.content) <= 1200 for c in chunks) and len(chunks) >= 4


def test_text_just_above_the_limit_is_split_in_two():
    text = ("palavra " * 40).strip()  # 319 caracteres
    chunks = chunk_pages([(1, text)], ChunkingConfig(max_chars=300, overlap_chars=50, min_chars=20))
    assert len(chunks) == 2 and chunks[1].end_offset == len(text)
