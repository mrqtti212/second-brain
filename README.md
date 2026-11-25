# Second Brain

Aplicação web pessoal para guardar, organizar e (nas próximas fases) consultar conhecimento com IA.
Roda localmente, sem Supabase, Firebase ou outro serviço externo no lugar do backend.

**Estado atual: Fase 3.2.2 (processamento assíncrono e reprocessamento seguro).** O upload agora só aceita e registra o PDF (`pending`); a extração do texto e a geração de trechos acontecem em segundo plano, com estado consultável, reprocessamento pela API e pela interface e troca atômica do resultado. A execução em segundo plano é um pool de threads **dentro do processo, não uma fila durável** (veja "Processamento em segundo plano").

**Embeddings em andamento (Etapas A, B e C).** Existem a tabela `chunk_embeddings`, a geração em segundo plano, o comando `embed-pending` e um provedor local (modelo `intfloat/multilingual-e5-small` em CPU, sem enviar texto para fora). Desligado por padrão e **sem busca semântica ainda**: a busca continua só por palavras-chave (ver "Embeddings dos trechos").

**Fase 3.2.1 (estrutura de documentos: trechos, metadados e duplicatas).** Sobre a Fase 3.1 (importação de documentos), cada PDF passa a ser dividido em trechos (chunks) rastreáveis até a página de origem, o título e a organização do documento podem ser editados depois da importação, e o mesmo arquivo (SHA-256) não é importado duas vezes. **Ainda não existem embeddings, busca semântica, RAG nem OCR.**

**Fase 3.1.** Importação de PDFs com armazenamento local do original e do texto extraído (por página) no PostgreSQL, listagem, visualização, download, exclusão e busca integrada às notas. Vem sobre a Fase 2 (notas, categorias, projetos, etiquetas e busca em português com índice GIN) e a Fase 1 (FastAPI, React, Alembic, pgvector preparado).
Não há autenticação, OCR, busca semântica nem integração com IA generativa ainda. A geração de embeddings dos trechos e o provedor local existem, mas vêm desligados por padrão e a busca continua só por palavras-chave (ver "Embeddings dos trechos"). O dashboard mostra apenas dados reais da API (contagens, itens recentes e PDFs em processamento); com a API ou o banco fora do ar, ele diz o que fazer em vez de exibir exemplos. O antigo bloco "Assistente de IA" (que não fazia nada) foi removido e só volta quando houver uma função real por trás.

## Stack

| Camada | Tecnologias |
|---|---|
| Frontend | React 19, TypeScript, Vite, React Router, CSS Modules + design tokens, lucide-react |
| Backend | Python 3.11+ (testado com 3.13), FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, psycopg 3, pypdf (extração de texto), python-multipart (upload) |
| Banco | PostgreSQL 16 + pgvector 0.6.0 (imagem `pgvector/pgvector:0.6.0-pg16`) |
| Testes | pytest (backend), Vitest + Testing Library (frontend), ESLint + `tsc` |

## Pré-requisitos

Node.js 20+ e npm, Python 3.11+, Docker com Compose (para o banco) e Git.

## Instalação

```bash
cp .env.example .env
# edite .env e troque POSTGRES_PASSWORD (e a mesma senha em DATABASE_URL)
```

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```bash
cd frontend
npm install
```

## Trechos (chunks) dos documentos

Depois de extrair o texto, cada página é dividida em trechos guardados em `document_chunks`, para servirem de unidade de recuperação em fases futuras. Os embeddings desses trechos são opcionais e vêm desligados por padrão (ver "Embeddings dos trechos"); **ainda não há busca semântica nem IA generativa.** A busca textual continua usando o texto das páginas, não os trechos.

**Estratégia** (`backend/app/services/chunker.py`, função pura e testada):
- cada página é segmentada separadamente: um trecho **nunca mistura páginas** e a sobreposição só existe dentro da mesma página;
- no máximo `CHUNK_MAX_CHARS` caracteres por trecho; o corte é escolhido na segunda metade da janela, preferindo parágrafo (linha em branco), depois fim de frase, quebra de linha e espaço; palavras não são cortadas (só um "token" maior que a janela inteira, como uma URL gigante, é cortado no meio);
- o trecho seguinte começa até `CHUNK_OVERLAP_CHARS` antes do fim do anterior, no início de uma palavra (a sobreposição real pode ser um pouco menor);
- páginas com menos de `CHUNK_MIN_CHARS` caracteres úteis são ignoradas; nunca há trecho vazio;
- `content` é exatamente `texto_da_página[start_offset:end_offset]`, sem normalização, e não começa nem termina com espaço em branco.

