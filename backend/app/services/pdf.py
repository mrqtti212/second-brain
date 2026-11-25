"""Leitura de PDFs com pypdf (sem OCR)."""

import logging
import re
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.core.errors import InvalidFileError

logger = logging.getLogger("second_brain.pdf")

# PostgreSQL não aceita NUL em text; demais controles atrapalham a leitura.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def open_pdf(path: Path, max_pages: int) -> PdfReader:
    """Abre e valida a estrutura do PDF. Lança InvalidFileError se não for utilizável."""
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise InvalidFileError("O PDF é protegido por senha e não pode ser importado.")
        count = len(reader.pages)
    except InvalidFileError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError, RecursionError) as exc:
        logger.info("PDF rejeitado: %s", type(exc).__name__)
        raise InvalidFileError("O PDF está corrompido ou não pôde ser lido.") from exc
    if count == 0:
        raise InvalidFileError("O PDF não possui páginas.")
    if count > max_pages:
        raise InvalidFileError(f"O PDF tem {count} páginas; o limite é {max_pages}.")
    return reader


def extract_text(reader: PdfReader) -> list[str]:
    """Texto de cada página, na ordem. Lança exceção se alguma página falhar."""
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(_CONTROL.sub("", text).strip())
    return pages
