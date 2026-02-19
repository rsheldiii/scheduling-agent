from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agents import function_tool
from google.oauth2 import service_account
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/calendar"]

_service: Any = None


def _get_service() -> Any:
    global _service
    if _service is not None:
        return _service

    creds_path = os.getenv("GOOGLE_CALENDAR_CREDENTIALS")
    if not creds_path:
        raise RuntimeError("GOOGLE_CALENDAR_CREDENTIALS env var not set")

    creds_file = Path(creds_path)
    if not creds_file.exists():
        raise RuntimeError(f"Credentials file not found: {creds_file}")

    credentials = service_account.Credentials.from_service_account_file(
        str(creds_file), scopes=_SCOPES
    )
    _service = build("calendar", "v3", credentials=credentials)
    return _service


def _get_calendar_id() -> str:
    return os.getenv("GOOGLE_CALENDAR_ID", "primary")


@function_tool
def create_calendar_event(
    summary: str,
    start_datetime: str,
    end_datetime: str,
    description: str = "",
    location: str = "",
) -> str:
    """Create a Google Calendar event.

    Args:
        summary: Short title for the event (e.g. "Doctor appointment").
        start_datetime: ISO 8601 start time (e.g. "2026-03-05T14:00:00-05:00").
        end_datetime: ISO 8601 end time (e.g. "2026-03-05T15:00:00-05:00").
        description: Optional longer description of the event.
        location: Optional location string.
    """
    service = _get_service()
    calendar_id = _get_calendar_id()

    event_body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start_datetime},
        "end": {"dateTime": end_datetime},
    }
    if description:
        event_body["description"] = description
    if location:
        event_body["location"] = location

    created = service.events().insert(calendarId=calendar_id, body=event_body).execute()
    return f"Calendar event created: {created.get('htmlLink', created.get('id'))}"
