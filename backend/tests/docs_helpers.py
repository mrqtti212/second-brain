"""Helpers compartilhados pelos testes de documentos."""

from tests.pdfs import make_pdf, unique_pdf

SENTENCE = "A segmentação preserva o contexto entre trechos vizinhos do documento. "


def long_text(sentences: int = 45) -> str:
    """~3 mil caracteres, com acentos, em frases (várias vezes o limite padrão de 1200)."""
    return (SENTENCE * sentences).strip()


def upload(client, content=None, name="relatorio.pdf", content_type="application/pdf", **fields):
    content = unique_pdf([long_text(), "Segunda página com texto suficiente para gerar um trecho."]) if content is None else content
    data = {k: v for k, v in fields.items() if v is not None}
    return client.post("/api/documents", files={"file": (name, content, content_type)}, data=data)


def ok(client, **kwargs) -> dict:
    """Importa e devolve o documento no estado final (o despachante de teste é imediato)."""
    response = upload(client, **kwargs)
    assert response.status_code == 201, response.text
    final = client.get(f"/api/documents/{response.json()['id']}")
    assert final.status_code == 200, final.text
    return final.json()


def chunks_of(client, document_id: str, **params) -> dict:
    response = client.get(f"/api/documents/{document_id}/chunks", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def all_chunks(client, document_id: str) -> list[dict]:
    return chunks_of(client, document_id, limit=200)["items"]


__all__ = ["make_pdf", "unique_pdf", "long_text", "upload", "ok", "chunks_of", "all_chunks"]
