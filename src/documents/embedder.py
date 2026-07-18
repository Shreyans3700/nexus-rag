"""
Embedding service — embeds text chunks with OpenAI and writes them to both
Milvus (for fast vector search) and PostgreSQL (for disaster-recovery fallback).

Dual-write strategy:
  1. Embed all chunks in a single batched OpenAI API call.
  2. Bulk-insert chunk text rows into the `document_chunks` Postgres table.
  3. Upsert vector rows into the Milvus `doc_chunks` collection.
  4. Return the count of chunks stored.

If Postgres write succeeds but Milvus upsert fails, we log the error and re-raise
so the ingestor can mark the document as 'failed'.  The Postgres rows remain and
act as the source of truth for a future re-ingestion attempt.
"""
import uuid

from langchain_openai import OpenAIEmbeddings
from pymilvus import MilvusClient

from src.config.config import MILVUS_COLLECTION_NAME
from src.logger import get_logger

logger = get_logger(__name__)

# Module-level embeddings client — stateless, safe to share across calls.
_embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

# Milvus VARCHAR field character limit (must match the schema in config.py)
_TEXT_MAX_LEN = 4096


def _truncate(text: str, max_len: int = _TEXT_MAX_LEN) -> str:
    """Truncate text to fit within the Milvus VARCHAR field limit."""
    return text[:max_len] if len(text) > max_len else text


async def embed_and_store(
    chunks: list[str],
    document_id: str,
    user_id: str,
    session_id: str,
    db,
    milvus_client: MilvusClient,
) -> int:
    """Embed *chunks* and write them to both Milvus and Postgres.

    Args:
        chunks:       List of text chunks produced by the chunker.
        document_id:  UUID of the parent document row in Postgres.
        user_id:      ID of the owning user (for scoping / filtering).
        session_id:   ID of the chat session (for scoping / filtering).
        db:           asyncpg connection pool.
        milvus_client: Connected MilvusClient instance.

    Returns:
        Number of chunks successfully stored.

    Raises:
        RuntimeError: If the embedding API call or either write fails.
    """
    if not chunks:
        logger.warning(
            "embed_and_store called with empty chunks list: document_id=%s", document_id
        )
        return 0

    logger.info(
        "Embedding %s chunks: document_id=%s user_id=%s session_id=%s",
        len(chunks),
        document_id,
        user_id,
        session_id,
    )

    # ------------------------------------------------------------------
    # 1. Embed all chunks in one batched call
    # ------------------------------------------------------------------
    try:
        vectors = await _embeddings.aembed_documents(chunks)
    except Exception as exc:
        logger.exception(
            "OpenAI embedding failed: document_id=%s chunks=%s", document_id, len(chunks)
        )
        raise RuntimeError(f"Embedding failed: {exc}") from exc

    # ------------------------------------------------------------------
    # 2. Bulk-insert into Postgres document_chunks (resilience fallback)
    # ------------------------------------------------------------------
    chunk_ids = [str(uuid.uuid4()) for _ in chunks]

    pg_rows = [
        (chunk_ids[i], document_id, user_id, session_id, i, chunks[i])
        for i in range(len(chunks))
    ]

    try:
        async with db.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO document_chunks
                    (id, document_id, user_id, session_id, chunk_index, chunk_text)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO NOTHING
                """,
                pg_rows,
            )
        logger.debug(
            "Postgres chunk rows inserted: document_id=%s count=%s",
            document_id,
            len(pg_rows),
        )
    except Exception as exc:
        logger.exception(
            "Postgres chunk insert failed: document_id=%s", document_id
        )
        raise RuntimeError(f"Postgres chunk insert failed: {exc}") from exc

    # ------------------------------------------------------------------
    # 3. Upsert vectors into Milvus
    # ------------------------------------------------------------------
    milvus_rows = [
        {
            "chunk_id": chunk_ids[i],
            "document_id": document_id,
            "user_id": user_id,
            "session_id": session_id,
            "chunk_index": i,
            "text": _truncate(chunks[i]),
            "vector": vectors[i],
        }
        for i in range(len(chunks))
    ]

    try:
        milvus_client.upsert(
            collection_name=MILVUS_COLLECTION_NAME,
            data=milvus_rows,
        )
        logger.info(
            "Milvus upsert complete: document_id=%s chunks=%s",
            document_id,
            len(milvus_rows),
        )
    except Exception as exc:
        logger.exception(
            "Milvus upsert failed: document_id=%s — chunks are safe in Postgres",
            document_id,
        )
        raise RuntimeError(f"Milvus upsert failed: {exc}") from exc

    return len(chunks)
