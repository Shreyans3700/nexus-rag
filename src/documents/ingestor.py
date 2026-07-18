"""
Background ingestion worker — orchestrates the full parse → chunk → embed pipeline
for a single uploaded document.

Called via FastAPI BackgroundTasks so the upload endpoint returns immediately
while heavy work (PDF parsing, OpenAI embedding) happens asynchronously.

Status lifecycle:
  processing  →  ready      (success)
  processing  →  failed     (any unhandled exception)
"""
from src.documents.chunker import chunk_text
from src.documents.embedder import embed_and_store
from src.documents.parser import parse_file
from src.logger import get_logger

logger = get_logger(__name__)


async def ingest_document(
    document_id: str,
    user_id: str,
    session_id: str,
    filename: str,
    content: bytes,
    db,
    milvus_client,
) -> None:
    """Parse, chunk, embed, and store a document. Updates status in Postgres.

    Args:
        document_id:  UUID of the pre-inserted `documents` row.
        user_id:      Owning user ID.
        session_id:   Owning session ID.
        filename:     Original filename (used for format detection).
        content:      Raw file bytes.
        db:           asyncpg connection pool.
        milvus_client: Connected MilvusClient instance.
    """
    logger.info(
        "Ingestion started: document_id=%s filename=%s user_id=%s session_id=%s",
        document_id,
        filename,
        user_id,
        session_id,
    )
    try:
        # 1. Parse raw bytes → plain text
        text = parse_file(filename, content)
        if not text.strip():
            logger.warning(
                "Parsed empty text from document: document_id=%s filename=%s",
                document_id,
                filename,
            )
            await _mark_status(db, document_id, "failed", chunk_count=0)
            return

        # 2. Chunk the text
        chunks = chunk_text(text)
        if not chunks:
            logger.warning(
                "Chunker produced zero chunks: document_id=%s filename=%s",
                document_id,
                filename,
            )
            await _mark_status(db, document_id, "failed", chunk_count=0)
            return

        # 3. Embed chunks and write to Milvus + Postgres
        count = await embed_and_store(
            chunks=chunks,
            document_id=document_id,
            user_id=user_id,
            session_id=session_id,
            db=db,
            milvus_client=milvus_client,
        )

        # 4. Mark document as ready
        await _mark_status(db, document_id, "ready", chunk_count=count)

        logger.info(
            "Ingestion complete: document_id=%s filename=%s chunks=%s",
            document_id,
            filename,
            count,
        )

    except Exception:
        logger.exception(
            "Ingestion failed: document_id=%s filename=%s", document_id, filename
        )
        await _mark_status(db, document_id, "failed", chunk_count=0)


async def _mark_status(db, document_id: str, status: str, chunk_count: int) -> None:
    """Update the document's status and chunk_count in Postgres."""
    try:
        async with db.acquire() as conn:
            await conn.execute(
                """
                UPDATE documents
                SET status = $1, chunk_count = $2
                WHERE id = $3
                """,
                status,
                chunk_count,
                document_id,
            )
        logger.debug(
            "Document status updated: document_id=%s status=%s chunks=%s",
            document_id,
            status,
            chunk_count,
        )
    except Exception:
        logger.exception(
            "Failed to update document status: document_id=%s status=%s",
            document_id,
            status,
        )
