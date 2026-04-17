"""Authentication helpers."""

import secrets

from fastapi import Header, HTTPException

from app.config import settings


def verify_api_key(x_api_key: str = Header(default="", alias="X-API-Key")) -> str:
    """Validate API key from request header."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    if not secrets.compare_digest(x_api_key, settings.agent_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key
