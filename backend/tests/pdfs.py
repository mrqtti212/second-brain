"""PDFs de teste gerados em memória (sem arquivos externos)."""

import itertools


def _escape(text: str) -> bytes:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1")


def make_pdf(pages: list[str]) -> bytes:
    """PDF válido com uma página por item. Texto vazio gera página sem texto (como um scan)."""
    count = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(count))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for i, text in enumerate(pages):
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
            ).encode()
        )
        stream = b"BT /F1 12 Tf 72 720 Td (" + _escape(text) + b") Tj ET" if text else b""
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


_counter = itertools.count(1)


def unique_pdf(pages: list[str]) -> bytes:
    """Mesmo texto, bytes diferentes a cada chamada (comentário final ignorado pelo leitor de PDF).

    A importação recusa o mesmo SHA-256 duas vezes; os testes que precisam de vários
    documentos usam este helper, e os testes de duplicidade reaproveitam os bytes de propósito.
    """
    return make_pdf(pages) + f"%unique-{next(_counter)}\n".encode()


def make_encrypted_pdf(password: str = "segredo") -> bytes:
    import io

    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["conteudo secreto"]))))
    writer.encrypt(password, algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


CORRUPT_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 99 0 R >>\nendobj\nesto nao e um pdf de verdade"
NOT_A_PDF = b"MZ\x90\x00\x03\x00\x00\x00 programa executavel disfarcado"
