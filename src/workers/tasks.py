"""ARQ task function for document ingestion pipeline.

This module defines the `process_document` task that:
1. Fetches document metadata from Postgres
2. Downloads the file from MinIO
3. Calls the existing ingestor to parse/chunk/embed/store
4. Updates status on success or failure
"""
import time

from src.config.config import MINIO_BUCKET
from src.documents.ingestor import ingest_document
from src.logger import bind_user_id, get_logger
from src.storage.minio_client import get_minio_client

logger = get_logger(__name__)


async def process_document(ctx: dict, document_id: str) -> None:
    """Process a queued document: download from MinIO and run ingestion pipeline.

    This is the ARQ task function registered in WorkerSettings. It orchestrates
    the full ingestion pipeline by:
    - Fetching metadata from Postgres
    - Downloading file bytes from MinIO
    - Delegating to the existing `ingest_document()` function
    - Updating status on completion or failure

    Args:
        ctx: ARQ worker context containing `db` (asyncpg pool) and `milvus` (MilvusClient)
        document_id: UUID of the document to process

    Raises:
        Exception: Re-raised for ARQ retry on transient failures
    """
    start_time = time.perf_counter()
    db = ctx["db"]
    milvus_client = ctx["milvus"]
    minio_client = get_minio_client()

    logger.info("ARQ task started: document_id=%s", document_id)

    try:
        # ------------------------------------------------------------------ #
        # 1. Fetch document metadata from Postgres
        # ------------------------------------------------------------------ #
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT user_id, session_id, filename, object_name
                FROM documents
                WHERE id = $1
                """,
                document_id,
            )

        if row is None:
            logger.error(
                "Document not found in database: document_id=%s — cannot process",
                document_id,
            )
            return  # Don't retry if metadata is missing

        user_id = row["user_id"]
        session_id = row["session_id"]
        filename = row["filename"]
        object_name = row["object_name"]

        if not object_name:
            logger.error(
                "Document has no object_name: document_id=%s — cannot download from MinIO",
                document_id,
            )
            await _mark_failed(
                db,
                document_id,
                "Missing MinIO object reference",
            )
            return

        # Bind user_id to logger context for all subsequent logs
        with bind_user_id(user_id):
            logger.info(
                "Processing document: document_id=%s user_id=%s session_id=%s filename=%s",
                document_id,
                user_id,
                session_id,
                filename,
            )

            # ------------------------------------------------------------------ #
            # 2. Update status to 'processing'
            # ------------------------------------------------------------------ #
            async with db.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE documents
                    SET status = 'processing'
                    WHERE id = $1
                    """,
                    document_id,
                )
            logger.debug("Status updated to 'processing': document_id=%s", document_id)

            # ------------------------------------------------------------------ #
            # 3. Download file from MinIO
            # ------------------------------------------------------------------ #
            try:
                content = minio_client.download_file(MINIO_BUCKET, object_name)
                logger.info(
                    "Downloaded file from MinIO: document_id=%s size=%s",
                    document_id,
                    len(content),
                )
            except Exception as exc:
                logger.exception(
                    "Failed to download file from MinIO: document_id=%s object=%s",
                    document_id,
                    object_name,
                )
                await _mark_failed(
                    db,
                    document_id,
                    f"MinIO download failed: {exc}",
                )
                # Re-raise for ARQ retry (transient network issue)
                raise

            # ------------------------------------------------------------------ #
            # 4. Call existing ingestion pipeline
            # ------------------------------------------------------------------ #
            try:
                await ingest_document(
                    document_id=document_id,
                    user_id=user_id,
                    session_id=session_id,
                    filename=filename,
                    content=content,
                    db=db,
                    milvus_client=milvus_client,
                )
                elapsed = time.perf_counter() - start_time
                logger.info(
                    "Document processing complete: document_id=%s user_id=%s elapsed=%.2fs",
                    document_id,
                    user_id,
                    elapsed,
                )
            except ValueError as exc:
                # Permanent failure (e.g., unsupported file type, corrupted file)
                logger.error(
                    "Permanent ingestion failure: document_id=%s error=%s",
                    document_id,
                    exc,
                )
                await _mark_failed(
                    db,
                    document_id,
                    f"Ingestion failed: {exc}",
                )
                # Don't re-raise — no point retrying permanent failures
                return
            except Exception as exc:
                # Transient failure (e.g., OpenAI timeout, Milvus connection)
                logger.exception(
                    "Transient ingestion failure: document_id=%s — will retry",
                    document_id,
                )
                await _mark_failed(
                    db,
                    document_id,
                    f"Transient error: {exc}",
                )
                # Re-raise for ARQ retry
                raise

    except Exception as exc:
        # Top-level catch for unexpected errors
        logger.exception(
            "Unexpected error in document processing: document_id=%s",
            document_id,
        )
        try:
            await _mark_failed(
                db,
                document_id,
                f"Unexpected error: {exc}",
            )
        except Exception:
            logger.exception("Failed to mark document as failed: document_id=%s", document_id)
        # Re-raise for ARQ retry
        raise


async def _mark_failed(db, document_id: str, reason: str) -> None:
    """Update document status to 'failed' with a reason.

    Args:
        db: asyncpg connection pool
        document_id: Document UUID
        reason: Human-readable failure reason
    """
    try:
        async with db.acquire() as conn:
            await conn.execute(
                """
                UPDATE documents
                SET status = 'failed', failure_reason = $2
                WHERE id = $1
                """,
                document_id,
                reason[:500],  # Truncate to avoid DB field overflow
            )
        logger.info(
            "Document marked as failed: document_id=%s reason=%s",
            document_id,
            reason[:100],
        )
    except Exception:
        logger.exception(
            "Failed to update document status to 'failed': document_id=%s",
            document_id,
        )
