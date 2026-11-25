"""Etapa C: provedor local ONNX (`intfloat/multilingual-e5-small`) e instalação do modelo.

Os testes que usam o modelo real são ignorados quando as dependências opcionais
(`requirements-embeddings.txt`) ou os arquivos de `backend/models/multilingual-e5-small/` não existem.
Nada aqui usa rede: um teste bloqueia conexões durante a carga e a inferência.
"""

import hashlib
import http.server
import logging
import math
import socket
import sys
import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app import cli
from app.core.config import Settings, get_settings
from app.main import app
from app.models import ChunkEmbedding, DocumentChunk
from app.services import embedding_local, embedding_model
from app.services.embedding_model import MODEL_FILES, MODEL_ID, ModelFile, ModelFileError, install_model
from app.services.embedding_tasks import embed_document
from app.services.embeddings import (
    EmbeddingConfigError,
    EmbeddingError,
    EmbeddingProvider,
    build_provider,
    validate_vectors,
)
from tests.conftest import requires_postgres
from tests.docs_helpers import long_text, ok
from tests.pdfs import unique_pdf
from tests.quality_data import OUT_OF_CORPUS, PASSAGES, QUERIES
from tests.test_embedding_tasks import Sleeps, make_document, rows_of, runner_dispatcher, texts_for

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "multilingual-e5-small"


def _model_available() -> bool:
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError:
        return False
    return all((MODEL_DIR / item.name).is_file() for item in MODEL_FILES)


needs_model = pytest.mark.skipif(not _model_available(), reason="Instale requirements-embeddings.txt e o modelo local.")


def local_settings(**overrides) -> Settings:
    values = dict(embeddings_enabled=True, embedding_provider="local", embedding_model_path=str(MODEL_DIR),
                  embedding_retry_backoff_seconds=0)
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture(scope="module")
def real():
    return embedding_local.get_local_provider(local_settings())


class Counting:
    """Envolve um provedor e conta as chamadas (para provar que não houve chamadas a mais)."""

    def __init__(self, inner) -> None:
        self.inner, self.model, self.dimensions = inner, inner.model, inner.dimensions
        self.calls = 0
        self.texts = 0

    def embed_passages(self, texts):
        self.calls += 1
        self.texts += len(texts)
        return self.inner.embed_passages(texts)

    def embed_query(self, text):
        return self.inner.embed_query(text)


def cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


# --- contrato do modelo real -------------------------------------------------------------
@needs_model
def test_real_vectors_follow_the_provider_contract(real):
    texts = ["O contrato de locação tem prazo de trinta meses.", "Receita de bolo de cenoura.", "Senha do wifi."]
    assert isinstance(real, EmbeddingProvider)
    assert real.model == MODEL_ID == "intfloat/multilingual-e5-small@614241f6" and real.dimensions == 384
    vectors = real.embed_passages(texts)
    validate_vectors(real, texts, vectors)  # quantidade, dimensão 384 e valores finitos
    assert len(vectors) == 3 and all(len(v) == 384 for v in vectors)
    for vector in vectors + [real.embed_query("quanto dura o aluguel?")]:
        assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, abs_tol=1e-5)  # normalizado em L2
    assert real.embed_passages([]) == []


@needs_model
def test_real_embeddings_are_deterministic_and_do_not_depend_on_batch_padding(real):
    short, long_ = "Senha do wifi.", " ".join(["O contrato de locação residencial tem prazo de trinta meses."] * 12)
    assert real.embed_passages([short]) == real.embed_passages([short])
    together = real.embed_passages([short, long_])  # o curto é preenchido até o tamanho do longo
    alone = [real.embed_passages([short])[0], real.embed_passages([long_])[0]]
    assert all(cosine(a, b) > 0.9999 for a, b in zip(together, alone))  # a máscara de atenção neutraliza o preenchimento


