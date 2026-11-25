"""Busca textual (notas e documentos) com full-text search do PostgreSQL.

Cada tabela tem um `search_vector` persistido e indexado com GIN. Pesos:
A = título, B = nomes de categoria/projeto/etiquetas (e nome do arquivo, em
documentos), C = conteúdo (texto das páginas, em documentos).
A aplicação recalcula o vetor em toda escrita que o afeta.
"""

import uuid
from collections.abc import Iterable
from typing import Literal

from sqlalchemy import Float, bindparam, cast, func, literal_column, null, select, text, union_all
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session

from app.core.errors import SearchUnavailableError
from app.models.document import Document, DocumentPage
from app.models.note import Note
from app.models.tag import Tag
from app.schemas.search import SearchPage, SearchResult

TS_CONFIG = "portuguese"
HIGHLIGHT_START = ""
HIGHLIGHT_END = ""
FALLBACK_SNIPPET_CHARS = 200
# tsvector tem limite de ~1 MB: indexamos no máximo este tanto de texto por documento.
INDEXED_TEXT_CHARS = 400_000

ContentType = Literal["all", "note", "document"]

_TAG_NAMES = """coalesce((SELECT string_agg(t.name, ' ') FROM {assoc} a
                            JOIN tags t ON t.id = a.tag_id WHERE a.{fk} = {table}.id), '')"""

_NOTE_VECTOR = f"""
    setweight(to_tsvector('{TS_CONFIG}', coalesce(notes.title, '')), 'A')
    || setweight(to_tsvector('{TS_CONFIG}',
         coalesce((SELECT c.name FROM categories c WHERE c.id = notes.category_id), '')
         || ' ' || coalesce((SELECT p.name FROM projects p WHERE p.id = notes.project_id), '')
         || ' ' || {_TAG_NAMES.format(assoc='note_tags', fk='note_id', table='notes')}), 'B')
    || setweight(to_tsvector('{TS_CONFIG}', coalesce(notes.content, '')), 'C')
"""

_DOCUMENT_VECTOR = f"""
    setweight(to_tsvector('{TS_CONFIG}', coalesce(documents.title, '')), 'A')
    || setweight(to_tsvector('{TS_CONFIG}',
         coalesce(documents.original_filename, '')
         || ' ' || coalesce((SELECT c.name FROM categories c WHERE c.id = documents.category_id), '')
         || ' ' || coalesce((SELECT p.name FROM projects p WHERE p.id = documents.project_id), '')
         || ' ' || {_TAG_NAMES.format(assoc='document_tags', fk='document_id', table='documents')}), 'B')
    || setweight(to_tsvector('{TS_CONFIG}', left(coalesce(
         (SELECT string_agg(pg.text, ' ' ORDER BY pg.page_number)
            FROM document_pages pg WHERE pg.document_id = documents.id), ''), {INDEXED_TEXT_CHARS})), 'C')
"""

_REFRESH_NOTES = text(
    f"UPDATE notes SET search_vector = {_NOTE_VECTOR} WHERE notes.id IN :ids"
).bindparams(bindparam("ids", expanding=True))
_REFRESH_DOCUMENTS = text(
    f"UPDATE documents SET search_vector = {_DOCUMENT_VECTOR} WHERE documents.id IN :ids"
).bindparams(bindparam("ids", expanding=True))


def _is_postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def _refresh(db: Session, statement, ids: Iterable[uuid.UUID]) -> None:
    unique = list(set(ids))
    if not unique or not _is_postgres(db):
        return
    db.flush()
    db.execute(statement, {"ids": unique})


def refresh_notes(db: Session, note_ids: Iterable[uuid.UUID]) -> None:
    """Recalcula o vetor das notas. Faz flush antes; não faz commit."""
    _refresh(db, _REFRESH_NOTES, note_ids)


def refresh_documents(db: Session, document_ids: Iterable[uuid.UUID]) -> None:
    """Recalcula o vetor dos documentos. Faz flush antes; não faz commit."""
    _refresh(db, _REFRESH_DOCUMENTS, document_ids)


def _tsquery(q: str):
    # websearch_to_tsquery aceita texto livre ("aspas", -exclusão, or) e nunca
    # falha por sintaxe. O termo vai como parâmetro, nunca concatenado.
    return func.websearch_to_tsquery(literal_column(f"'{TS_CONFIG}'::regconfig"), q)


