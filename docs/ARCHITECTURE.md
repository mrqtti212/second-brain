# Arquitetura

## Visão geral

```
Navegador (React/Vite :5173)
   │  /api/*  (proxy do Vite em desenvolvimento)
   ▼
FastAPI (:8000)  ──►  PostgreSQL 16 + pgvector (:5432)
```

## Backend (`backend/app`)

| Pasta | Responsabilidade |
|---|---|
| `api/` | roteadores HTTP finos (`health`, `notes`, `documents`, `organization`, `search`) agregados em `router.py`. `organization.py` gera o CRUD de categorias, projetos e etiquetas por uma fábrica de rotas |
| `core/` | configuração (`config.py`, Pydantic Settings) e erros de domínio (`errors.py`: 404, 409, 413, 415, 422, 500, 503), convertidos em resposta HTTP por um handler único em `main.py` |
| `db/` | engine, sessão (`get_db`) e `Base` declarativa |
| `models/` | modelos SQLAlchemy 2: `Note`, `Document`, `DocumentPage`, `DocumentChunk`, `Category`, `Project`, `Tag` e as tabelas `note_tags` e `document_tags` |
| `schemas/` | contratos Pydantic de entrada e saída |
| `services/` | regras de negócio e acesso a dados, sem dependência de HTTP: `notes`, `documents`, `chunker`, `pdf`, `storage`, `organization` (CRUD genérico), `search` |

Fluxo de uma requisição: rota → valida com schema → chama service → service usa a sessão → resposta serializada pelo schema de saída.
Erros: os services lançam `AppError` (`NotFoundError`, `ConflictError`, `InvalidReferenceError`, `SearchUnavailableError`); o handler devolve `{"detail": ...}` com o código certo. Qualquer exceção não tratada vira 500 genérico, com stack trace apenas no log, sem expor SQL.

## Banco

- Chaves primárias em UUID (`uuid4` gerado pela aplicação).
- Timestamps com fuso (`timestamptz`); `updated_at` é atualizado pelo SQLAlchemy em cada UPDATE.
- Migrations em `backend/migrations/versions`:
  - `0001`: tabela `notes`.
  - `0002`: `CREATE EXTENSION vector`. Nenhuma coluna de embedding existe ainda.
  - `0003`: categorias, projetos, etiquetas, `note_tags` e as FKs de `notes`.
  - `0004`: `notes.search_vector` (tsvector) com índice GIN.
  - `0005`: `documents`, `document_pages`, `document_tags` e o índice GIN de documentos.
  - `0006`: `document_chunks` e índice único em `documents.sha256`.
- `db/init/01-extensions.sql` cria a extensão na primeira subida do contêiner.

### Relacionamentos e integridade (Fase 2)

- `notes.category_id` e `notes.project_id`: FK com `ON DELETE SET NULL`. Excluir categoria ou projeto desassocia as notas, nunca as apaga.
- `note_tags`: chave composta `(note_id, tag_id)` impede associação repetida; `ON DELETE CASCADE` nos dois lados remove só a linha de associação. Não sobram órfãos.
- Nomes únicos por índice em `lower(name)` (409 na API); `CHECK` contra nome em branco.
- As relações de `Note` usam `lazy="selectin"`: listar N notas custa uma consulta por relação, não N. Há teste que garante que a contagem de queries não cresce com o número de notas.
- PATCH de nota é parcial: `model_fields_set` distingue campo omitido (não muda) de `null` explícito (remove categoria/projeto).

### Documentos (Fase 3.1)

**Separação de responsabilidades.** O PDF original fica em disco (`services/storage.py`); o banco guarda metadados, estado e o texto extraído, separado por página (`document_pages`). O PDF nunca é armazenado em coluna. `storage_key` liga o registro ao arquivo e não é exposto pela API.

**Armazenamento local (`LocalStorage`).**
- O nome em disco é `<uuid4 hex>.pdf`, gerado pelo sistema. O nome enviado pelo usuário vai só para `original_filename` (sanitizado: sem diretórios, sem caracteres de controle ou aspas) e para o cabeçalho de download.
- `path_for(key)` aceita apenas o padrão `[0-9a-f]{32}.pdf` e confere que o caminho resolvido está dentro da raiz: uma chave adulterada no banco não chega ao sistema de arquivos.
- A gravação passa por um arquivo temporário em `.tmp/` (copiado em blocos de 1 MB, calculando SHA-256, tamanho e conferindo `%PDF-`) e só vira definitivo com `os.link`, que não sobrescreve. O temporário é removido em qualquer saída.
- A exclusão é em duas fases: renomear para `*.deleting` (reversível), confirmar a transação, apagar. Se o renome falha ou o commit falha, nada se perde e o arquivo volta ao lugar.

