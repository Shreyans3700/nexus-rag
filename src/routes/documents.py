"""
Document management routes.

POST /documents/upload             — Upload files to MinIO and enqueue for processing
GET  /documents                    — List documents for a session
GET  /documents/{document_id}/status — Poll document processing status
DELETE /documents/{id}             — Delete a document from Postgres + Milvus + MinIO
"""
import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status

from src.auth import get_current_user
from src.config.arq_config import get_redis_pool
from src.config.config import MILVUS_COLLECTION_NAME
from src.logger import get_logger
from src.rate_limit import limiter
from src.routes.dependencies import get_db, get_milvus
from src.storage.minio_client import get_minio_client

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}


def _check_extension(filename: str) -> None:
    import os
    ext = os.path.splitext(filename.lower())[1]
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"File '{filename}' has unsupported extension '{ext}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            ),
        )


# ---------------------------------------------------------------------------
# POST /documents/upload
# ---------------------------------------------------------------------------
@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/minute")
async def upload_documents(
    request: Request,
    files: List[UploadFile],
    session_id: str = Form(..., min_length=1, max_length=128),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Upload files to MinIO and enqueue for async processing.

    This endpoint:
    1. Validates file extensions
    2. Uploads raw files to MinIO
    3. Inserts metadata rows with status='queued'
    4. Enqueues jobs in Redis for ARQ workers
    5. Returns immediately with document IDs

    Poll GET /documents/{document_id}/status to watch progress.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one file must be provided.",
        )

    minio_client = get_minio_client()
    redis_pool = await get_redis_pool()
    minio_bucket = os.getenv("MINIO_BUCKET", "documents")

    uploaded = []

    for upload in files:
        filename = upload.filename or "untitled"
        _check_extension(filename)

        content = await upload.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"File '{filename}' is empty.",
            )

        document_id = str(uuid.uuid4())
        
        # Generate MinIO object name with extension preserved
        ext = os.path.splitext(filename.lower())[1]
        object_name = f"{document_id}{ext}"

        # ------------------------------------------------------------------ #
        # 1. Upload file to MinIO
        # ------------------------------------------------------------------ #
        try:
            minio_client.upload_file(
                bucket=minio_bucket,
                object_name=object_name,
                data=content,
            )
            logger.info(
                "Uploaded file to MinIO: document_id=%s object=%s size=%s",
                document_id,
                object_name,
                len(content),
            )
        except Exception as exc:
            logger.exception(
                "Failed to upload file to MinIO: filename=%s user_id=%s",
                filename,
                current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload file '{filename}' to storage.",
            ) from exc

        # ------------------------------------------------------------------ #
        # 2. Insert metadata row with status='queued'
        # ------------------------------------------------------------------ #
        try:
            async with db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO documents (id, user_id, session_id, filename, object_name, status)
                    VALUES ($1, $2, $3, $4, $5, 'queued')
                    """,
                    document_id,
                    current_user.id,
                    session_id,
                    filename,
                    object_name,
                )
        except Exception as exc:
            logger.exception(
                "Failed to insert document row: filename=%s user_id=%s",
                filename,
                current_user.id,
            )
            # Try to clean up MinIO object if metadata insert fails
            try:
                minio_client.delete_file(minio_bucket, object_name)
            except Exception:
                logger.warning(
                    "Failed to clean up MinIO object after metadata insert failure: %s",
                    object_name,
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to register document.",
            ) from exc

        # ------------------------------------------------------------------ #
        # 3. Enqueue job in Redis
        # ------------------------------------------------------------------ #
        try:
            job = await redis_pool.enqueue_job(
                "process_document",
                document_id,
            )
            logger.info(
                "Enqueued document for processing: document_id=%s job_id=%s filename=%s user_id=%s",
                document_id,
                job.job_id if job else "unknown",
                filename,
                current_user.id,
            )
        except Exception as exc:
            logger.exception(
                "Failed to enqueue document job: document_id=%s filename=%s",
                document_id,
                filename,
            )
            # Update status to 'failed' if enqueue fails
            try:
                async with db.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE documents
                        SET status = 'failed', failure_reason = 'Failed to enqueue job'
                        WHERE id = $1
                        """,
                        document_id,
                    )
            except Exception:
                logger.exception("Failed to update document status after enqueue failure")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to queue document '{filename}' for processing.",
            ) from exc

        uploaded.append({
            "document_id": document_id,
            "filename": filename,
            "status": "queued",
        })

    return {"uploaded": uploaded}


