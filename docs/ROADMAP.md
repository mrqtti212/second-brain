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

## Fase 4: Busca semântica
- Embeddings, colunas `vector` e índice HNSW.
- Busca híbrida (palavra-chave + significado).

## Fase 5: Assistente de IA
- Conversa com respostas baseadas nos documentos do usuário, com fontes exibidas.
- Resumos e itens relacionados.

## Fora do escopo até aqui
Autenticação, multiusuário, deploy.
