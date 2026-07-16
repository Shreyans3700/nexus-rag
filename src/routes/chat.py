from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from src.auth import get_current_user
from src.chatbot.chat import get_answer
from src.chatbot.stream import stream_answer
from src.database.exceptions import SessionAccessError
from src.database.fetch_data import get_session_context_from_db
from src.logger import get_logger
from src.routes.dependencies import get_chain, get_db, get_title_chain
from src.schema.models import RequestModel, ResponseModel

logger = get_logger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ResponseModel)
async def chat_with_bot(
    request: RequestModel,
    db=Depends(get_db),
    chain=Depends(get_chain),
    title_chain=Depends(get_title_chain),
    current_user=Depends(get_current_user),
) -> ResponseModel:
    logger.debug("Chat request received: session_id=%s user_id=%s query_len=%s", request.session_id, current_user.id, len(request.user_query))
    try:
        session_context = await get_session_context_from_db(
            session_id=request.session_id,
            user_id=current_user.id,
            db=db,
        )
        if session_context["foreign"]:
            logger.warning("Chat request rejected for foreign session: session_id=%s user_id=%s", request.session_id, current_user.id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        response = await get_answer(
            session_id=request.session_id,
            user_id=current_user.id,
            user_query=request.user_query,
            chain=chain,
            title_chain=title_chain,
            db=db,
            session_context=session_context,
        )
    except SessionAccessError as error:
        logger.warning("Chat request access denied: session_id=%s user_id=%s", request.session_id, current_user.id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from error
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Chat request failed: session_id=%s user_id=%s", request.session_id, current_user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to generate a response",
        ) from error

    logger.info("Chat request completed: session_id=%s user_id=%s", request.session_id, current_user.id)
    return ResponseModel(
        session_id=request.session_id,
        user_query=request.user_query,
        answer=response["answer"],
        model_used=response["model_used"],
        tokens_used=response["tokens"],
        latency_time=response["latency_time"],
        status_code=status.HTTP_200_OK,
    )


@router.post("/chat/stream")
async def stream_chat(
    request: RequestModel,
    db=Depends(get_db),
    chain=Depends(get_chain),
    title_chain=Depends(get_title_chain),
    current_user=Depends(get_current_user),
) -> StreamingResponse:
    logger.debug("Stream request received: session_id=%s user_id=%s query_len=%s", request.session_id, current_user.id, len(request.user_query))
    try:
        session_context = await get_session_context_from_db(
            session_id=request.session_id,
            user_id=current_user.id,
            db=db,
        )
        if session_context["foreign"]:
            logger.warning("Chat request rejected for foreign session: session_id=%s user_id=%s", request.session_id, current_user.id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        return StreamingResponse(
            stream_answer(
                session_id=request.session_id,
                user_id=current_user.id,
                user_query=request.user_query,
                chain=chain,
                db=db,
                title_chain=title_chain,
                session_context=session_context,
            ),
            media_type="text/event-stream",
            status_code=status.HTTP_200_OK,
        )
    except SessionAccessError as error:
        logger.warning("Chat request access denied: session_id=%s user_id=%s", request.session_id, current_user.id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from error
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Stream request failed: session_id=%s user_id=%s", request.session_id, current_user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to generate a response",
        ) from error