# ---------------------------------------------------------------------------
# GET /documents/{document_id}/status
# ---------------------------------------------------------------------------
@router.get("/{document_id}/status")
async def get_document_status(
    document_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Poll document processing status.

    Returns:
        {
            "document_id": str,
            "status": "queued" | "processing" | "ready" | "failed",
            "failure_reason": str | null
        }
    """
    try:
        async with db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT status, failure_reason
                FROM documents
                WHERE id = $1 AND user_id = $2
                """,
                document_id,
                current_user.id,
            )
    except Exception as exc:
        logger.exception(
            "Failed to fetch document status: document_id=%s user_id=%s",
            document_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve document status.",
        ) from exc

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    return {
        "document_id": document_id,
        "status": row["status"],
        "failure_reason": row["failure_reason"],
    }


# ---------------------------------------------------------------------------
# GET /documents
# ---------------------------------------------------------------------------
@router.get("")
async def list_documents(
    session_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all documents uploaded by the current user for a given session."""
    try:
        async with db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, filename, status, chunk_count, uploaded_at
                FROM documents
                WHERE user_id = $1 AND session_id = $2
                ORDER BY uploaded_at DESC
                """,
                current_user.id,
                session_id,
            )
    except Exception as exc:
        logger.exception(
            "Failed to list documents: user_id=%s session_id=%s",
            current_user.id,
            session_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve documents.",
        ) from exc

    return [
        {
            "document_id": row["id"],
            "filename": row["filename"],
            "status": row["status"],
            "chunk_count": row["chunk_count"],
            "uploaded_at": row["uploaded_at"].isoformat() if row["uploaded_at"] else None,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# DELETE /documents/{document_id}
# ---------------------------------------------------------------------------
@router.delete("/{document_id}", status_code=status.HTTP_200_OK)
async def delete_document(
    document_id: str,
    db=Depends(get_db),
    milvus=Depends(get_milvus),
    current_user=Depends(get_current_user),
):
    """Delete a document from Postgres (cascades to chunks), Milvus, and MinIO."""
    minio_client = get_minio_client()
    minio_bucket = os.getenv("MINIO_BUCKET", "documents")
    
    # Verify ownership and get object_name before deleting
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, object_name FROM documents
            WHERE id = $1 AND user_id = $2
            """,
            document_id,
            current_user.id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found.",
            )

        object_name = row["object_name"]

        # Delete from Postgres — ON DELETE CASCADE removes document_chunks rows too
        try:
            await conn.execute(
                "DELETE FROM documents WHERE id = $1",
                document_id,
            )
        except Exception as exc:
            logger.exception(
                "Failed to delete document from Postgres: document_id=%s", document_id
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete document.",
            ) from exc

    # Delete vectors from Milvus (best-effort — log but don't fail if Milvus is down)
    try:
        milvus.delete(
            collection_name=MILVUS_COLLECTION_NAME,
            filter=f'document_id == "{document_id}"',
        )
        logger.info(
            "Deleted Milvus vectors: document_id=%s user_id=%s",
            document_id,
            current_user.id,
        )
    except Exception:
        logger.warning(
            "Milvus delete failed (non-fatal): document_id=%s — vectors may linger until next collection cleanup",
            document_id,
        )

    # Delete file from MinIO (best-effort — log but don't fail)
    if object_name:
        try:
            minio_client.delete_file(minio_bucket, object_name)
            logger.info(
                "Deleted MinIO object: document_id=%s object=%s user_id=%s",
                document_id,
                object_name,
                current_user.id,
            )
        except Exception:
            logger.warning(
                "MinIO delete failed (non-fatal): document_id=%s object=%s — file may linger in storage",
                document_id,
                object_name,
            )

    logger.info(
        "Document deleted: document_id=%s user_id=%s", document_id, current_user.id
    )
    return {"deleted": document_id}
