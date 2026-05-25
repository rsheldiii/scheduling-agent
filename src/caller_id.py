"""Twilio Lookup v2 caller ID: network fetch and name sanitization."""
from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

_CALLER_NAME_SAFE_RE = re.compile(r"[^\w\s'\-.]", re.UNICODE)
_MAX_CALLER_NAME_LEN = 64


def _sanitize_caller_name(name: str | None) -> str | None:
    """Strip unusual characters and cap length before injecting into a prompt.

    Returns None for None input or names that are empty after sanitization.
    """
    if not name:
        return None
    sanitized = _CALLER_NAME_SAFE_RE.sub("", name).strip()
    return sanitized[:_MAX_CALLER_NAME_LEN] or None


async def _lookup_caller_name(from_number: str, account_sid: str, auth_token: str) -> str | None:
    """Look up the caller's name via the Twilio Lookup v2 API.

    Returns None if the name is unavailable or the request fails.
    """
    url = f"https://lookups.twilio.com/v2/PhoneNumbers/{from_number}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                url,
                params={"Fields": "caller_name"},
                auth=(account_sid, auth_token),
            )
            if resp.status_code == 200:
                data = resp.json()
                caller_name_obj = data.get("caller_name") or {}
                return caller_name_obj.get("caller_name")
            logger.warning("Caller ID lookup returned HTTP %s for %s", resp.status_code, from_number)
    except Exception:
        logger.warning("Caller ID lookup failed for %s", from_number, exc_info=True)
    return None
