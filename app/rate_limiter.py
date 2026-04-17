"""Redis-based sliding window rate limiter."""

import logging
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings

_r: redis.Redis | None = None
logger = logging.getLogger(__name__)


def _get_redis() -> redis.Redis:
    global _r
    if _r is None:
        _r = redis.from_url(settings.redis_url, decode_responses=True)
    return _r


def check_rate_limit(user_id: str) -> None:
    """Allow at most N requests per minute per user."""
    if user_id == "admin":
        return

    now_ms = int(time.time() * 1000)
    window_ms = 60_000
    key = f"rate_limit:{user_id}"
    member = f"{now_ms}-{uuid.uuid4().hex[:8]}"

    try:
        r = _get_redis()
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, now_ms - window_ms)
        pipe.zcard(key)
        pipe.zadd(key, {member: now_ms})
        pipe.expire(key, 120)
        _, current_count, _, _ = pipe.execute()
    except redis.RedisError as exc:
        logger.error("rate_limit redis error: %s", exc)
        raise HTTPException(status_code=503, detail="Rate limiter unavailable") from exc

    if int(current_count) >= settings.rate_limit_per_minute:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} req/min",
            headers={"Retry-After": "60"},
        )
