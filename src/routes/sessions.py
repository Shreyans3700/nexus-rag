from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from src.auth import get_current_user
from src.database.fetch_data import get_session_history_from_db, get_sessions_from_db
from src.logger import get_logger
from src.routes.dependencies import get_db
from src.schema.models import SessionHistoryResponse, SessionMetaData

logger = get_logger(__name__)

router = APIRouter(tags=["sessions"])


@router.get("/getSessionHistory")
async def get_session_history(
    session_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> SessionHistoryResponse:
    logger.debug("Session history request received: session_id=%s user_id=%s", session_id, current_user.id)
    try:
        session_history = await get_session_history_from_db(
            session_id=session_id,
            user_id=current_user.id,
            db=db,
        )
        if session_history is None:
            logger.warning("Session history not found for session_id=%s user_id=%s", session_id, current_user.id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        logger.info("Session history fetched: session_id=%s user_id=%s", session_id, current_user.id)
        return SessionHistoryResponse(
            session_id=session_id,
            title=session_history["title"] or session_id,
            history=session_history["history"],
            status_code=status.HTTP_200_OK,
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Get session history failed: session_id=%s user_id=%s", session_id, current_user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to fetch session history",
        ) from error


@router.get("/getSessionMetaData", response_model=List[SessionMetaData])
async def get_sessions(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> List[SessionMetaData]:
    logger.debug("Session metadata request received: user_id=%s", current_user.id)
    try:
        sessions = await get_sessions_from_db(db=db, user_id=current_user.id)
        logger.info("Session metadata fetched: user_id=%s count=%s", current_user.id, len(sessions))
        return sessions
    except Exception as error:
        logger.exception("Failed to fetch session metadata: user_id=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to fetch sessions metadata",
        ) from error