@needs_model
def test_real_provider_applies_the_e5_prefixes(real, monkeypatch):
    seen: list[list[str]] = []

    class Spy:
        def __init__(self, inner):
            self._inner = inner

        def encode_batch(self, texts):
            seen.append(list(texts))
            return self._inner.encode_batch(texts)

    monkeypatch.setattr(real, "_tokenizer", Spy(real._tokenizer))
    real.embed_passages(["um trecho", "outro trecho"])
    real.embed_query("uma pergunta")
    assert seen == [["passage: um trecho", "passage: outro trecho"], ["query: uma pergunta"]]
    assert cosine(real.embed_passages(["senha do wifi"])[0], real.embed_query("senha do wifi")) < 0.9999


@needs_model
def test_real_provider_truncates_very_long_text_instead_of_failing(real):
    vector = real.embed_passages(["palavra " * 5000, "Texto com acentuação: ação, coração, não, é."])
    assert len(vector) == 2 and all(math.isfinite(x) for v in vector for x in v)


@needs_model
def test_real_provider_runs_on_cpu_only_and_the_instance_is_reused(real):
    assert real._session.get_providers() == ["CPUExecutionProvider"]  # sem o provedor de nuvem que o onnxruntime lista
    built = []
    original = embedding_local.LocalOnnxEmbeddingProvider.__init__

    def counting_init(self, *args, **kwargs):
        built.append(1)
        original(self, *args, **kwargs)

    embedding_local.LocalOnnxEmbeddingProvider.__init__ = counting_init
    try:
        again = embedding_local.get_local_provider(local_settings())
        via_factory = build_provider(local_settings())
    finally:
        embedding_local.LocalOnnxEmbeddingProvider.__init__ = original
    assert again is real and via_factory is real and built == []  # nenhuma segunda carga do modelo


@needs_model
def test_loading_and_inference_open_no_network_connection(monkeypatch):
    def blocked(*_a, **_k):
        raise AssertionError("tentativa de conexão de rede")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    fresh = embedding_local.LocalOnnxEmbeddingProvider(MODEL_DIR)  # carga completa, com verificação dos hashes
    assert len(fresh.embed_passages(["Documento confidencial com dados pessoais."])[0]) == 384
    assert len(fresh.embed_query("dados pessoais")) == 384


# --- falhas sem vazamento de conteúdo ----------------------------------------------------------
SECRET = "CPF 123.456.789-00 da paciente Maria"


@needs_model
def test_inference_failure_hides_the_text_in_errors_and_logs(real, monkeypatch, caplog):
    class Broken:
        def run(self, *_a, **_k):
            raise RuntimeError(f"falha ao processar: {SECRET}")

    monkeypatch.setattr(real, "_session", Broken())
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(EmbeddingError) as raised:
            real.embed_passages([SECRET])
    assert "123.456" not in str(raised.value) and "Maria" not in str(raised.value)
    assert "RuntimeError" in str(raised.value) and raised.value.__suppress_context__
    assert "123.456" not in caplog.text and "Maria" not in caplog.text and "RuntimeError" in caplog.text


@needs_model
def test_tokenizer_failure_and_non_finite_output_are_reported_without_the_text(real, monkeypatch):
    class BadTokenizer:
        def encode_batch(self, texts):
            raise ValueError(f"texto inválido: {texts[0]}")

    monkeypatch.setattr(real, "_tokenizer", BadTokenizer())
    with pytest.raises(EmbeddingError) as raised:
        real.embed_query(SECRET)
    assert "123.456" not in str(raised.value) and "ValueError" in str(raised.value)
    monkeypatch.undo()

    real_run = real._session.run

    class NotANumber:
        def run(self, names, feed):
            out = real_run(names, feed)
            out[0][:] = float("nan")
            return out

        def __getattr__(self, name):
            return getattr(real._session, name)

    monkeypatch.setattr(real, "_session", NotANumber())
    with pytest.raises(EmbeddingError, match="não finitos"):
        real.embed_passages(["qualquer texto"])


