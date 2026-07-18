"""
Document chunker — splits plain text into overlapping chunks suitable for embedding.

Uses LangChain's RecursiveCharacterTextSplitter with sensible defaults:
  - chunk_size=1000 chars
  - chunk_overlap=150 chars

These defaults keep each chunk well within the token budget for
text-embedding-3-small while maintaining enough overlap to preserve context
across chunk boundaries.
"""
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.logger import get_logger

logger = get_logger(__name__)

_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 150

# Module-level splitter instance — stateless, safe to reuse across calls.
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=_CHUNK_SIZE,
    chunk_overlap=_CHUNK_OVERLAP,
    length_function=len,
    # Prefer splitting on paragraph → sentence → word boundaries
    separators=["\n\n", "\n", ". ", " ", ""],
)


def chunk_text(text: str) -> list[str]:
    """Split *text* into a list of overlapping text chunks.

    Args:
        text: Plain text string to split (may be empty).

    Returns:
        List of non-empty string chunks.  Empty list if *text* is blank.
    """
    if not text or not text.strip():
        logger.debug("chunk_text called with empty text, returning []")
        return []

    chunks = _splitter.split_text(text)
    # Filter out any whitespace-only chunks that the splitter may produce
    chunks = [c for c in chunks if c.strip()]

    logger.debug(
        "Chunked text: input_chars=%s chunks=%s avg_chunk_chars=%s",
        len(text),
        len(chunks),
        round(sum(len(c) for c in chunks) / len(chunks)) if chunks else 0,
    )
    return chunks