**Consultar:** `GET /api/documents/{id}/chunks?page_number=2&limit=50&offset=0`; `chunk_count` aparece nos metadados do documento. Na interface, a página do documento tem a seção "Trechos" com a página de origem de cada um.

**Consistência.** Páginas e trechos são gravados na mesma transação do documento. Se a segmentação falhar, o documento fica `failed` (sem páginas nem trechos, original preservado); se a gravação falhar, tudo é desfeito, inclusive o arquivo.

**Documentos já existentes.** Os trechos só são criados para novos uploads. Para os anteriores à fase 3.2.1, ou para aplicar novos limites:

```bash
cd backend && source .venv/bin/activate
python -m app.cli rebuild-chunks --missing-only   # só documentos sem trechos
python -m app.cli rebuild-chunks --document-id UUID
python -m app.cli rebuild-chunks --all

# processa agora o que ficou pending (ex.: a API caiu com a fila cheia)
python -m app.cli process-pending
```

O comando é idempotente (apaga e recria os trechos do documento na mesma transação; se falhar, os antigos ficam) e **não** altera páginas, texto, arquivo ou metadados.

## Armazenamento de documentos

Os PDFs originais ficam em disco, em `DOCUMENT_STORAGE_PATH` (padrão `./storage/documents`, relativo a `backend/`; já está no `.gitignore`). O diretório é criado automaticamente. Para usar outro local, defina a variável no `.env` com um caminho absoluto.

| Variável | Padrão | Função |
|---|---|---|
| `DOCUMENT_STORAGE_PATH` | `./storage/documents` | onde ficam os PDFs originais |
| `MAX_UPLOAD_MB` | `20` | tamanho máximo do arquivo (1 a 500) |
| `MAX_DOCUMENT_PAGES` | `500` | máximo de páginas por PDF |
| `DOCUMENT_WORKERS` | `2` | documentos processados ao mesmo tempo (pool de threads) |
| `DOCUMENT_PROCESSING_ENABLED` | `true` | liga o processamento em segundo plano (sem ele, o upload responde 503) |
| `RECOVER_ON_STARTUP` | `true` | reenfileira `pending`/`processing` ao iniciar (processo único) |
| `CHUNK_MAX_CHARS` | `1200` | tamanho máximo de cada trecho (caracteres) |
| `CHUNK_OVERLAP_CHARS` | `200` | sobreposição entre trechos da mesma página (menor que o máximo) |
| `CHUNK_MIN_CHARS` | `50` | páginas com menos texto útil que isso não geram trechos |

Os nomes em disco são gerados pelo sistema (`<uuid>.pdf`); o nome enviado pelo usuário só é guardado no banco, para exibição e download. Faça backup do diretório junto com o banco: o banco guarda o texto e os metadados, o disco guarda o original.

## Executar

1. Banco de dados (na raiz do projeto):

```bash
docker compose up -d db
```

2. Migrations e API (em `backend/`, com o venv ativo):

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

3. Frontend (em `frontend/`):

```bash
npm run dev
```

Acesse http://localhost:5173. A documentação interativa da API fica em http://localhost:8000/docs.
O Vite encaminha `/api` para o backend (`VITE_BACKEND_PROXY`).

### Executar como aplicativo (uma porta só)

Depois de subir o banco e aplicar as migrations (passos 1 e 2 acima), um comando inicia a API **servindo a interface compilada**, em http://127.0.0.1:8000:

```bash
./scripts/run-app.sh            # compila a interface se frontend/dist não existir
./scripts/run-app.sh --build    # força nova compilação
```

O script **não aplica migrations, não instala dependências e não sobe o banco**. Ele confere o ambiente e o banco (somente leitura, com `python -m app.cli check-db`) e, se algo faltar, explica o que fazer e para sem alterar nada: venv do backend ausente, PostgreSQL inacessível, banco vazio ou com migrations atrasadas, `frontend/node_modules` ausente. `PORT` e `HOST` mudam o endereço (padrão `127.0.0.1:8000`, só local: não há autenticação, então não exponha a porta na rede). Por baixo, ele define `FRONTEND_DIST_PATH`, que faz a API servir `frontend/dist` (rotas do React e arquivos), sem tirar a prioridade de `/api`, `/docs` e `/openapi.json`; sem essa variável nada muda.

## Comandos úteis

