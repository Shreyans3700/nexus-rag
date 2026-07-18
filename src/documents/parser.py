"""
Document parser — converts raw file bytes into plain text.

Supported formats: PDF, DOCX, TXT, MD, CSV.
Raises ValueError for unsupported file extensions.
"""
import csv
import io
import os

from src.logger import get_logger

logger = get_logger(__name__)

_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}


def parse_file(filename: str, content: bytes) -> str:
    """Parse raw file bytes into a plain-text string.

    Args:
        filename: Original filename including extension (used for dispatch).
        content:  Raw bytes of the uploaded file.

    Returns:
        Extracted text string.  May be empty if the file has no text layer.

    Raises:
        ValueError: If the file extension is not supported.
    """
    ext = os.path.splitext(filename.lower())[1]
    if ext not in _SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported types: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}"
        )

    logger.debug("Parsing file: filename=%s ext=%s size=%s", filename, ext, len(content))

    if ext == ".pdf":
        text = _parse_pdf(content)
    elif ext == ".docx":
        text = _parse_docx(content)
    elif ext in {".txt", ".md"}:
        text = _parse_text(content)
    elif ext == ".csv":
        text = _parse_csv(content)
    else:
        # Should never reach here given the guard above
        raise ValueError(f"Unsupported extension: {ext}")

    logger.debug("Parsed file: filename=%s chars=%s", filename, len(text))
    return text


# ---------------------------------------------------------------------------
# Per-format helpers
# ---------------------------------------------------------------------------

def _parse_pdf(content: bytes) -> str:
    """Extract text from all pages of a PDF."""
    try:
        import pypdf  # lazy import so the package is only required when used
    except ImportError as exc:
        raise RuntimeError(
            "pypdf is required to parse PDF files. "
            "Install it with: pip install pypdf"
        ) from exc

    reader = pypdf.PdfReader(io.BytesIO(content))
    pages: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            pages.append(page_text)
    return "\n\n".join(pages)


def _parse_docx(content: bytes) -> str:
    """Extract text from a DOCX file, paragraph by paragraph."""
    try:
        import docx  # lazy import
    except ImportError as exc:
        raise RuntimeError(
            "python-docx is required to parse DOCX files. "
            "Install it with: pip install python-docx"
        ) from exc

    doc = docx.Document(io.BytesIO(content))
    paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
    return "\n\n".join(paragraphs)


def _parse_text(content: bytes) -> str:
    """Decode a plain-text or Markdown file as UTF-8, falling back to latin-1."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def _parse_csv(content: bytes) -> str:
    """Convert a CSV file to a readable text block (one row per line)."""
    text_io = io.StringIO(content.decode("utf-8", errors="replace"))
    reader = csv.reader(text_io)
    rows: list[str] = []
    for row in reader:
        rows.append(", ".join(cell.strip() for cell in row))
    return "\n".join(rows)
