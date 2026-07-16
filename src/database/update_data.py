import json
from typing import Any

from langchain_core.messages import AIMessage

from src.database.exceptions import SessionAccessError
from src.logger import get_logger

logger = get_logger(__name__)


def _serialize_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text_value = item.get("text")
                if text_value:
                    parts.append(str(text_value))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        try:
            return json.dumps(content, ensure_ascii=False)
        except TypeError:
            return str(content)
    return str(content)


def _build_fallback_title(user_message: str) -> str:
    cleaned = " ".join(user_message.split()).strip()
    if not cleaned:
        return "New Chat"
    return cleaned[:80]


async def update_session_history(
    session_id: str,
    user_id: str,
    user_message: str,
    ai_message: AIMessage,
    db,
    title: str | None,
) -> bool:
    logger.debug("Persisting session history: session_id=%s user_id=%s title_present=%s", session_id, user_id, bool(title))
    user_content = _serialize_message_content(user_message)
    ai_content = _serialize_message_content(
        ai_message.content if hasattr(ai_message, "content") else ai_message
    )
    try:
        async with db.acquire() as connection:
            async with connection.transaction():
                session_row = await connection.fetchrow(
                    """
                    SELECT user_id
                    FROM sessions
                    WHERE session_id = $1
                    """,
                    session_id,
                )

                if session_row is None:
                    session_title = (title or _build_fallback_title(user_content)).strip()
                    logger.debug("Creating new session row: session_id=%s user_id=%s title=%r", session_id, user_id, session_title[:128])
                    await connection.execute(
                        """
                        INSERT INTO sessions (session_id, user_id, title)
                        VALUES ($1, $2, $3)
                        """,
                        session_id,
                        user_id,
                        session_title[:128],
                    )
                else:
                    stored_user_id = str(session_row["user_id"])
                    if stored_user_id != str(user_id):
                        logger.warning("Session ownership mismatch: session_id=%s stored_user_id=%s requested_user_id=%s", session_id, stored_user_id, user_id)
                        raise SessionAccessError(
                            "Session does not belong to the current user"
                        )

                await connection.execute(
                    """
                    INSERT INTO messages (session_id, role, content)
                    VALUES ($1, 'Human', $2)
                    """,
                    session_id,
                    user_content,
                )
                await connection.execute(
                    """
                    INSERT INTO messages (session_id, role, content)
                    VALUES ($1, 'AI', $2)
                    """,
                    session_id,
                    ai_content,
                )
                await connection.execute(
                    """
                    UPDATE sessions
                    SET updated_at = NOW()
                    WHERE session_id = $1 AND user_id = $2
                    """,
                    session_id,
                    user_id,
                )
        logger.info("Persisted session history successfully: session_id=%s user_id=%s", session_id, user_id)
        return True
    except SessionAccessError:
        raise
    except Exception:
        logger.exception(
            "Failed to persist conversation history for session %s user_id=%s", session_id, user_id
        )
        return False
