"""Redis-backed rate limiting shared across routers.

Uses the same Redis instance as the ARQ task queue (REDIS_HOST/PORT/DB), so
limits are enforced correctly across multiple uvicorn workers/replicas
instead of resetting per-process.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.config.config import REDIS_DB, REDIS_HOST, REDIS_PORT

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
)
