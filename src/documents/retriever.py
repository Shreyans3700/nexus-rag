"""Hybrid document retrieval using Milvus dense vectors, BM25, and RRF."""
from dataclasses import dataclass
import re

from langchain_openai import OpenAIEmbeddings
from pymilvus import AnnSearchRequest, MilvusClient, RRFRanker

from src.config.config import (
    MILVUS_COLLECTION_NAME,
    MILVUS_HYBRID_CANDIDATE_K,
    MILVUS_RRF_K,
    MILVUS_TOP_K,
    RERANKER_CANDIDATE_K,
    RERANKER_ENABLED,
    RERANKER_TOP_K,
)
from src.documents.reranker import rerank_chunks
from src.logger import get_logger

logger = get_logger(__name__)

_embeddings = OpenAIEmbeddings(model="text-embedding-3-small")


@dataclass(frozen=True)
class RetrievalResult:
    """LLM context plus the exact source metadata used to build it."""

    context: str
    sources: list[dict]


def cited_sources(answer: str, sources: list[dict]) -> list[dict]:
    """Return only sources explicitly cited as ``[n]`` in the answer."""
    cited_numbers = {int(number) for number in re.findall(r"\[(\d+)]", answer)}
    return [source for source in sources if source["citation"] in cited_numbers]


def _format_context(chunks: list[dict]) -> str:
    if not chunks:
        return ""
    lines = []
    for index, chunk in enumerate(chunks, start=1):
        page = (
            f"PDF page: {chunk['page']}"
            if chunk["page"] is not None
            else "PDF page: unavailable"
        )
        lines.append(
            f"[{index}] Source: {chunk['filename']}\n{page}\n\n{chunk['text'].strip()}"
        )
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
) -> list[dict]:
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
        output_fields=["text", "filename", "document_id", "chunk_index", "page"],
    )
    hits = results[0] if results else []
    return [
        {
            "text": entity["text"],
            "filename": entity.get("filename", "Unknown document"),
            "page": entity.get("page"),
            "chunk": entity.get("chunk_index", 0),
        }
        for hit in hits
        if (entity := hit.get("entity", {})).get("text")
    ]


async def retrieve_context(
    query: str,
    session_id: str,
    user_id: str,
    milvus_client: MilvusClient,
    top_k: int = MILVUS_TOP_K,
) -> RetrievalResult:
    """Retrieve hybrid-ranked context, preferring the active session's documents."""
    if not query.strip():
        return RetrievalResult(context="", sources=[])

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
                return RetrievalResult(context="", sources=[])

        logger.debug(
            "Running hybrid retrieval: user_id=%s session_id=%s scope=%s candidates=%s rerank_enabled=%s",
            user_id,
            session_id,
            scope,
            RERANKER_CANDIDATE_K
            if RERANKER_ENABLED
            else max(top_k, MILVUS_HYBRID_CANDIDATE_K),
            RERANKER_ENABLED,
        )
        query_vector = await _embeddings.aembed_query(query)
        retrieval_k = RERANKER_CANDIDATE_K if RERANKER_ENABLED else top_k
        chunks = _hybrid_search(
            milvus_client=milvus_client,
            query=query,
            query_vector=query_vector,
            filter_expr=filter_expr,
            top_k=retrieval_k,
        )
        if RERANKER_ENABLED:
            try:
                chunks = await rerank_chunks(
                    query=query,
                    chunks=chunks,
                    top_k=min(RERANKER_TOP_K, top_k),
                )
            except Exception:
                logger.warning(
                    "Reranking failed; using hybrid-ranked candidates: user_id=%s session_id=%s",
                    user_id,
                    session_id,
                    exc_info=True,
                )
                chunks = chunks[:top_k]
        logger.info(
            "Hybrid retrieval: user_id=%s session_id=%s scope=%s chunks_returned=%s reranked=%s",
            user_id,
            session_id,
            scope,
            len(chunks),
            RERANKER_ENABLED,
        )
        sources = [
            {
                "filename": chunk["filename"],
                "page": chunk["page"],
                "chunk": chunk["chunk"],
                "citation": index,
            }
            for index, chunk in enumerate(chunks, start=1)
        ]
        return RetrievalResult(context=_format_context(chunks), sources=sources)
    except Exception:
        logger.warning(
            "Hybrid retrieval failed: user_id=%s session_id=%s",
            user_id,
            session_id,
            exc_info=True,
        )
        return RetrievalResult(context="", sources=[])
