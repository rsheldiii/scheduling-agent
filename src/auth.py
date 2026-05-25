"""Bearer-token authentication for the FastAPI server."""
from __future__ import annotations

import logging
import secrets
from functools import lru_cache

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .secrets import get_secret

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer()


@lru_cache
def _get_bearer_token() -> str:
    """Return the API bearer token, generating one if not configured."""
    token = get_secret("api_bearer_token", "API_BEARER_TOKEN")
    if token:
        return token
    token = secrets.token_urlsafe(32)
    logger.warning("API_BEARER_TOKEN not set — generated token: %s", token)
    return token


async def _validate_bearer_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> None:
    """FastAPI dependency that validates the Authorization: Bearer header."""
    if credentials.credentials != _get_bearer_token():
        raise HTTPException(status_code=401, detail="Invalid bearer token")
