import uvicorn
from fastapi import FastAPI

from src.config.config import set_environment
from src.logger import configure_logging, get_logger
from src.routes import auth_router, chat_router, sessions_router

configure_logging()
logger = get_logger(__name__)

app = FastAPI(
    title="EndToEndChatBot",
    description="Complete Chatbot with persistent history",
    version="0.0.1",
    lifespan=set_environment,
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(sessions_router)


@app.get("/")
async def index():
    logger.debug("Health check requested")
    return {"service": "EndToEndChatBot", "status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app=app, host="0.0.0.0", port=8000)
