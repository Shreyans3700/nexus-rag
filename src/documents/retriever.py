"""Hybrid document retrieval using Milvus dense vectors, BM25, and RRF."""
from langchain_openai import OpenAIEmbeddings
from pymilvus import AnnSearchRequest, MilvusClient, RRFRanker

from src.config.config import (
    MILVUS_COLLECTION_NAME,
    MILVUS_HYBRID_CANDIDATE_K,
    MILVUS_RRF_K,
    MILVUS_TOP_K,
)
from src.logger import get_logger

logger = get_logger(__name__)

_embeddings = OpenAIEmbeddings(model="text-embedding-3-small")


def _format_context(chunks: list[str]) -> str:
    if not chunks:
        return ""
    lines = [f"[{index + 1}] {chunk.strip()}" for index, chunk in enumerate(chunks)]
    return (
        "Relevant document context (use this to answer the user's question):\n\n"
        + "\n\n".join(lines)
    )


def _filter_value(value: str) -> str:
    """Escape a string used in a Milvus scalar filter."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _scope_filter(user_id: str, session_id: str | None = None) -> str:
    user_filter = f'user_id == "{_filter_value(user_id)}"'
    if session_id is None:
        return user_filter
    return f'{user_filter} and session_id == "{_filter_value(session_id)}"'


def _has_chunks(milvus_client: MilvusClient, filter_expr: str) -> bool:
    rows = milvus_client.query(
        collection_name=MILVUS_COLLECTION_NAME,
        filter=filter_expr,
        output_fields=["chunk_id"],
        limit=1,
    )
    return bool(rows)


def _hybrid_search(
    milvus_client: MilvusClient,
    query: str,
    query_vector: list[float],
    filter_expr: str,
    top_k: int,
) -> list[str]:
    candidate_k = max(top_k, MILVUS_HYBRID_CANDIDATE_K)
    dense_request = AnnSearchRequest(
        data=[query_vector],
        anns_field="dense_vector",
        param={"metric_type": "COSINE", "params": {"nprobe": 16}},
        limit=candidate_k,
        expr=filter_expr,
    )
    sparse_request = AnnSearchRequest(
        data=[query],
        anns_field="sparse_vector",
        param={"metric_type": "BM25"},
        limit=candidate_k,
        expr=filter_expr,
    )
    results = milvus_client.hybrid_search(
        collection_name=MILVUS_COLLECTION_NAME,
        reqs=[dense_request, sparse_request],
        ranker=RRFRanker(k=MILVUS_RRF_K),
        limit=top_k,
        output_fields=["text", "filename", "document_id", "chunk_index"],
    )
    hits = results[0] if results else []
    return [hit["entity"]["text"] for hit in hits if hit.get("entity", {}).get("text")]


async def retrieve_context(
    query: str,
    session_id: str,
    user_id: str,
    milvus_client: MilvusClient,
    top_k: int = MILVUS_TOP_K,
) -> str:
    """Retrieve hybrid-ranked context, preferring the active session's documents."""
    if not query.strip():
        return ""

    session_filter = _scope_filter(user_id, session_id)
    try:
        filter_expr = session_filter
        scope = "session"
        if not _has_chunks(milvus_client, session_filter):
            logger.debug(
                "No session-scoped chunks; broadening retrieval: user_id=%s session_id=%s",
                user_id,
                session_id,
            )
            filter_expr = _scope_filter(user_id)
            scope = "user"
            if not _has_chunks(milvus_client, filter_expr):
                logger.debug("No indexed chunks: user_id=%s session_id=%s", user_id, session_id)
                return ""

        logger.debug(
            "Running hybrid retrieval: user_id=%s session_id=%s scope=%s candidates=%s top_k=%s",
            user_id,
            session_id,
            scope,
            max(top_k, MILVUS_HYBRID_CANDIDATE_K),
            top_k,
        )
        query_vector = await _embeddings.aembed_query(query)
        chunks = _hybrid_search(
            milvus_client=milvus_client,
            query=query,
            query_vector=query_vector,
            filter_expr=filter_expr,
            top_k=top_k,
        )
        logger.info(
            "Hybrid retrieval: user_id=%s session_id=%s scope=%s chunks_returned=%s",
            user_id,
            session_id,
            scope,
            len(chunks),
        )
        return _format_context(chunks)
    except Exception:
        logger.warning(
            "Hybrid retrieval failed: user_id=%s session_id=%s",
            user_id,
            session_id,
            exc_info=True,
        )
        return ""
