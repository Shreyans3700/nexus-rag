"""
Document management routes.

POST /documents/upload   — Upload one or more files for a session (async ingestion).
GET  /documents          — List documents for a session.
DELETE /documents/{id}   — Delete a document from Postgres + Milvus.
"""
import uuid
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile, status

from src.auth import get_current_user
from src.config.config import MILVUS_COLLECTION_NAME
from src.documents.ingestor import ingest_document
from src.logger import get_logger
from src.routes.dependencies import get_db, get_milvus

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
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile],
    session_id: str = Form(..., min_length=1, max_length=128),
    db=Depends(get_db),
    milvus=Depends(get_milvus),
    current_user=Depends(get_current_user),
):
    """Accept one or more files and schedule async ingestion.

    Returns immediately with a list of document IDs and 'processing' status.
    Poll GET /documents?session_id=... to watch status change to 'ready'.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one file must be provided.",
        )

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

        # Insert metadata row — status starts as 'processing'
        try:
            async with db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO documents (id, user_id, session_id, filename, status)
                    VALUES ($1, $2, $3, $4, 'processing')
                    """,
                    document_id,
                    current_user.id,
                    session_id,
                    filename,
                )
        except Exception as exc:
            logger.exception(
                "Failed to insert document row: filename=%s user_id=%s",
                filename,
                current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to register document.",
            ) from exc

        # Schedule background ingestion — returns immediately
        background_tasks.add_task(
            ingest_document,
            document_id=document_id,
            user_id=current_user.id,
            session_id=session_id,
            filename=filename,
            content=content,
            db=db,
            milvus_client=milvus,
        )

        logger.info(
            "Document queued for ingestion: document_id=%s filename=%s user_id=%s session_id=%s",
            document_id,
            filename,
            current_user.id,
            session_id,
        )

        uploaded.append({
            "document_id": document_id,
            "filename": filename,
            "status": "processing",
        })

    return {"uploaded": uploaded}


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
    """Delete a document from Postgres (cascades to chunks) and from Milvus."""
    # Verify ownership before deleting
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id FROM documents
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

    logger.info(
        "Document deleted: document_id=%s user_id=%s", document_id, current_user.id
    )
    return {"deleted": document_id}
