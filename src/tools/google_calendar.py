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

    json_content = os.getenv("GOOGLE_CALENDAR_CREDENTIALS_JSON")
    if json_content:
        import json

        info = json.loads(json_content)
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=_SCOPES
        )
    else:
        creds_path = os.getenv("GOOGLE_CALENDAR_CREDENTIALS")
        if not creds_path:
            raise RuntimeError(
                "Either GOOGLE_CALENDAR_CREDENTIALS_JSON or GOOGLE_CALENDAR_CREDENTIALS env var must be set"
            )
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
def get_calendar_events(start_date: str, end_date: str) -> str:
    """List calendar events between two dates to check the user's availability.

    Args:
        start_date: ISO 8601 date or datetime (e.g. "2026-04-22" or "2026-04-22T00:00:00-05:00").
        end_date: ISO 8601 date or datetime, exclusive upper bound.

    Returns a list of events with their title, start, end, and whether they are
    all-day. Use judgment to decide if an event is exclusionary — a vague all-day
    event like "get flowers" is probably not; a specific commitment like "run the
    Boston Marathon" or a timed appointment likely is.
    """
    service = _get_service()
    calendar_id = _get_calendar_id()

    def _to_rfc3339(s: str) -> str:
        if "T" not in s:
            return f"{s}T00:00:00Z"
        return s

    try:
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=_to_rfc3339(start_date),
                timeMax=_to_rfc3339(end_date),
                singleEvents=True,
                orderBy="startTime",
                maxResults=50,
            )
            .execute()
        )
    except Exception as e:
        return f"Failed to fetch calendar events: {e}"

    items = result.get("items", [])
    if not items:
        return "No events found in that range."

    lines: list[str] = []
    for event in items:
        summary = event.get("summary", "(no title)")
        start = event.get("start", {})
        end = event.get("end", {})
        if "date" in start:
            lines.append(f"- [all-day] {summary}: {start['date']} to {end.get('date', '?')}")
        else:
            lines.append(f"- {summary}: {start.get('dateTime', '?')} to {end.get('dateTime', '?')}")
    return "\n".join(lines)


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
