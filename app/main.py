"""Main application for Day 12 Lab 6 production-ready agent."""

import json
import logging
import signal
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_cost_usd, record_cost
from app.rate_limiter import check_rate_limit
from utils.mock_llm import ask as llm_ask
from utils.mock_llm import ask_stream as llm_ask_stream


def _setup_logger() -> logging.Logger:
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
    logger_instance = logging.getLogger("app")
    return logger_instance


logger = _setup_logger()
START_TIME = time.time()
_is_ready = False
_is_draining = False
_request_count = 0
_error_count = 0
_redis_client: redis.Redis | None = None


def log_event(event: str, **fields: object) -> None:
    payload = {
        "event": event,
        "ts": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    logger.info(json.dumps(payload, ensure_ascii=True))


def _build_history(user_id: str) -> list[dict]:
    if _redis_client is None:
        return []
    key = f"history:{user_id}"
    raw_messages = _redis_client.lrange(key, 0, -1)
    history: list[dict] = []
    for item in raw_messages:
        try:
            history.append(json.loads(item))
        except json.JSONDecodeError:
            continue
    return history


def _append_history(user_id: str, role: str, content: str) -> None:
    if _redis_client is None:
        return
    key = f"history:{user_id}"
    msg = {
        "role": role,
        "content": content,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    _redis_client.rpush(key, json.dumps(msg, ensure_ascii=True))
    _redis_client.ltrim(key, -settings.history_max_messages, -1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready, _redis_client
    log_event("startup", app=settings.app_name, version=settings.app_version)
    try:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        _redis_client.ping()
        _is_ready = True
        log_event("ready", redis="ok")
    except Exception as exc:
        _is_ready = False
        log_event("ready_failed", error=str(exc))

    yield

    _is_ready = False
    if _redis_client is not None:
        _redis_client.close()
    log_event("shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    global _request_count, _error_count
    if _is_draining and request.url.path not in ("/health", "/ready"):
        raise HTTPException(status_code=503, detail="Server is shutting down")

    started = time.time()
    _request_count += 1
    try:
        response: Response = await call_next(request)
    except Exception:
        _error_count += 1
        raise

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers.pop("server", None)

    log_event(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.time() - started) * 1000, 1),
    )
    return response


class AskRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    question: str = Field(..., min_length=1, max_length=2000)


class AskResponse(BaseModel):
    user_id: str
    question: str
    answer: str
    model: str
    history_count: int
    timestamp: str


@app.get("/")
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "endpoints": ["POST /ask", "POST /ask/stream", "GET /health", "GET /ready"],
    }


@app.post("/ask", response_model=AskResponse)
def ask_agent(body: AskRequest, _api_key: str = Depends(verify_api_key)):
    check_rate_limit(body.user_id)

    estimated_cost = estimate_cost_usd(body.question, "")
    check_budget(body.user_id, estimated_cost)

    history = _build_history(body.user_id)
    _append_history(body.user_id, "user", body.question)

    answer = llm_ask(body.question)
    _append_history(body.user_id, "assistant", answer)

    final_cost = estimate_cost_usd(body.question, answer)
    check_budget(body.user_id, final_cost - estimated_cost)

    return AskResponse(
        user_id=body.user_id,
        question=body.question,
        answer=answer,
        model=settings.llm_model,
        history_count=len(history) + 2,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/ask/stream")
def ask_stream(body: AskRequest, _api_key: str = Depends(verify_api_key)):
    check_rate_limit(body.user_id)
    check_budget(body.user_id, estimate_cost_usd(body.question, ""))
    _append_history(body.user_id, "user", body.question)

    def _generator():
        collected = []
        for chunk in llm_ask_stream(body.question):
            collected.append(chunk)
            yield chunk
        full_answer = "".join(collected).strip()
        _append_history(body.user_id, "assistant", full_answer)
        # Use record_cost instead of check_budget: streaming has already started,
        # so raising HTTPException here would corrupt the response.
        record_cost(body.user_id, estimate_cost_usd(body.question, full_answer))

    return StreamingResponse(_generator(), media_type="text/plain")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    if not _is_ready or _redis_client is None:
        raise HTTPException(status_code=503, detail="Not ready")
    try:
        _redis_client.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    return {"status": "ready"}


@app.get("/metrics")
def metrics(_api_key: str = Depends(verify_api_key)):
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "error_count": _error_count,
    }


def _handle_sigterm(signum, _frame):
    global _is_draining
    _is_draining = True
    log_event("signal", signal="SIGTERM", signum=signum)


signal.signal(signal.SIGTERM, _handle_sigterm)


if __name__ == "__main__":
    log_event("boot", host=settings.host, port=settings.port)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
