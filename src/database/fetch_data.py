from typing import Any, List

import tiktoken
from src.logger import get_logger
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, get_buffer_string, trim_messages

from src.config.config import MAX_CHAT_TOKENS, chat_model
from src.schema.models import Session, SessionMetaData

logger = get_logger(__name__)

MESSAGE_MAP = {
    "Human": HumanMessage,
    "AI": AIMessage,
}


def _get_encoding():
    try:
        return tiktoken.encoding_for_model(chat_model)
    except Exception:
        return tiktoken.get_encoding("cl100k_base")


def _count_tokens(messages: list[BaseMessage] | BaseMessage) -> int:
    if isinstance(messages, BaseMessage):
        messages = [messages]
    text = get_buffer_string(messages)
    return len(_get_encoding().encode(text))


async def get_sessions_from_db(db, user_id: str) -> List[SessionMetaData]:
    logger.debug("Fetching sessions from DB for user_id=%s", user_id)
    async with db.acquire() as connection:
        sessions = await connection.fetch(
            """
                SELECT session_id, title
                FROM sessions
                WHERE user_id = $1
                ORDER BY updated_at DESC, created_at DESC
            """,
            user_id,
        )

    logger.debug("Fetched sessions from DB for user_id=%s count=%s", user_id, len(sessions))
    return [
        SessionMetaData(
            session_id=row["session_id"],
            title=(row["title"] or row["session_id"]),
        )
        for row in sessions
    ]


async def get_session_context_from_db(session_id: str, user_id: str, db) -> dict[str, Any]:
    logger.debug("Fetching session context: session_id=%s user_id=%s", session_id, user_id)
    async with db.acquire() as connection:
        session_row = await connection.fetchrow(
            """
                SELECT title
                FROM sessions
                WHERE session_id = $1 AND user_id = $2
            """,
            session_id,
            user_id,
        )
        if session_row is None:
            foreign_exists = await connection.fetchval(
                """
                    SELECT 1
                    FROM sessions
                    WHERE session_id = $1
                """,
                session_id,
            )
            result = {
                "exists": False,
                "foreign": bool(foreign_exists),
                "title": None,
                "history": [],
            }
            logger.debug("Session context missing: session_id=%s user_id=%s foreign=%s", session_id, user_id, result["foreign"])
            return result

        rows = await connection.fetch(
            """
                SELECT id, role, content
                FROM messages
                WHERE session_id = $1
                ORDER BY created_at ASC, id ASC
            """,
            session_id,
        )

    history = [
        MESSAGE_MAP[row["role"]](content=row["content"])
        for row in rows
        if row["role"] in MESSAGE_MAP
    ]
    trimmed_history = trim_messages(
        history,
        max_tokens=MAX_CHAT_TOKENS,
        token_counter=_count_tokens,
        strategy="last",
        allow_partial=True,
    )
    result = {
        "exists": True,
        "foreign": False,
        "title": session_row["title"],
        "history": trimmed_history,
    }
    logger.debug(
        "Session context loaded: session_id=%s user_id=%s history_len=%s trimmed_len=%s",
        session_id,
        user_id,
        len(history),
        len(trimmed_history),
    )
    return result


async def get_session_history_from_db(
    session_id: str, user_id: str, db
) -> dict[str, Any] | None:
    logger.debug("Fetching session history: session_id=%s user_id=%s", session_id, user_id)
    context = await get_session_context_from_db(session_id=session_id, user_id=user_id, db=db)
    if context["foreign"] or not context["exists"]:
        return None

    async with db.acquire() as connection:
        rows = await connection.fetch(
            """
                SELECT id, role, content
                FROM messages
                WHERE session_id = $1
                ORDER BY created_at ASC, id ASC
            """,
            session_id,
        )

    history = [
        Session(sequence_no=row["id"], role=row["role"], content=row["content"])
        for row in rows
    ]
    logger.debug("Fetched session history rows: session_id=%s user_id=%s count=%s", session_id, user_id, len(history))
    return {"history": history, "title": context["title"]}


