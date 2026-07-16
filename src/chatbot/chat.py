from src.database.exceptions import SessionAccessError
from src.database.fetch_data import get_session_context_from_db
from src.database.update_data import update_session_history
from src.logger import get_logger

logger = get_logger(__name__)


async def get_answer(
    session_id: str,
    user_id: str,
    user_query: str,
    db,
    chain,
    title_chain,
    session_context: dict | None = None,
) -> dict:
    if session_context is None:
        logger.debug("Loading session context in non-stream chat: session_id=%s user_id=%s", session_id, user_id)
        session_context = await get_session_context_from_db(
            session_id=session_id,
            user_id=user_id,
            db=db,
        )

    if session_context["foreign"]:
        raise SessionAccessError("Session does not belong to the current user")

    history = session_context["history"]
    logger.debug("Non-stream chat context: session_id=%s user_id=%s exists=%s history_len=%s", session_id, user_id, session_context["exists"], len(history))
    title = None
    if not session_context["exists"]:
        logger.info("New chat detected: session=%s user=%s", session_id, user_id)
        title = await title_chain.ainvoke({"query": user_query})
        title = str(title.content).strip() or "New Chat"
        logger.info("Generated title: %s", title)
    logger.debug("Invoking answer chain: session_id=%s user_id=%s", session_id, user_id)
    response = await chain.ainvoke({"chat_history": history, "query": user_query})

    metadata = response.response_metadata
    token_usage = metadata.get("token_usage") or {}
    final_response = str(response.content)
    model_used = str(metadata.get("model_name", "unknown"))
    finish_reason = str(metadata.get("finish_reason", "unknown"))
    total_token_used = int(token_usage.get("total_tokens", 0))
    time_taken = float(token_usage.get("total_time", 0.0))

    save_status = await update_session_history(
        session_id=session_id,
        user_id=user_id,
        user_message=user_query,
        ai_message=response,
        db=db,
        title=title,
    )
    if not save_status:
        logger.error("Failed to persist conversation history: session_id=%s user_id=%s", session_id, user_id)
        raise RuntimeError("Failed to persist conversation history")

    logger.info("Non-stream chat completed: session_id=%s user_id=%s model=%s tokens=%s finish_reason=%s", session_id, user_id, model_used, total_token_used, finish_reason)

    return {
        "answer": final_response,
        "model_used": model_used,
        "tokens": total_token_used,
        "latency_time": time_taken,
    }