**Fluxo de importação (`services/documents.import_pdf`, síncrono só até aceitar o arquivo; ver "Processamento assíncrono").**
1. valida extensão e Content-Type, e as referências (categoria, projeto, etiquetas): nada gravado ainda;
2. grava no temporário, checando limite, vazio e assinatura (413/422);
3. abre o PDF com pypdf: estrutura inválida, senha ou páginas demais viram 422, sem registro nem arquivo;
4. se o SHA-256 já existe, recusa com 409 (checagem prévia; a corrida é decidida pelo índice único);
5. cria o registro `pending` (com `page_count`), move o arquivo para o destino, atualiza o vetor de busca (título, nome do arquivo e organização) e faz commit. Qualquer falha desse passo desfaz a transação e apaga o arquivo definitivo. A rota então envia o `document_id` ao despachante e responde 201.

Um middleware recusa, pelo `Content-Length`, uploads muito acima do limite antes de ler o corpo; a checagem exata fica no `storage`.
`has_text=false` em um documento `completed` indica PDF sem camada de texto.

### Trechos, metadados e duplicatas (Fase 3.2.1)

**Modelo.** `document_pages` segue como fonte do texto; `document_chunks` guarda uma cópia de cada trecho com `page_number`, `chunk_index` e `start_offset`/`end_offset` (posição no texto da página), então qualquer trecho é rastreável até a página e ao intervalo exato. A FK composta `(document_id, page_number)` → `document_pages` (`ON DELETE CASCADE`) faz o banco recusar trecho de página inexistente e apagar os trechos junto com a página ou o documento. Únicos `(document_id, chunk_index)` e `(document_id, page_number, start_offset)` impedem trechos repetidos; checks garantem contagem coerente com o conteúdo, offsets válidos e conteúdo não vazio. A ordem global (`chunk_index` acompanha `page_number`) é garantida pelo serviço e coberta por testes, não por trigger. Sem `token_count`, sem embeddings.

**Segmentador** (`services/chunker.py`): função pura, sem banco nem IA, configurada por `ChunkingConfig` (valores vindos de `Settings`). Não mistura páginas, prefere cortes naturais e mede tudo em caracteres. A estratégia completa está no README.

**Fluxo de importação.** Extrair texto → segmentar → gravar documento, páginas e trechos (nessa ordem, pois a FK dos trechos aponta para as páginas) → atualizar o vetor de busca → commit. Falha de extração ou segmentação = documento `failed` sem dados parciais; falha de gravação = rollback e remoção do arquivo. `rebuild_chunks` (idempotente, apaga e recria na mesma transação) e `python -m app.cli rebuild-chunks` cobrem documentos anteriores à fase e mudanças de configuração; não há reprocessamento automático nem endpoint.

**Duplicatas.** O SHA-256 é calculado durante a gravação do upload em arquivo temporário. Uma checagem prévia devolve `DuplicateDocumentError` (409, com `code` e `existing_document`; `AppError` ganhou campos extras na resposta) antes de qualquer gravação definitiva. Como duas requisições podem passar pela checagem ao mesmo tempo, a garantia real é o índice único em `sha256`: quem perde a corrida recebe `IntegrityError`, o serviço remove o arquivo que acabara de gravar e responde com o mesmo 409 apontando para o vencedor.

**Metadados.** `PATCH /api/documents/{id}` (`DocumentUpdate` com `extra="forbid"`) altera só título, categoria, projeto e etiquetas, valida as referências antes de gravar e recalcula o vetor de busca. Páginas, trechos, arquivo e hash não são tocados.

### Processamento assíncrono (Fase 3.2.2)

**Escolha.** Um `ThreadPoolExecutor` dentro do processo (`services/processing.py`), com o **banco como fonte da verdade**. Alternativas descartadas por ora: Redis/Celery/RabbitMQ (infraestrutura nova para um projeto local de um usuário), `BackgroundTasks` do FastAPI (roda no pool de threads das próprias requisições, sem limite próprio nem como pausar no desligamento) e `asyncio` (a extração é CPU-bound e bloqueante). O custo assumido é a durabilidade parcial descrita no README.

**Componentes.**
- `DocumentProcessor.process(document_id)`: abre uma sessão própria por chamada e executa `process_document`.
- `ThreadPoolDispatcher` (produção, `DOCUMENT_WORKERS` threads), `InlineDispatcher` (CLI) e um despachante de teste nos testes. A API só depende do protocolo `Dispatcher.submit(document_id)` (injetado por `api/deps.get_dispatcher`), então trocar o pool por um worker externo não mexe nas rotas.
- `lifespan` (em `main.py`): cria o pool na inicialização, retoma documentos pendentes (`recover_interrupted`) e encerra o pool ao desligar, sem esperar tarefas em curso.

