# Desenvolvimento

## Variáveis de ambiente

Veja `.env.example`. O backend lê `.env` da raiz do projeto (ou de `backend/`). Nunca versione o `.env`.

## Banco de dados

```bash
docker compose up -d db      # sobe PostgreSQL + pgvector
docker compose logs -f db
docker compose down          # para (os dados ficam no volume pgdata)
docker compose down -v       # para e APAGA os dados
```

## Documentos (PDF)

Dependências Python novas: `pypdf` (extração) e `python-multipart` (upload), ambas em `backend/requirements.txt`; rode `pip install -r requirements.txt` ao atualizar. Não há dependência de sistema (nada de poppler, tesseract ou similar).

O armazenamento fica em `DOCUMENT_STORAGE_PATH` (veja o README). Em desenvolvimento, apagar `backend/storage/` sem apagar a tabela `documents` deixa registros apontando para arquivos ausentes: a API responde 404 no download (“arquivo original não encontrado”) e a exclusão do registro continua possível. Apagar o banco sem apagar o diretório deixa arquivos órfãos; nenhum comando faz essa limpeza automaticamente.

Se a `0006` abortar dizendo que existem documentos com o mesmo SHA-256, são cópias importadas na Fase 3.1: exclua as que sobrarem (pela interface ou `DELETE /api/documents/{id}`) e rode `alembic upgrade head` de novo. A migration não altera nada antes de abortar.

Ao rodar a API, use **um único processo** (`uvicorn app.main:app`, sem `--workers`), por causa da retomada na inicialização. O reload do desenvolvimento (`--reload`) reinicia o processo e dispara a retomada a cada recarga, o que é seguro (apenas reprocessa o que estava `pending`/`processing`).

Para experimentar limites sem editar o `.env`: `MAX_UPLOAD_MB=1 uvicorn app.main:app --reload`.

## Migrations

```bash
cd backend && source .venv/bin/activate
alembic upgrade head                          # aplica
alembic downgrade -1                          # desfaz a última
alembic revision --autogenerate -m "mensagem" # nova migration (revise o arquivo gerado)
```

## Testes

**Backend.** `pytest` sem variáveis usa SQLite em memória: valida CRUD, integridade (FKs ligadas via PRAGMA), filtros e ausência de N+1. Os testes de busca com termo exigem PostgreSQL e são pulados.

Para rodar tudo no PostgreSQL, crie um banco descartável terminado em `_test` e aponte `TEST_DATABASE_URL` para ele:

```bash
docker compose exec db createdb -U "$POSTGRES_USER" secondbrain_test
cd backend && source .venv/bin/activate
TEST_DATABASE_URL=postgresql+psycopg://USUARIO:SENHA@localhost:5432/secondbrain_test pytest
```

A suíte **apaga e recria as tabelas** desse banco a cada teste e recusa nomes sem o sufixo `_test`, para não tocar nos seus dados.

O banco de teste do PostgreSQL precisa ter o pgvector disponível (a suíte roda `CREATE EXTENSION IF NOT EXISTS vector` antes de criar as tabelas, por causa de `chunk_embeddings`). O teste da cadeia de migrations `0001` a `0007` (`test_migration_chain_reaches_0007_and_matches_the_models`) **apaga o esquema `public` inteiro** do banco de teste e o recria pelas migrations.

**Interface e execução como aplicativo.** `src/pages/dashboard.test.tsx` cobre o dashboard (dados reais, contagens por tipo e estado, polling, vazio, erro, API offline e banco indisponível); o helper `renderApp(path, { withBackend: true })` inclui o `BackendProvider`, como o `App.tsx`. No backend, `tests/test_frontend_serving.py` (interface servida pela API, sem banco) e `tests/test_check_db.py` (conferência somente leitura do banco, com SQLite em arquivo temporário e uma URL de PostgreSQL inacessível). Para ver o aplicativo funcionando sem PostgreSQL, dá para usar um SQLite descartável com o esquema criado pelos modelos (`Base.metadata.create_all`) e `DATABASE_URL=sqlite:///…`, mas a busca por termo responde 503 nesse caso.