| Onde | Comando | O que faz |
|---|---|---|
| raiz | `./scripts/run-app.sh` | inicia o aplicativo (API + interface) numa porta; confere o banco e para se faltar algo |
| `backend/` | `python -m app.cli check-db` | confere se o banco está acessível e com as migrations em dia (somente leitura) |
| `backend/` | `pytest` | testes da API em SQLite em memória (os testes de busca com termo são pulados) |
| `backend/` | `alembic revision --autogenerate -m "msg"` | gera migration |
| `backend/` | `TEST_DATABASE_URL=postgresql+psycopg://…/nome_test pytest` | suíte completa, incluindo a busca textual (ver [Testes](#testes)) |
| `frontend/` | `npm test` | testes de comportamento (Vitest) |
| `frontend/` | `npm run typecheck` | checagem de tipos |
| `frontend/` | `npm run lint` | ESLint |
| `frontend/` | `npm run build` | build de produção |

## API

Todas as rotas ficam sob `/api`. Erros usam `{"detail": "mensagem"}` (422 de validação traz uma lista).
Códigos: 200/201/202/204 sucesso, 404 recurso inexistente, 409 nome ou arquivo duplicado, 413 arquivo acima do limite, 415 formato não suportado, 422 dados ou PDF inválidos, referência inexistente, 500 falha de armazenamento, 503 busca com termo sem PostgreSQL ou processamento desativado.

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` | estado da API e do banco |
| GET | `/api/notes` | lista notas com categoria, projeto e etiquetas (`limit`, `offset`) |
| POST | `/api/notes` | cria nota (`title`, `content`, `category_id`, `project_id`, `tag_ids`) |
| GET | `/api/notes/{id}` | consulta nota |
| PATCH | `/api/notes/{id}` | edição parcial. Campos omitidos não mudam; `category_id`/`project_id` com `null` removem a associação; `tag_ids` substitui o conjunto |
| DELETE | `/api/notes/{id}` | exclui nota e suas associações |
| PUT | `/api/notes/{id}/tags/{tag_id}` | associa etiqueta (idempotente) |
| DELETE | `/api/notes/{id}/tags/{tag_id}` | desassocia etiqueta (idempotente) |
| GET/POST | `/api/categories` | lista / cria (`name`, `description`, `color`) |
| GET/PATCH/DELETE | `/api/categories/{id}` | consulta / edita / exclui |
| GET/POST | `/api/projects` | lista / cria (`name`, `description`) |
| GET/PATCH/DELETE | `/api/projects/{id}` | consulta / edita / exclui |
| GET/POST | `/api/tags` | lista / cria (`name`, `color`) |
| GET/PATCH/DELETE | `/api/tags/{id}` | consulta / edita / exclui |
| GET | `/api/search` | busca textual em notas e documentos, com filtros (abaixo) |
| POST | `/api/documents` | aceita um PDF (`multipart/form-data`) e o registra como `pending`; o processamento segue em segundo plano (abaixo) |
| POST | `/api/documents/{id}/reprocess` | pede novo processamento a partir do PDF original (`202`; `409` se já em andamento) |
| GET | `/api/documents` | lista documentos (`q`, `status`, `category_id`, `project_id`, `tag_id`, `sort`, `order`, `limit`, `offset`) |
| GET | `/api/documents/limits` | limites de importação (`max_upload_bytes`, `max_pages`) |
| GET | `/api/documents/{id}` | metadados do documento |
| PATCH | `/api/documents/{id}` | edita título, categoria, projeto e etiquetas. Omitido = não muda; `null` remove categoria/projeto; `tag_ids` substitui as etiquetas. Qualquer outro campo (id, arquivo, hash, estado) é recusado com 422 |
| GET | `/api/documents/{id}/content` | texto extraído, página por página |
| GET | `/api/documents/{id}/file` | baixa o PDF original |
| GET | `/api/documents/{id}/chunks` | trechos do documento, em ordem (`page_number`, `limit` até 200, `offset`) |
| DELETE | `/api/documents/{id}` | exclui registro, páginas, trechos, associações e arquivo |

Categorias, projetos e etiquetas retornam também `notes_count`. `color` é hexadecimal `#RRGGBB`. Nomes têm até 80 caracteres e são únicos sem diferenciar maiúsculas de minúsculas (409 se repetir).
Excluir categoria, projeto ou etiqueta **não exclui notas**: elas apenas perdem a associação.

### Busca: `GET /api/search`

| Parâmetro | Descrição |
|---|---|
| `q` | texto livre, até 200 caracteres. Aceita `"frase exata"`, `-exclusão` e `or`. Vazio ou só espaços lista tudo |
| `category_id`, `project_id` | filtra por categoria / projeto |
| `type` | `all` (padrão), `note` ou `document` |
| `tag_id` | repetível. O item precisa ter **todas** as etiquetas informadas |
| `limit` (1–100, padrão 20), `offset` | paginação |

Resposta: `{items, total, limit, offset}`. Cada item tem `type` (`note` ou `document`), `id`, `title`, `snippet`, `updated_at`, `category`, `project`, `tags` e `score` (relevância; `null` sem termo). Documentos trazem ainda `status`, `page_count` e `has_text`. Notas e documentos são ordenados juntos por relevância e paginados como uma lista só.
No `snippet`, os termos encontrados vêm entre os caracteres U+E000 e U+E001, para o cliente destacar sem interpretar HTML.

### Duplicatas: `409` com `code: duplicate_document`

O SHA-256 é calculado sobre os bytes recebidos, não sobre o nome. Se já existe um documento com o mesmo hash, o upload é recusado e **nada novo é gravado** (nem registro, nem arquivo; o documento existente não é alterado):

```json
{
  "detail": "Este arquivo já foi importado.",
  "code": "duplicate_document",
  "existing_document": {"id": "…", "title": "…", "original_filename": "…", "created_at": "…"}
}
```

Nomes diferentes com o mesmo conteúdo são duplicatas; arquivos que diferem em um único byte não são (PDFs "visualmente iguais" mas binariamente distintos são importados). A garantia vem de um **índice único em `documents.sha256`**: duas requisições simultâneas com o mesmo arquivo resultam em exatamente um `201` e um `409`. Documentos `failed` e sem texto também contam; para tentar de novo um arquivo que falhou, exclua o documento antes.

### Importar PDF: `POST /api/documents`

Campos do formulário: `file` (obrigatório, `.pdf` com `Content-Type: application/pdf`), `title` (opcional; padrão é o nome do arquivo sem extensão), `category_id`, `project_id` e `tag_ids` (repetível).

```bash
curl -F "file=@contrato.pdf;type=application/pdf" -F "title=Contrato" http://localhost:8000/api/documents
```

O upload devolve **201 logo depois de validar e guardar o arquivo**, com o documento em `status: "pending"` (e `Location: /api/documents/{id}`). O texto e os trechos ainda não existem nesse momento: acompanhe `GET /api/documents/{id}` até `completed` ou `failed`. Validações síncronas, nesta ordem: extensão e tipo declarado (415), tamanho (413), arquivo vazio, assinatura `%PDF-` nos primeiros 1024 bytes, duplicata por SHA-256 (409), estrutura legível, PDF sem senha e limite de páginas (422; é rápido e já informa `page_count`). O `Content-Type` do cliente nunca é a única checagem.

PDFs sem texto (digitalizados) terminam `completed` com `has_text: false`: não é erro, só não há o que pesquisar (não há OCR).

## Processamento em segundo plano

**Fluxo.** `POST /api/documents` grava o original, cria o registro `pending` e envia só o `document_id` a um pool de threads (`DOCUMENT_WORKERS`, padrão 2). Cada tarefa abre a **própria sessão** do banco, passa o documento para `processing`, extrai o texto, gera os trechos e grava tudo de uma vez.

```
        upload                  tarefa assume              extração + trechos ok
  ─────────────▶ pending ───────────────────▶ processing ─────────────────────▶ completed
                   ▲                               │                                │
                   │ reprocessar                   │ erro                           │
                   │ (failed ou completed)         ▼                                │
                   └────────────────────────────  failed ◀── nova tentativa falha ──┘
```

| Estado | Significado | Transições |
|---|---|---|
| `pending` | aceito, aguardando uma tarefa | → `processing` (tarefa assume) |
| `processing` | uma tarefa está extraindo e gerando trechos | → `completed` ou `failed` |
| `completed` | páginas e trechos gravados | → `pending` (reprocessamento pedido) |
| `failed` | erro registrado em `error_message`; o PDF original foi preservado | → `pending` (reprocessamento pedido) |

**Garantias de consistência.**
- **Uma execução por documento.** `pending → processing` é um `UPDATE ... WHERE status = 'pending'` (compare-and-set no banco): de duas tarefas para o mesmo documento, só uma assume; a outra não faz nada. Não há lock em memória.
- **Troca atômica.** A extração e a segmentação rodam fora de qualquer transação. Só depois, numa única transação, as páginas e os trechos antigos são apagados, os novos inseridos e o documento marcado `completed`. Qualquer erro desfaz tudo: **os dados anteriores continuam valendo** e o documento fica `failed`. A interface nunca mostra "Concluído" antes de páginas e trechos estarem gravados.
- **Original intocado.** O processamento só lê o PDF; falha, reprocessamento e exclusão não o corrompem. Falha tudo-ou-nada: um documento novo que falha fica sem páginas nem trechos.
- **Sessões.** Nenhuma sessão atravessa threads: a requisição usa a dela, cada tarefa abre e fecha a sua.
- **Mensagens seguras.** `error_message` traz uma frase em português com o tipo do erro (ex.: `Não foi possível extrair o texto do PDF (RuntimeError)`), nunca stack trace, caminho ou SQL; detalhes vão só para o log.
- **Exclusão** é permitida em qualquer estado: se o documento some durante o processamento, a tarefa percebe e não grava nada (sem páginas, trechos ou arquivos órfãos).
- **Duplicatas** continuam valendo enquanto o documento está `pending` ou `processing`.

**Reprocessar: `POST /api/documents/{id}/reprocess`.** Refaz a extração e os trechos a partir do PDF original.

| Situação | Resposta |
|---|---|
| `failed` ou `completed` | `202` com o documento em `pending`; o conteúdo atual segue disponível até a nova versão ficar pronta |
| `pending` ou `processing` | `409`, `code: "already_processing"`, nenhuma tarefa nova |
| documento inexistente | `404` |
| PDF original ausente do armazenamento | `409`, `code: "original_file_missing"`, sem expor caminhos |
| vários pedidos simultâneos | exatamente um `202`, os demais `409` |

Se a nova tentativa falhar, o documento fica `failed` com a mensagem `... A versão anterior foi mantida.`, páginas e trechos antigos intactos, e pode ser reprocessado de novo. Repetir o reprocessamento não duplica páginas nem trechos. O comando `rebuild-chunks` (só re-segmenta a partir das páginas, sem reler o PDF) e o reprocessamento compartilham `chunking_config` e `_chunk_rows`; a extração está em `services/pdf.py`, usada só pelo processamento.

**Acompanhar.** `GET /api/documents/{id}` (e a lista) trazem `status`, `error_message`, `page_count` e `chunk_count`; `GET /api/documents?status=pending` lista a fila. A interface consulta o documento a cada 2 s (a lista, a cada 3 s) **só enquanto há algo em andamento**, para ao chegar a um estado terminal e ao sair da página, e pausa após 5 falhas seguidas (botão "Atualizar agora").

### Durabilidade: o que NÃO é garantido

O pool de threads **não é uma fila durável**. A fila existe só na memória do processo:
- se a API cair ou for reiniciada, as tarefas ainda não executadas ou em andamento **somem**; o documento fica `pending`/`processing` no banco, com o PDF guardado, e nada o processa até a próxima etapa abaixo;
- ao **iniciar**, a API reenfileira os documentos `pending` e devolve os `processing` para `pending` (`RECOVER_ON_STARTUP=true`). Enquanto a API estiver fora, nada é processado;
- o comando `python -m app.cli process-pending` faz o mesmo à mão, sem a API (`--include-processing` também retoma `processing`, e só deve ser usado com a API parada);
- **suposição de processo único.** Com vários processos da API (ex.: `uvicorn --workers N`), a retomada na inicialização devolveria à fila documentos que outro processo está processando de verdade. O compare-and-set impede execução dupla do mesmo estado, mas não torna esse cenário seguro; rode com um único processo;
- a execução é "pelo menos uma vez": uma tarefa interrompida a meio é refeita do início, e como o resultado só é gravado ao final, refazer é seguro.

Se for preciso garantir processamento independente da vida da API (vários processos, filas persistentes, tentativas com espera), a evolução natural é um worker separado lendo a mesma tabela `documents` (o banco já é a fila) ou uma fila externa. Isso não foi feito nesta fase.

## Embeddings dos trechos (em desenvolvimento)

Desligados por padrão (`EMBEDDINGS_ENABLED=false`): nada é gerado e nenhuma tela ou rota muda. **Ainda não há busca semântica**: `/api/search` continua usando só palavras-chave, com ou sem vetores no banco. O `FakeEmbeddingProvider` (determinístico, lexical) continua disponível para desenvolvimento e testes (`EMBEDDING_PROVIDER=fake`).

### Provedor local (modelo em CPU)

Usa `intfloat/multilingual-e5-small` (licença MIT, **revisão fixa `614241f622f53c4eeff9890bdc4f31cfecc418b3`**, 384 dimensões), exportado em ONNX e executado com `onnxruntime` em `CPUExecutionProvider`.

```bash
cd backend
pip install -r requirements-embeddings.txt          # onnxruntime 1.32.0, tokenizers 0.23.3, numpy 2.5.5 (opcionais)
python -m app.cli download-embedding-model          # MANUAL: baixa 3 arquivos (~490 MB) e confere o SHA-256 de cada um
# sem rede, a partir de uma cópia local:  python -m app.cli download-embedding-model --from-dir /caminho/da/copia
# depois, no .env: EMBEDDINGS_ENABLED=true   e reinicie a API (ou rode: python -m app.cli embed-pending)
```

- **Dependências opcionais.** Quem não liga embeddings não precisa instalar nada disso: o provedor só importa os pacotes quando é criado e, se faltarem, explica o que instalar. O `pip install` do `requirements-embeddings.txt` também instala dependências indiretas (`flatbuffers`, `protobuf`, `huggingface-hub` e outras); o código do projeto **não** usa o `huggingface-hub` nem abre conexão de rede.
- **Arquivos do modelo.** Ficam em `backend/models/multilingual-e5-small/` (`EMBEDDING_MODEL_PATH`), ignorados pelo Git. O download é sempre um comando manual, nunca roda sozinho. Cada arquivo só é aceito depois de conferir o SHA-256 (`model.onnx`: `ca456c06…bc8665`). Na carga, os três hashes são conferidos de novo, e um arquivo adulterado ou incompleto é recusado.
- **Formato do modelo.** Trechos recebem o prefixo `passage: ` e consultas `query: `. O vetor é a média dos tokens ponderada pela máscara de atenção, normalizada em L2 (norma 1). Textos acima de 512 tokens são **truncados**; um trecho de 1200 caracteres tem em torno de 230 tokens.
- **Privacidade.** Nenhum texto de documento sai da máquina: o modelo é carregado de um caminho local, o provedor fixa `CPUExecutionProvider` (o `onnxruntime` também lista um provedor de nuvem, que não é usado) e há um teste que bloqueia conexões de rede durante a carga e a inferência. Os únicos dados que trafegam são os arquivos públicos do modelo, e só quando você roda o comando de download. Mensagens de erro e logs trazem só o **tipo** da exceção, nunca o texto.
- **Identificação.** Os vetores são gravados com `model = intfloat/multilingual-e5-small@614241f6`. Mudar a revisão do modelo cria outro identificador, então vetores de pesos diferentes nunca se misturam nem são reaproveitados.
- **Recursos.** Medido neste ambiente (4 CPUs, sem GPU): carga em cerca de 2,3 s, aproximadamente 32 trechos de 1200 caracteres por segundo e pico de memória perto de **1 GB**. A instância do modelo é carregada uma vez por processo e reutilizada. Uma API e um `embed-pending` rodando ao mesmo tempo carregam o modelo cada um (cerca de 1 GB cada).

### Qualidade: o que foi medido e o que não foi
Numa amostra mínima em português (14 trechos, 16 consultas, em `backend/tests/quality_data.py`, escrita antes dos resultados e sem ajustes depois), o modelo acertou o trecho relevante em 1º lugar em **15 de 16** consultas (MRR 0,958), contra 8 de 16 (MRR 0,614) do provedor falso lexical. Nas 13 paráfrases (quase sem palavras em comum com o trecho) foram 13 de 13, contra 6 de 13. O único erro foi uma consulta em português sobre um texto em **inglês**. Isto **não prova qualidade geral**:

- A amostra é pequena, curta e foi escrita por quem implementou. Não houve avaliação com documentos reais seus, e o modelo **não** foi comparado numericamente com a implementação de referência (PyTorch/sentence-transformers); a implementação própria de pooling e normalização foi validada por testes de propriedades e pelo ranking acima.
- As similaridades do E5 ficam concentradas em uma faixa alta (aqui, entre 0,8 e 0,9) e as margens entre acerto e erro são pequenas (cerca de 0,04). Uma consulta **sem resposta** no corpus teve similaridade máxima de 0,82, no mesmo patamar dos acertos: **não é possível usar um limiar de similaridade** para decidir "achou" ou "não achou". Só a ordem do ranking é informativa.
- O desempenho em outros assuntos, documentos longos, jargão técnico e entre idiomas ficou sem avaliação. Para busca por palavras exatas (nomes, códigos, números), a busca por palavras-chave continua a melhor opção, e é por isso que ela segue como padrão e a semântica/híbrida será opcional.

**Fluxo.** Quando o processamento deixa um documento `completed`, ele é enviado a um pool próprio (`EMBEDDING_WORKERS`, padrão 1) que roda `embed_document`. O documento e seus trechos já estão utilizáveis nesse momento, e uma falha do provedor **nunca** muda o estado do documento. Cada trecho recebe um vetor em `chunk_embeddings`, com o modelo, as dimensões e o SHA-256 do texto.

- **Estado derivado.** Um trecho está pendente quando não tem vetor do modelo atual. Não há coluna de estado nem fila própria: o banco é a fonte da verdade, então repetir ou retomar converge para o mesmo resultado.
- **Lotes.** Os textos vão ao provedor em lotes de `EMBEDDING_BATCH_SIZE`, e cada lote é confirmado sozinho. Uma falha no meio preserva os lotes anteriores, e a próxima execução continua do que falta.
- **Repetição controlada.** Só falhas passageiras (`EmbeddingTransientError`) são repetidas, até `EMBEDDING_MAX_ATTEMPTS` vezes, com espera de `EMBEDDING_RETRY_BACKOFF_SECONDS` que dobra a cada tentativa. Dimensão errada, contagem de vetores errada ou qualquer outro erro não são repetidos. Os logs e o resumo do comando trazem só ids e o **tipo** da exceção, nunca texto de documento.
- **Sem chamadas desnecessárias.** Antes de chamar o provedor, o vetor é copiado de qualquer trecho com o mesmo texto e o mesmo modelo (inclusive de outro documento), e textos repetidos no mesmo documento são enviados uma vez. No **reprocessamento** (e no `rebuild-chunks`), os trechos são recriados com ids novos, mas os vetores dos trechos de texto idêntico são copiados dentro da própria troca atômica. Reprocessar o mesmo PDF faz 0 chamadas ao provedor; se o PDF mudou, só os trechos novos são gerados.
- **Concorrência.** Neste processo, uma trava por documento faz a segunda tarefa simultânea desistir (`busy`). Entre processos (API e CLI ao mesmo tempo) a gravação usa `ON CONFLICT DO NOTHING`: nunca duplica nem quebra, no máximo repete uma chamada ao provedor.
- **Trocar de modelo** torna todos os trechos pendentes de novo e os vetores antigos são substituídos. A dimensão da coluna é fixa em 384; o provedor precisa produzir exatamente isso.

**Retomada.** Com `RECOVER_ON_STARTUP=true`, a inicialização envia à geração todo documento `completed` que ainda tenha trechos sem vetor. O pool é em memória, **não** uma fila durável: o que estava na fila ou em curso ao cair é retomado na próxima inicialização, ou à mão:

```bash
python -m app.cli embed-pending                      # todos os documentos com trechos sem vetor
python -m app.cli embed-pending --document-id UUID   # apenas um documento
```

O comando é idempotente, imprime `N documento(s) tratado(s), G vetor(es) gerado(s), R trecho(s) reaproveitado(s), F falha(s).` e termina com código 1 se houve falha, ou 2 se os embeddings estão desligados ou o provedor está indisponível. O `process-pending` não dispara embeddings: rode o `embed-pending` depois. Com o provedor `local`, o `embed-pending` carrega o modelo (cerca de 1 GB) no próprio processo do comando.

## Modelo de dados

```
categories 1───* notes *───1 projects        notes *───* tags   (tabela note_tags)
```

| Tabela | Colunas principais |
|---|---|
| `notes` | `id` UUID, `title`, `content`, `category_id` (FK, `ON DELETE SET NULL`), `project_id` (FK, `ON DELETE SET NULL`), `search_vector` tsvector (GIN), `created_at`, `updated_at` |
| `categories` | `id`, `name`, `description`, `color`, `created_at` |
| `projects` | `id`, `name`, `description`, `created_at` |
| `tags` | `id`, `name`, `color`, `created_at` |
| `note_tags` | `note_id`, `tag_id`: chave primária composta (sem duplicatas), ambas com `ON DELETE CASCADE` |
| `documents` | `id` UUID, `title`, `original_filename`, `storage_key` (único, nunca exposto), `content_type`, `size_bytes`, `sha256`, `page_count`, `status` (`pending`/`processing`/`completed`/`failed`), `has_text`, `error_message`, `category_id` e `project_id` (FK `SET NULL`), `search_vector` (GIN), `created_at`, `updated_at` |
| `document_pages` | `id`, `document_id` (FK `CASCADE`), `page_number` (≥ 1), `text`; único por `(document_id, page_number)`. Continua sendo a fonte do texto extraído |
| `document_chunks` | `id`, `document_id`, `page_number`, `chunk_index` (0, 1, 2… no documento), `content`, `character_count`, `start_offset`/`end_offset` (posição do trecho no texto da página), `created_at`. FK composta `(document_id, page_number)` → `document_pages` (`CASCADE`), únicos `(document_id, chunk_index)` e `(document_id, page_number, start_offset)`, checks de contagem, offsets e conteúdo não vazio |
| `document_tags` | `document_id`, `tag_id`: chave composta, ambas `CASCADE`. Reaproveita a tabela `tags` |

Nomes únicos por índice em `lower(name)` e restrição que impede nome em branco. Regras de integridade ficam no banco, não só na aplicação.

### Migrations

| Revisão | Conteúdo |
|---|---|
| `0001` | tabela `notes` (Fase 1) |
| `0002` | extensão `vector` (Fase 1) |
| `0003` | categorias, projetos, etiquetas, `note_tags` e FKs em `notes` |
| `0004` | coluna `search_vector`, preenchimento das notas existentes e índice GIN |
| `0005` | `documents`, `document_pages`, `document_tags`, índices e restrições (não depende de pgvector) |
| `0006` | `document_chunks` e índice **único** em `documents.sha256` (não depende de pgvector). Se já existirem documentos com o mesmo hash, a migration aborta antes de alterar qualquer coisa, listando os grupos; exclua as cópias e rode de novo |
| `0007` | `chunk_embeddings`: um `vector(384)` por trecho, hash do texto, modelo e dimensões, com índice HNSW por cosseno. **Exige pgvector ≥ 0.5** e nasce vazia; o `downgrade` apaga os vetores (derivados, regeráveis) |

## Testes

```bash
cd backend && source .venv/bin/activate
pytest                      # SQLite em memória: CRUD, integridade, filtros, N+1
```

Cada teste usa um diretório temporário como armazenamento e PDFs gerados em memória; nada do seu armazenamento real é tocado. A busca com termo usa recursos do PostgreSQL e só roda com um banco real. Crie um banco **descartável** cujo nome termine em `_test` (ele é apagado e recriado a cada teste; a suíte recusa nomes sem esse sufixo):

```bash
TEST_DATABASE_URL=postgresql+psycopg://USUARIO:SENHA@localhost:5432/secondbrain_test pytest
```

```bash
cd frontend && npm test && npm run typecheck && npm run lint && npm run build
```

## Limitações conhecidas

- Trechos: o tamanho é medido em caracteres, não em tokens (não há `token_count`: nenhum tokenizador confiável sem dependência ou modelo); títulos e listas não são reconhecidos; o último trecho de uma página pode ser quase só sobreposição; o limite de uma só palavra é cortado no meio. Páginas curtas (< `CHUNK_MIN_CHARS`) não geram trechos, mas continuam no texto e na busca.
- Duplicatas: só binariamente idênticos (SHA-256). O mesmo conteúdo salvo de outra forma é um arquivo diferente.
- Documentos: sem OCR (PDF digitalizado fica sem texto), sem PDF protegido por senha, sem visualizador de PDF na interface (há texto por página e download).
- O processamento em segundo plano usa um pool de threads dentro da API, com as limitações de durabilidade descritas acima. A extração de texto é CPU-bound: documentos muito grandes ocupam um worker por mais tempo e os demais esperam em `pending` quando todos os workers estão ocupados.
- O recebimento do upload é feito em blocos de 1 MB para um arquivo temporário, mas a validação de estrutura (no upload) e a extração (em segundo plano) do `pypdf` leem o arquivo já validado inteiro na memória. O uso de memória fica limitado por `MAX_UPLOAD_MB`.
- O limite de tamanho é recusado cedo pelo `Content-Length`. Um cliente que envie sem esse cabeçalho (chunked) só é barrado depois que o corpo foi recebido em arquivo temporário (apagado em seguida).
- Para a busca, no máximo os primeiros 400 mil caracteres do texto de cada documento são indexados (limite do `tsvector`). O texto completo continua disponível na visualização.
- Se o disco falhar ao apagar o arquivo de um documento já excluído, pode sobrar um arquivo `*.pdf.deleting` no armazenamento, inacessível pela API e seguro de remover manualmente.
- Título, categoria, projeto e etiquetas do documento são definidos na importação e podem ser editados depois, na página do documento ("Editar informações") ou por `PATCH /api/documents/{id}`.
- A busca usa a configuração `portuguese` do PostgreSQL: reduz palavras ao radical ("dado" acha "dados"), mas não é lematização ("construir" não acha "construção", "linguagem" não acha "linguagens"), não ignora acentos ("construcao" não acha "construção") e não faz busca por prefixo ("pyth").
- O `search_vector` é recalculado pela aplicação a cada escrita. Alterações feitas direto no banco, fora da API, não atualizam o índice.
- A busca com termo exige PostgreSQL (retorna 503 em outros bancos). Listagem e filtros funcionam em qualquer banco.
- O conteúdo da nota é texto simples (sem Markdown renderizado).
- A migration `0002` (pgvector) exige a extensão instalada; use a imagem `pgvector/pgvector:0.6.0-pg16` do Docker Compose.
- Sem autenticação: o projeto assume uso local por uma única pessoa.

## Documentação

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- [docs/ROADMAP.md](docs/ROADMAP.md)