**`process_document`.** (1) `claim`: `UPDATE ... SET status='processing' WHERE id=:id AND status='pending'`; zero linhas = não faz nada. (2) Fora de qualquer transação: lê o PDF, extrai o texto por página e segmenta. (3) `_store_result`: numa transação, apaga trechos e páginas antigos, insere as novas páginas, faz `flush` (a FK dos trechos exige as páginas), insere os trechos, atualiza `page_count`/`has_text`/`error_message`, marca `completed` e recalcula o vetor de busca; um `commit` no fim. (4) Qualquer exceção em (2) ou (3) faz rollback e um `UPDATE ... WHERE status='processing'` registra `failed` e a mensagem; se nem isso for possível, o documento permanece `processing` e é retomado na próxima inicialização.

**Reprocessamento.** `request_reprocess` faz `UPDATE ... WHERE status IN ('completed','failed') SET status='pending'`; `rowcount == 1` decide quem enfileira. Não exige migration: `status` e `updated_at` já existiam e o CHECK de `status` já aceitava os quatro valores.

**Interface.** `usePolling` repete a consulta só enquanto o estado é `pending`/`processing`; limpa o timer ao desmontar e pausa após falhas seguidas. `useAsync` agora mantém o último dado bom quando uma recarga falha, para um erro de rede não apagar a tela. A seção de texto extraído e a lista de trechos recarregam quando `status`/`updated_at`/`chunk_count` mudam.

**Preparação para a Fase 3.2.3.** `document_pages` é a unidade natural para dividir em trechos e gerar embeddings (uma tabela de trechos pode referenciar `document_id` e `page_number`), e `sha256` permite detectar duplicatas. Nada de IA foi adicionado: a Fase 3.1 não depende de pgvector.

### Busca textual

`search_vector` é persistido e indexado (GIN) em `notes` e em `documents`. Pesos: título (A), nomes de categoria, projeto e etiquetas, mais o nome do arquivo nos documentos (B), conteúdo (C; nos documentos, o texto das páginas, limitado a 400 mil caracteres por causa do limite do `tsvector`). Config `portuguese`.
`services/search.py` recalcula o vetor com um único `UPDATE` sempre que algo que o compõe muda: criar/editar nota ou documento, mudar etiquetas, renomear ou excluir categoria, projeto ou etiqueta (as notas e documentos afetados são identificados antes da exclusão).
`GET /api/search` junta notas e documentos com `UNION ALL` de candidatos (tipo, id, relevância, data), ordena e pagina a união, e só então carrega as entidades e calcula os trechos (`ts_headline`) das linhas da página. O parâmetro `type` escolhe os ramos da união.
A consulta usa `websearch_to_tsquery` com o termo como parâmetro (sem concatenação de SQL, sem erro de sintaxe para entrada arbitrária), ordena por `ts_rank_cd` e monta o trecho com `ts_headline` só para as linhas da página. Filtros de etiqueta usam `EXISTS`, o que evita notas duplicadas. A alternativa de triggers no banco foi descartada nesta fase para manter a lógica testável junto ao código; a limitação está registrada no README.

## Frontend (`frontend/src`)

| Pasta | Conteúdo |
|---|---|
| `styles/` | `tokens.css` (cores, tipografia, espaçamento, raios, sombras) e `global.css` |
| `components/` | componentes reutilizáveis, cada um com seu CSS Module (`Field`, `Chip`, `ConfirmDialog`, `StateBlock`, `NoteCard`, `Highlight`…) |
| `layouts/` | `AppLayout` (sidebar fixa no desktop, gaveta no mobile, topbar) |
| `pages/` | uma página por rota |
| `routes/` | definição do React Router |
| `features/` | `backend/` (estado do /health), `library/` (formulário de nota), `organization/` (gerenciador de categorias/projetos/etiquetas), `dashboard/` (dados de demonstração) |
| `hooks/` | `useAsync` (carregamento/erro/recarga por chave), `useDebouncedValue` |
| `services/` | cliente HTTP (`api.ts`) |
| `types/` | tipos TypeScript |

Não há cache global de notas: cada tela busca o que precisa pela API (`useAsync`), e a fonte da verdade é o backend. Sem `localStorage`.
Rotas: `/documents` (lista com busca por nome e filtros), `/documents/new` (importação), `/documents/:id` (metadados, texto por página, download, exclusão), `/` dashboard, `/library` biblioteca (busca e filtros na URL: `q`, `type`, `category`, `project`, `tag`, `page`; notas e documentos juntos), `/notes/new`, `/notes/:id`, `/notes/:id/edit`, `/organize`.
O editor de nota inicia o formulário com os valores da nota e envia todos os campos no PATCH, então categoria, projeto e etiquetas são preservados ao editar só o texto. O sucesso só é exibido depois da resposta da API.
Dados de demonstração vivem em `features/dashboard/demoData.ts` e são sinalizados como temporários na interface.

## Pontos de extensão previstos

- Embeddings: nova tabela/coluna `vector(N)` com índice HNSW, populada por um service em `services/`.
- Provedor de IA: interface em `services/` com implementação trocável, configurada por variáveis de ambiente.
- Documentos: novo modelo, rota de upload e extração de texto antes de gerar embeddings.
