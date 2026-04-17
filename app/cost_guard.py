"""Monthly budget guard backed by Redis."""

import logging
from datetime import datetime

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


def estimate_cost_usd(question: str, answer: str) -> float:
    """Simple token-cost estimation for mock LLM usage."""
    input_tokens = max(1, len(question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2) if answer else 0
    return (input_tokens / 1000) * 0.00015 + (output_tokens / 1000) * 0.00060


def check_budget(user_id: str, estimated_cost: float) -> None:
    """Reject request if monthly budget would be exceeded."""
    if estimated_cost <= 0:
        return

    month_key = datetime.now().strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"

    try:
        r = _get_redis()
        current_raw = r.get(key)
        current = float(current_raw) if current_raw else 0.0
        if current + estimated_cost > settings.monthly_budget_usd:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Monthly budget exceeded: ${settings.monthly_budget_usd:.2f} limit"
                ),
            )

        pipe = r.pipeline()
        pipe.incrbyfloat(key, estimated_cost)
        pipe.expire(key, 32 * 24 * 3600)
        pipe.execute()
    except HTTPException:
        raise
    except redis.RedisError as exc:
        logger.error("budget redis error: %s", exc)
        raise HTTPException(status_code=503, detail="Budget service unavailable") from exc


def record_cost(user_id: str, cost: float) -> None:
    """Record actual cost after a request completes (no budget check, safe to call inside generators)."""
    if cost <= 0:
        return
    month_key = datetime.now().strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"
    try:
        r = _get_redis()
        pipe = r.pipeline()
        pipe.incrbyfloat(key, cost)
        pipe.expire(key, 32 * 24 * 3600)
        pipe.execute()
    except redis.RedisError as exc:
        logger.error("record_cost redis error: %s", exc)
