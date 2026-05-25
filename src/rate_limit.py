"""Rate limiting: per-caller incoming throttle and slowapi outgoing limit."""
from __future__ import annotations

import collections
import os
import time

from fastapi import FastAPI, HTTPException, Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import Response


def _rate_limit_key(request: Request) -> str:
    """Use the bearer token as the rate-limit key so limits are per-token."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)

_incoming_call_timestamps: dict[str, collections.deque[float]] = collections.defaultdict(
    collections.deque
)


def _check_incoming_rate_limit(from_number: str) -> None:
    """Raise 429 if this caller has exceeded the per-hour incoming call limit.

    Keyed by E.164 phone number so each caller has an independent window.
    Configurable via RATE_LIMIT_INCOMING_CALLS_PER_HOUR (default: 10).
    """
    limit = int(os.getenv("RATE_LIMIT_INCOMING_CALLS_PER_HOUR", "10"))
    now = time.monotonic()
    timestamps = _incoming_call_timestamps[from_number]
    cutoff = now - 3600
    while timestamps and timestamps[0] < cutoff:
        timestamps.popleft()
    if len(timestamps) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded for this caller")
    timestamps.append(now)


def _call_rate_limit() -> str:
    limit = os.getenv("RATE_LIMIT_CALLS_PER_HOUR", "30")
    return f"{limit}/hour"


def setup_limiter(app: FastAPI) -> None:
    """Attach slowapi state and exception handler to the FastAPI app."""
    app.state.limiter = limiter
    app.add_exception_handler(
        RateLimitExceeded,
        lambda request, exc: Response("Rate limit exceeded", status_code=429),
    )
