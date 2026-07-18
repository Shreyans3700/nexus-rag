"""
Retrieval service — finds the most relevant document chunks for a query.

Fast path:  Embed the query → vector search in Milvus filtered by session_id.
Fallback:   If Milvus has no chunks for the session (or is unavailable):
              1. Load chunk texts from Postgres document_chunks.
              2. Re-embed those chunks and restore them to Milvus.
              3. Rank fetched chunks by cosine similarity to the query vector.
              4. Return the top-K most relevant chunks as a formatted string.

If neither store has chunks for this session, return "" so the chain falls
back to a normal conversation without RAG context.
"""
import numpy as np
from langchain_openai import OpenAIEmbeddings
from pymilvus import MilvusClient

from src.config.config import MILVUS_COLLECTION_NAME, MILVUS_TOP_K
from src.logger import get_logger

logger = get_logger(__name__)

_embeddings = OpenAIEmbeddings(model="text-embedding-3-small")


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two equal-length float vectors."""
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _format_context(chunks: list[str]) -> str:
    """Format a list of chunk strings into the {context} template value."""
    if not chunks:
        return ""
    lines = [f"[{i + 1}] {chunk.strip()}" for i, chunk in enumerate(chunks)]
    return (
        "Relevant document context (use this to answer the user's question):\n\n"
        + "\n\n".join(lines)
    )


async def retrieve_context(
    query: str,
    session_id: str,
    db,
    milvus_client: MilvusClient,
    top_k: int = MILVUS_TOP_K,
) -> str:
    """Retrieve the top-K most relevant chunks for *query* in *session_id*.

    Args:
        query:        The user's current query text.
        session_id:   Session to scope the search to.
        db:           asyncpg connection pool.
        milvus_client: Connected MilvusClient instance.
        top_k:        Number of chunks to return.

    Returns:
        A formatted string of relevant chunks, or "" if none exist.
    """
    if not query.strip():
        return ""

    # ------------------------------------------------------------------
    # Embed the query
    # ------------------------------------------------------------------
    try:
        query_vector = await _embeddings.aembed_query(query)
    except Exception:
        logger.exception("Failed to embed query for retrieval: session_id=%s", session_id)
        return ""

    # ------------------------------------------------------------------
    # Fast path: Milvus vector search
    # ------------------------------------------------------------------
    try:
        chunks = _milvus_search(milvus_client, session_id, query_vector, top_k)
        if chunks:
            logger.info(
                "Milvus retrieval: session_id=%s chunks_returned=%s", session_id, len(chunks)
            )
            return _format_context(chunks)
        logger.debug(
            "Milvus returned no chunks for session_id=%s — trying Postgres fallback",
            session_id,
        )
    except Exception:
        logger.warning(
            "Milvus search failed for session_id=%s — falling back to Postgres",
            session_id,
            exc_info=True,
        )

    # ------------------------------------------------------------------
    # Fallback path: Postgres chunk store
    # ------------------------------------------------------------------
    try:
        pg_chunks = await _postgres_fetch_chunks(db, session_id)
    except Exception:
        logger.exception(
            "Postgres chunk fallback failed: session_id=%s", session_id
        )
        return ""

    if not pg_chunks:
        logger.debug("No chunks found in Postgres either: session_id=%s", session_id)
        return ""

    logger.info(
        "Postgres fallback: session_id=%s total_chunks=%s — re-indexing into Milvus",
        session_id,
        len(pg_chunks),
    )

    # Re-populate Milvus from Postgres so the next query hits the fast path
    await _restore_to_milvus(db, milvus_client, session_id, pg_chunks)

    # Rank by cosine similarity using the already-computed query vector
    chunk_texts = [row["chunk_text"] for row in pg_chunks]
    try:
        chunk_vectors = await _embeddings.aembed_documents(chunk_texts)
        scored = [
            (chunk_texts[i], _cosine_similarity(query_vector, chunk_vectors[i]))
            for i in range(len(chunk_texts))
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        top_chunks = [text for text, _ in scored[:top_k]]
    except Exception:
        logger.warning(
            "Could not rank Postgres chunks by similarity: session_id=%s — returning first %s",
            session_id,
            top_k,
        )
        top_chunks = chunk_texts[:top_k]

    logger.info(
        "Postgres fallback retrieval: session_id=%s chunks_returned=%s",
        session_id,
        len(top_chunks),
    )
    return _format_context(top_chunks)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _milvus_search(
    milvus_client: MilvusClient,
    session_id: str,
    query_vector: list[float],
    top_k: int,
) -> list[str]:
    """Run a vector search in Milvus scoped to session_id. Returns list of chunk texts."""
    results = milvus_client.search(
        collection_name=MILVUS_COLLECTION_NAME,
        data=[query_vector],
        filter=f'session_id == "{session_id}"',
        limit=top_k,
        output_fields=["text"],
        search_params={"metric_type": "COSINE", "params": {"nprobe": 16}},
    )
    # results is a list of lists (one per query vector)
    hits = results[0] if results else []
    return [hit["entity"]["text"] for hit in hits if hit.get("entity", {}).get("text")]


async def _postgres_fetch_chunks(db, session_id: str) -> list[dict]:
    """Fetch all chunk rows for a session from Postgres."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT dc.id, dc.document_id, dc.user_id, dc.session_id,
                   dc.chunk_index, dc.chunk_text
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.session_id = $1
              AND d.status = 'ready'
            ORDER BY dc.document_id, dc.chunk_index
            """,
            session_id,
        )
    return [dict(row) for row in rows]


async def _restore_to_milvus(
    db, milvus_client: MilvusClient, session_id: str, pg_chunks: list[dict]
) -> None:
    """Re-embed Postgres chunks and upsert them back into Milvus."""
    try:
        texts = [row["chunk_text"] for row in pg_chunks]
        vectors = await _embeddings.aembed_documents(texts)
        milvus_rows = [
            {
                "chunk_id": pg_chunks[i]["id"],
                "document_id": pg_chunks[i]["document_id"],
                "user_id": pg_chunks[i]["user_id"],
                "session_id": pg_chunks[i]["session_id"],
                "chunk_index": pg_chunks[i]["chunk_index"],
                "text": texts[i][:4096],
                "vector": vectors[i],
            }
            for i in range(len(texts))
        ]
        milvus_client.upsert(
            collection_name=MILVUS_COLLECTION_NAME,
            data=milvus_rows,
        )
        logger.info(
            "Milvus restored from Postgres: session_id=%s chunks=%s",
            session_id,
            len(milvus_rows),
        )
    except Exception:
        logger.warning(
            "Failed to restore Milvus from Postgres: session_id=%s — will retry on next query",
            session_id,
            exc_info=True,
        )