def test_missing_files_wrong_hash_wrong_model_and_missing_packages_are_clear_config_errors(tmp_path, monkeypatch):
    with pytest.raises(EmbeddingConfigError, match="Arquivo do modelo ausente"):
        embedding_local.LocalOnnxEmbeddingProvider(tmp_path / "vazio")

    for item in MODEL_FILES:  # arquivos com o nome certo e conteúdo errado: recusados antes de carregar
        (tmp_path / item.name).write_bytes(b"conteudo errado")
    with pytest.raises(EmbeddingConfigError, match="SHA-256 de .* não confere"):
        embedding_local.LocalOnnxEmbeddingProvider(tmp_path)

    with pytest.raises(EmbeddingConfigError, match="só suporta intfloat/multilingual-e5-small"):
        embedding_local.get_local_provider(local_settings(embedding_model="outro/modelo"))

    monkeypatch.setitem(sys.modules, "onnxruntime", None)  # equivale a pacote não instalado
    with pytest.raises(EmbeddingConfigError, match="Dependências do provedor local ausentes"):
        embedding_local.LocalOnnxEmbeddingProvider(MODEL_DIR)


# --- instalação do modelo (sem rede: arquivos pequenos e servidor em 127.0.0.1) ---------------------
def tiny_files(monkeypatch, contents: dict[str, bytes]) -> None:
    monkeypatch.setattr(embedding_model, "MODEL_FILES", tuple(
        ModelFile(name, f"sub/{name}", hashlib.sha256(data).hexdigest()) for name, data in contents.items()
    ))


def test_install_from_a_local_copy_verifies_every_file_and_keeps_the_good_ones(tmp_path, monkeypatch):
    contents = {"model.onnx": b"pesos", "tokenizer.json": b"{}", "config.json": b"{\"a\": 1}"}
    tiny_files(monkeypatch, contents)
    source, destination = tmp_path / "origem", tmp_path / "modelo"
    (source / "sub").mkdir(parents=True)
    for name, data in contents.items():
        (source / "sub" / name).write_bytes(data)
    logs: list[str] = []
    install_model(destination, source_dir=source, log=logs.append)
    assert {p.name for p in destination.iterdir()} == set(contents) and not list(destination.glob("*.part"))
    embedding_model.verify_model_dir(destination)

    logs.clear()
    install_model(destination, source_dir=source, log=logs.append)  # repetir não copia de novo
    assert all("já presente" in line for line in logs)


def test_install_rejects_a_file_with_the_wrong_hash_and_never_leaves_it_in_place(tmp_path, monkeypatch):
    tiny_files(monkeypatch, {"model.onnx": b"pesos certos"})
    source = tmp_path / "origem"
    source.mkdir()
    (source / "model.onnx").write_bytes(b"pesos adulterados")
    with pytest.raises(ModelFileError, match="não confere"):
        install_model(tmp_path / "modelo", source_dir=source, log=lambda _l: None)
    assert list((tmp_path / "modelo").iterdir()) == []  # nem o arquivo final nem o .part

    with pytest.raises(ModelFileError, match="não encontrado"):
        install_model(tmp_path / "modelo2", source_dir=tmp_path / "inexistente", log=lambda _l: None)


