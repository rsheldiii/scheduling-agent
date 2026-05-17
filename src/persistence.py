"""SQLite persistence layer for MCP scheduling requests."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, Session, SQLModel, create_engine

_DB_PATH = Path(os.getenv("DATA_DIR", str(Path(__file__).parent.parent / "data"))) / "requests.db"

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{_DB_PATH}")
    return _engine


class Request(SQLModel, table=True):
    request_id: str = Field(primary_key=True)
    scenario: str
    user_prompt: str
    call_instructions: str = Field(default="")
    questions: list = Field(sa_column=Column(JSON, nullable=False))
    answers: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    status: str = Field(default="awaiting_info")
    call_sid: str | None = Field(default=None)
    summary: str | None = Field(default=None)
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    SQLModel.metadata.create_all(_get_engine())


def create_request(
    *,
    request_id: str,
    scenario: str,
    user_prompt: str,
    call_instructions: str,
    questions: list[str],
) -> None:
    now = _now()
    with Session(_get_engine()) as session:
        session.add(Request(
            request_id=request_id,
            scenario=scenario,
            user_prompt=user_prompt,
            call_instructions=call_instructions,
            questions=questions,
            created_at=now,
            updated_at=now,
        ))
        session.commit()


def update_request(request_id: str, **kwargs: Any) -> None:
    if not kwargs:
        return
    with Session(_get_engine()) as session:
        request = session.get(Request, request_id)
        if request is None:
            return
        for key, value in kwargs.items():
            setattr(request, key, value)
        request.updated_at = _now()
        session.add(request)
        session.commit()


def get_request(request_id: str) -> Request | None:
    with Session(_get_engine()) as session:
        return session.get(Request, request_id)
