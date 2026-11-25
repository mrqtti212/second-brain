# Roadmap

## Fase 1: Fundação (concluída)
Estrutura, CRUD de notas, interface base, PostgreSQL + pgvector preparado, migrations, testes e documentação.

## Fase 2: Biblioteca de conhecimento (concluída, com ressalva)
Notas editáveis (criar, ver, editar, excluir com confirmação), categorias, projetos e etiquetas, busca textual em português no PostgreSQL com filtros, paginação e índice GIN, testes de frontend (Vitest) e de backend (SQLite e PostgreSQL real).
Ressalva: a migration `0002` (pgvector) segue sem validação em banco real com a extensão, por falta de Docker neste ambiente de desenvolvimento.

Candidatos a próxima iteração, nascidos de limitações conhecidas:
- Busca sem acento (extensão `unaccent`) e por prefixo.
- Triggers no banco para manter `search_vector`, em vez da atualização pela aplicação.
- Markdown na nota e ordenação escolhida pelo usuário na biblioteca.

## Fase 3.1: Importação de documentos (concluída, com ressalva)
Upload de PDF com validação (extensão, tipo, assinatura, tamanho, estrutura), armazenamento local seguro do original, texto extraído por página no PostgreSQL, listagem com busca por nome e filtros, visualização, download, exclusão consistente e busca unificada com as notas. Sem OCR, embeddings ou IA.
Ressalva: a migration `0002` (pgvector) segue sem validação em banco com a extensão; a `0005` não depende dela.

## Fase 3.2.1: Estrutura de documentos (concluída, com ressalva)
Trechos (chunks) por página com sobreposição e rastreio exato da origem, edição de título e organização do documento (API e interface), detecção de duplicatas por SHA-256 com índice único e 409 estruturado, comando de reprocessamento idempotente. Sem embeddings, IA, OCR ou processamento assíncrono.
Ressalva: a cadeia de migrations desde um banco vazio segue sem validação completa (a `0002` exige pgvector). A `0006` foi validada isoladamente sobre um esquema equivalente ao da `0005`.

## Fase 3.2.2: Processamento assíncrono e reprocessamento (concluída, com ressalvas)
Upload que responde `pending` sem esperar a extração, processamento em segundo plano por pool de threads com banco como fonte da verdade, estados `pending → processing → completed/failed`, troca atômica do resultado, reprocessamento por API e interface (`POST /api/documents/{id}/reprocess`), retomada na inicialização e `python -m app.cli process-pending`, polling na interface. Sem migration, sem fila externa.
Ressalvas: o pool **não é uma fila durável** e pressupõe um único processo da API; e a cadeia de migrations desde um banco vazio segue sem validação completa (a `0002` exige pgvector).

## Fase 3.2.3 (sugestão): preparar a recuperação
- Se for preciso durabilidade real ou vários processos: worker separado lendo a tabela `documents` (ou fila externa), com tentativas e espera.
- Embeddings e busca semântica sobre os trechos (exige validar a `0002` em um PostgreSQL com pgvector), depois RAG com citação de fonte (documento e página).
- OCR opcional para PDFs digitalizados.

## MVP utilizável (M0)
Dashboard com dados reais e estados honestos, fim dos placeholders e dos dados de demonstração (painel "Assistente de IA", dados fictícios e a rota `/assistant`), e execução como aplicativo numa porta só (`scripts/run-app.sh`, com conferência de banco somente leitura). Sem dependências novas e sem migrations.
Ressalvas: a busca por termo exige PostgreSQL e a validação de ponta a ponta com PostgreSQL ainda não foi feita (o percurso no navegador foi feito com um SQLite descartável); a busca por significado (M1) depende da Etapa D; a busca ainda não ignora acentos.

## Fase 4: Busca semântica
Em andamento, por etapas. **Etapa C pronta:** provedor local `intfloat/multilingual-e5-small` (ONNX, CPU, revisão fixa e SHA-256 verificado), instalação manual do modelo e avaliação de qualidade em uma amostra pequena em português (sem prova de qualidade geral; ver README). **Etapa B pronta:** tarefa `embed_document` (idempotente, em lotes, com repetição de falhas passageiras), reaproveitamento de vetores por hash no reprocessamento e entre documentos, comando `embed-pending` e retomada na inicialização, testada com o provedor falso. **Etapa A pronta:** migration `0007` (`chunk_embeddings`, `vector(384)`, HNSW por cosseno), modelo, contrato `EmbeddingProvider`, provedor falso determinístico e configuração desligada por padrão. Modelo candidato: `intfloat/multilingual-e5-small` (local, em CPU, sem enviar texto para fora). Faltam: modos de busca semântica e híbrida, opcionais e desligados por padrão (D), interface e documentação (E).
- Embeddings, colunas `vector` e índice HNSW.
- Busca híbrida (palavra-chave + significado).

## Fase 5: Assistente de IA
- Conversa com respostas baseadas nos documentos do usuário, com fontes exibidas.
- Resumos e itens relacionados.

## Fora do escopo até aqui
Autenticação, multiusuário, deploy.