def test_install_downloads_from_the_given_url_and_checks_the_hash(tmp_path, monkeypatch):
    payload = {"model.onnx": b"pesos baixados"}
    tiny_files(monkeypatch, payload)
    served = tmp_path / "servido"
    (served / "sub").mkdir(parents=True)
    (served / "sub" / "model.onnx").write_bytes(payload["model.onnx"])

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(served), **k)

        def log_message(self, *_a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url_for = lambda remote: f"http://127.0.0.1:{server.server_port}/{remote}"  # noqa: E731
        install_model(tmp_path / "modelo", url_for=url_for, log=lambda _l: None)
        assert (tmp_path / "modelo" / "model.onnx").read_bytes() == payload["model.onnx"]

        (served / "sub" / "model.onnx").write_bytes(b"conteudo trocado no servidor")
        with pytest.raises(ModelFileError, match="não confere"):
            install_model(tmp_path / "outro", url_for=url_for, log=lambda _l: None)
        assert list((tmp_path / "outro").iterdir()) == []
    finally:
        server.shutdown()


def test_the_pinned_revision_and_hashes_are_the_approved_ones():
    assert embedding_model.MODEL_REVISION == "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    assert embedding_model.MODEL_FILES[0].sha256 == "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665"
    assert embedding_model.huggingface_url("onnx/model.onnx").endswith(
        "/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3/onnx/model.onnx")


def test_download_command_reports_failure_with_exit_code_1(tmp_path, capsys):
    code = cli.main(["download-embedding-model", "--from-dir", str(tmp_path / "nada"), "--dest", str(tmp_path / "d")],
                    settings=Settings(_env_file=None))
    assert code == 1 and "Falha ao instalar o modelo" in capsys.readouterr().err


# --- integração com a geração de embeddings -----------------------------------------------------
@needs_model
def test_embed_document_stores_real_vectors_and_a_second_run_calls_nothing(db, real):
    provider = Counting(real)
    document = make_document(db, ["O contrato de locação residencial tem prazo de trinta meses.",
                                  "Para trocar a senha do wifi, abra o painel do roteador."])
    result = embed_document(db, provider, local_settings(), document.id)
    assert (result.status, result.generated, result.remaining) == ("completed", 2, 0)
    rows = rows_of(db, document.id)
    assert {r.model for r in rows} == {MODEL_ID} and all(len(r.embedding) == 384 for r in rows)
    assert rows[0].embedding == pytest.approx(real.embed_passages([
        "O contrato de locação residencial tem prazo de trinta meses."])[0], abs=1e-5)

    calls = provider.calls
    assert embed_document(db, provider, local_settings(), document.id).provider_calls == 0
    assert provider.calls == calls


@needs_model
def test_reprocessing_reuses_the_real_vectors_without_calling_the_model(client, dispatcher, session_factory, db, real):
    provider = Counting(real)
    runner_dispatcher(dispatcher, session_factory, provider)
    doc = ok(client, content=unique_pdf([long_text(), "Segunda página com texto suficiente para gerar um trecho."]))
    document_id = uuid.UUID(doc["id"])
    before = {r.content_sha256: r.embedding for r in rows_of(db, document_id)}
    assert len(before) >= 2 and provider.texts >= 2

    texts_before = provider.texts
    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 202
    db.expire_all()
    after = {r.content_sha256: r.embedding for r in rows_of(db, document_id)}
    assert after == before and provider.texts == texts_before  # mesmos vetores, nenhum texto reenviado ao modelo


@needs_model
def test_embed_pending_uses_the_real_provider_through_the_configured_factory(db, session_factory, capsys):
    document = make_document(db, ["Painéis solares reduzem a conta de luz.", "A taxa Selic é a taxa básica de juros."])
    code = cli.main(["embed-pending"], session_factory=session_factory, settings=local_settings(), sleep=Sleeps())
    assert code == 0 and "2 vetor(es) gerado(s)" in capsys.readouterr().out
    assert {r.model for r in rows_of(db, document.id)} == {MODEL_ID}


@needs_model
def test_api_startup_with_the_local_provider_resumes_pending_embeddings(db, session_factory, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    document = make_document(db, texts_for(3))
    monkeypatch.setattr("app.main.SessionLocal", session_factory)
    for name, value in {"EMBEDDINGS_ENABLED": "true", "EMBEDDING_PROVIDER": "local",
                        "EMBEDDING_MODEL_PATH": str(MODEL_DIR)}.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        with TestClient(app):
            assert app.state.embedding_dispatcher is not None
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                with session_factory() as check:
                    if len(rows_of(check, document.id)) == 3:
                        break
                time.sleep(0.1)
        with session_factory() as check:
            assert {r.model for r in rows_of(check, document.id)} == {MODEL_ID}
    finally:
        get_settings.cache_clear()


@needs_model
@requires_postgres  # a busca textual com termo usa o tsvector do PostgreSQL
def test_keyword_search_is_unchanged_when_embeddings_exist(client, dispatcher, session_factory, real):
    doc = ok(client, content=unique_pdf(["O contrato de locação residencial tem prazo de trinta meses."]))
    before = client.get("/api/search", params={"q": "locação"}).json()
    assert [i["title"] for i in before["items"]] == [doc["title"]]  # a busca por palavras-chave acha o documento

    runner_dispatcher(dispatcher, session_factory, real)
    with session_factory() as db:
        assert embed_document(db, real, local_settings(), uuid.UUID(doc["id"])).status == "completed"
    after = client.get("/api/search", params={"q": "locação"}).json()
    assert after == before  # busca por palavras-chave continua sendo a única, com ou sem vetores
    assert client.get("/api/search", params={"q": "locação", "mode": "semantic"}).json() == before  # sem modo semântico ainda


# --- avaliação de qualidade (guarda de regressão, não prova de qualidade) -----------------------------
def evaluate(provider) -> dict:
    ids = list(PASSAGES)
    vectors = provider.embed_passages([PASSAGES[i] for i in ids])
    rows = []
    for query, relevant, kind in QUERIES:
        q = provider.embed_query(query)
        sims = {i: cosine(q, v) for i, v in zip(ids, vectors)}
        order = sorted(sims, key=sims.get, reverse=True)
        rows.append((kind, order.index(relevant) + 1, sims[relevant] - max(s for i, s in sims.items() if i != relevant)))
    out_q = provider.embed_query(OUT_OF_CORPUS)
    summary = {}
    for kind in ("parafrase", "palavras", "entre_idiomas", "todas"):
        subset = [r for r in rows if kind == "todas" or r[0] == kind]
        summary[kind] = {"n": len(subset), "top1": sum(r[1] == 1 for r in subset),
                         "mrr": sum(1 / r[1] for r in subset) / len(subset),
                         "margem": sum(r[2] for r in subset) / len(subset)}
    summary["fora_do_corpus_max_sim"] = max(cosine(out_q, v) for v in vectors)
    return summary


@needs_model
def test_retrieval_quality_on_the_portuguese_sample_beats_the_lexical_baseline(real, capsys):
    from app.services.embeddings import FakeEmbeddingProvider

    model, baseline = evaluate(real), evaluate(FakeEmbeddingProvider())
    with capsys.disabled():
        print("\n  qualidade (amostra: 14 trechos, 16 consultas)")
        for name, result in (("E5 local", model), ("falso lexical", baseline)):
            print(f"  {name:14} " + " | ".join(
                f"{k}: top1 {v['top1']}/{v['n']} MRR {v['mrr']:.3f}" for k, v in result.items() if isinstance(v, dict)))
        print(f"  similaridade máxima de uma consulta SEM resposta no corpus: {model['fora_do_corpus_max_sim']:.3f}")
    # Pisos de regressão abaixo do que foi observado (15/16, MRR 0,958), não metas de qualidade.
    assert model["todas"]["top1"] >= 13 and model["todas"]["mrr"] >= 0.9
    assert model["parafrase"]["top1"] >= 11
    assert model["parafrase"]["mrr"] - baseline["parafrase"]["mrr"] > 0.2  # entende paráfrases que o lexical não pega
    assert model["fora_do_corpus_max_sim"] > 0.7  # limitação: uma consulta sem resposta também tem similaridade alta


@needs_model
@requires_postgres
def test_real_vectors_ranked_by_cosine_distance_in_postgres(db, real):
    from sqlalchemy import select as sa_select

    ids = list(PASSAGES)
    document = make_document(db, [PASSAGES[i] for i in ids])
    assert embed_document(db, real, local_settings(), document.id).status == "completed"
    for query, relevant, kind in QUERIES:
        if kind != "parafrase":
            continue
        distance = ChunkEmbedding.embedding.cosine_distance(real.embed_query(query))
        top = db.execute(sa_select(DocumentChunk.content, distance)
                         .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
                         .order_by(distance).limit(1)).first()
        assert top[0] == PASSAGES[relevant], query