def _filters(model, q, category_id, project_id, tag_ids: list[uuid.UUID]) -> list:
    conditions = []
    if q:
        conditions.append(model.search_vector.op("@@")(_tsquery(q)))
    if category_id:
        conditions.append(model.category_id == category_id)
    if project_id:
        conditions.append(model.project_id == project_id)
    for tag_id in dict.fromkeys(tag_ids):  # AND entre etiquetas, sem repetir
        conditions.append(model.tags.any(Tag.id == tag_id))  # EXISTS: sem duplicatas
    return conditions


def _candidates(model, kind: str, q, conditions: list):
    score = func.ts_rank_cd(model.search_vector, _tsquery(q)) if q else cast(null(), Float)
    return select(
        literal_column(f"'{kind}'").label("kind"),
        model.id.label("id"),
        score.label("score"),
        model.updated_at.label("updated_at"),
    ).where(*conditions)


def _highlight_options() -> str:
    return (
        f"StartSel={HIGHLIGHT_START}, StopSel={HIGHLIGHT_END}, "
        "MaxFragments=2, MaxWords=30, MinWords=12, FragmentDelimiter= … "
    )


def _note_snippet(q):
    if q:
        return func.ts_headline(
            literal_column(f"'{TS_CONFIG}'::regconfig"), Note.content, _tsquery(q), _highlight_options()
        )
    return func.substr(Note.content, 1, FALLBACK_SNIPPET_CHARS)


def _document_snippet(q):
    if q:
        full_text = (
            select(func.left(
                func.string_agg(DocumentPage.text, aggregate_order_by(literal_column("' '"), DocumentPage.page_number)),
                INDEXED_TEXT_CHARS,
            ))
            .where(DocumentPage.document_id == Document.id)
            .scalar_subquery()
        )
        return func.ts_headline(
            literal_column(f"'{TS_CONFIG}'::regconfig"), func.coalesce(full_text, ""), _tsquery(q), _highlight_options()
        )
    first_page = (
        select(func.substr(DocumentPage.text, 1, FALLBACK_SNIPPET_CHARS))
        .where(DocumentPage.document_id == Document.id, DocumentPage.page_number == 1)
        .scalar_subquery()
    )
    return func.coalesce(first_page, "")


def search(
    db: Session,
    *,
    q: str | None,
    content_type: ContentType = "all",
    category_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    tag_ids: list[uuid.UUID] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> SearchPage:
    q = (q or "").strip() or None
    if q and not _is_postgres(db):
        raise SearchUnavailableError()
    tag_ids = tag_ids or []

    selects = []
    if content_type in ("all", "note"):
        selects.append(_candidates(Note, "note", q, _filters(Note, q, category_id, project_id, tag_ids)))
    if content_type in ("all", "document"):
        selects.append(_candidates(Document, "document", q, _filters(Document, q, category_id, project_id, tag_ids)))

    candidates = union_all(*selects).subquery() if len(selects) > 1 else selects[0].subquery()
    total = db.scalar(select(func.count()).select_from(candidates)) or 0
    page_rows = db.execute(
        select(candidates.c.kind, candidates.c.id, candidates.c.score)
        .order_by(candidates.c.score.desc().nulls_last(), candidates.c.updated_at.desc(), candidates.c.id)
        .limit(limit)
        .offset(offset)
    ).all()

    # Trechos (ts_headline é caro): só para as linhas da página.
    note_ids = [r.id for r in page_rows if r.kind == "note"]
    doc_ids = [r.id for r in page_rows if r.kind == "document"]
    notes = (
        {n.id: (n, s) for n, s in db.execute(select(Note, _note_snippet(q)).where(Note.id.in_(note_ids)))}
        if note_ids
        else {}
    )
    docs = (
        {d.id: (d, s) for d, s in db.execute(select(Document, _document_snippet(q)).where(Document.id.in_(doc_ids)))}
        if doc_ids
        else {}
    )

    items: list[SearchResult] = []
    for row in page_rows:
        score = float(row.score) if row.score is not None else None
        if row.kind == "note":
            note, snippet = notes[row.id]
            items.append(
                SearchResult(
                    type="note", id=note.id, title=note.title, snippet=snippet or "",
                    updated_at=note.updated_at, category=note.category, project=note.project,
                    tags=note.tags, score=score,
                )
            )
        else:
            doc, snippet = docs[row.id]
            items.append(
                SearchResult(
                    type="document", id=doc.id, title=doc.title, snippet=snippet or "",
                    updated_at=doc.updated_at, category=doc.category, project=doc.project,
                    tags=doc.tags, score=score, status=doc.status, page_count=doc.page_count,
                    has_text=doc.has_text,
                )
            )
    return SearchPage(items=items, total=total, limit=limit, offset=offset)


# Compatibilidade com o nome usado na Fase 2.
search_notes = search
