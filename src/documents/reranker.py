"""Cross-encoder reranking for hybrid-retrieval candidates."""
import asyncio
from functools import lru_cache

from sentence_transformers import CrossEncoder

from src.config.config import RERANKER_MAX_LENGTH, RERANKER_MODEL
from src.logger import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_reranker() -> CrossEncoder:
    """Load the local model once, on the first request that needs it."""
    logger.info("Loading cross-encoder reranker: model=%s", RERANKER_MODEL)
    return CrossEncoder(RERANKER_MODEL, max_length=RERANKER_MAX_LENGTH)


def _score_pairs(query: str, chunks: list[dict]) -> list[float]:
    pairs = [(query, chunk["text"]) for chunk in chunks]
    return [float(score) for score in _get_reranker().predict(pairs)]


async def rerank_chunks(query: str, chunks: list[dict], top_k: int) -> list[dict]:
    """Rank candidate chunks by pairwise query relevance.

    The model inference is synchronous and CPU/GPU intensive, so it runs in a
    worker thread rather than blocking FastAPI's async event loop.
    """
    if not chunks:
        return []

    scores = await asyncio.to_thread(_score_pairs, query, chunks)
    ranked_chunks = [
        {**chunk, "rerank_score": score}
        for chunk, score in zip(chunks, scores)
    ]
    ranked_chunks.sort(key=lambda chunk: chunk["rerank_score"], reverse=True)
    return ranked_chunks[:top_k]
