"""Persistent call memory — simple append-only log readable by all agents."""
from __future__ import annotations

from datetime import datetime, timezone

from agents import function_tool
from sqlmodel import Field, Session, SQLModel, select

from ..persistence import _get_engine, init_db


class MemoryEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: str
    content: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_table() -> None:
    SQLModel.metadata.create_all(_get_engine())


def load_memory() -> str:
    """Return all memory entries as a single text block, oldest first.

    Returns an empty string if there are no entries yet.
    """
    _ensure_table()
    with Session(_get_engine()) as session:
        entries = session.exec(select(MemoryEntry).order_by(MemoryEntry.id)).all()
    if not entries:
        return ""
    lines = [f"[{e.created_at}] {e.content}" for e in entries]
    return "\n".join(lines)


@function_tool
def get_memory() -> str:
    """Retrieve the persistent call memory — a chronological log of past call outcomes.
    Use this at the start of a call to check whether there is relevant prior context
    (e.g. a previous attempt, a callback that was expected, a partial outcome).
    Returns an empty string if no memory has been recorded yet.
    """
    return load_memory() or "(no memory recorded yet)"


@function_tool
def add_memory(entry: str) -> str:
    """Append a new entry to the persistent call memory.
    Call this after every call to record what happened: who was called, what the outcome
    was, and any unresolved items (e.g. 'awaiting callback', 'appointment unconfirmed').
    This is the only record that persists across sessions.
    """
    _ensure_table()
    with Session(_get_engine()) as session:
        session.add(MemoryEntry(created_at=_now(), content=entry))
        session.commit()
    return "Memory recorded."