**Embeddings nos testes.** `tests/test_embeddings.py` e `tests/test_embedding_tasks.py` usam só o `FakeEmbeddingProvider` (sem rede e sem modelo). `tests/test_embedding_local.py` usa o modelo real e é **ignorado** quando as dependências de `requirements-embeddings.txt` ou os arquivos de `backend/models/multilingual-e5-small/` não existem; os testes de instalação do modelo rodam sempre, com arquivos pequenos e um servidor em `127.0.0.1`. Para rodar só o modelo real: `pytest tests/test_embedding_local.py -s` (o `-s` mostra a tabela de qualidade). Os pisos do teste de qualidade são guardas de regressão numa amostra pequena (`tests/quality_data.py`), não uma meta de qualidade.

**Processamento assíncrono nos testes.** `tests/conftest.py` injeta um `TestDispatcher` no lugar do pool real (`DOCUMENT_PROCESSING_ENABLED=false` nos testes). Por padrão ele executa na hora (o processamento termina antes de o POST voltar); com `dispatcher.manual()` as tarefas ficam na fila e o teste decide quando rodar (`run_all()`), o que permite observar `pending`, `processing` (espiando dentro da extração) e `failed`. `tests/test_document_processing.py` cobre estados, falhas, reprocessamento, troca atômica, pedidos repetidos, exclusão, retomada, `process-pending` e sessões; os testes com threads reais (pool, reprocessamento simultâneo, "documento lento não bloqueia os outros") exigem PostgreSQL. Os helpers `ok()` leem o estado final com um GET depois do upload, porque a resposta do POST é `pending`.

**Trechos e duplicatas nos testes.** `tests/test_chunker.py` testa o segmentador sem banco (limites, sobreposição, ordem, páginas, acentos, configuração). `test_document_chunks.py` cobre a geração no upload, o endpoint, falhas injetadas, reprocessamento, o comando `rebuild-chunks` e as restrições do banco; `test_document_duplicates.py` cobre o 409, a corrida (simulada em qualquer banco e real, com threads, só no PostgreSQL); `test_document_metadata.py` cobre a edição. Os testes que precisam de vários documentos usam `unique_pdf` (bytes diferentes a cada chamada), porque o mesmo arquivo agora é recusado.

**Documentos nos testes.** Cada teste recebe um diretório temporário (`DOCUMENT_STORAGE_PATH`, fixture automática em `tests/conftest.py`), então o armazenamento real nunca é tocado. PDFs de teste são gerados em memória por `tests/pdfs.py` (`make_pdf`, PDF corrompido, protegido por senha, sem texto); não há arquivos binários no repositório. As falhas são injetadas com `monkeypatch` (extração, commit do banco, `os.link`, `os.replace`) e os testes conferem que não sobram registros nem arquivos (`stored_files`).

**Migration 0006 sem pgvector.** A cadeia desde um banco vazio para na `0002`. Sem `stamp`, a `0006` pode ser validada sobre um esquema equivalente ao da `0005`: `alembic upgrade 0001`, executar o `upgrade()` de `0003`, `0004` e `0005` (por `alembic.operations.Operations`), inserir dados e então o `upgrade()`/`downgrade()` da `0006`. Isso valida o DDL e a preservação de dados, **não** a cadeia completa. O SQL pode ser conferido com `alembic upgrade 0005:0006 --sql`.

**Migrations.** Teste em banco descartável, nunca no que tem dados: `alembic upgrade head`, e para validar a reversão `alembic downgrade 0002` seguido de `alembic upgrade head`.

**Frontend.** `npm test` (Vitest + Testing Library, jsdom). A camada HTTP (`services/api.ts`) é substituída por mocks; os testes exercitam as telas pela interface (rótulos, botões, navegação).

## Convenções

- Backend: um módulo por domínio em `models/`, `schemas/`, `services/` e `api/routes/`.
- Frontend: CSS Modules por componente; valores visuais sempre via tokens (`var(--...)`).
- Frontend: dados remotos com `useAsync(fetcher, key)`; a `key` deve conter tudo de que o `fetcher` depende.
- Mudou algo que compõe o texto pesquisável de uma nota? Chame `search.refresh_notes(db, ids)` na mesma transação.
- Nunca edite migrations já criadas; crie uma nova revisão.
- Texto de documentos: remova caracteres NUL antes de gravar (o PostgreSQL recusa), e recalcule o vetor com `search.refresh_documents`.
- Nada fora de `services/storage.py` deve montar caminhos de arquivo de documento.
- Comunicação com a API apenas por `src/services/api.ts`.
