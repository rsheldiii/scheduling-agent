"""Shared fixtures and helpers for the test suite."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml


@pytest.fixture()
def tmp_prompts(tmp_path: Path) -> Path:
    """Create a temporary prompts directory with sample YAML files.

    Layout::

        tmp_path/
            default.yaml
            incoming/
                default.yaml
            outgoing/
                doctor_appointment.yaml
                restaurant_reservation.yaml
    """
    # Root-level prompt
    _write_prompt(tmp_path / "default.yaml", name="Root Default", description="root desc")

    # incoming/
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    _write_prompt(incoming / "default.yaml", name="Incoming Default", description="inc desc")

    # outgoing/
    outgoing = tmp_path / "outgoing"
    outgoing.mkdir()
    _write_prompt(
        outgoing / "doctor_appointment.yaml",
        name="Doctor Appointment",
        description="doc desc",
        required_context=["preferred date", "doctor name"],
        voice="alloy",
    )
    _write_prompt(
        outgoing / "restaurant_reservation.yaml",
        name="Restaurant Reservation",
        description="resto desc",
    )

    return tmp_path


def _write_prompt(
    path: Path,
    *,
    name: str,
    description: str,
    instructions: str = "You are a test assistant.",
    required_context: list[str] | None = None,
    voice: str | None = None,
) -> None:
    data: dict[str, Any] = {
        "name": name,
        "description": description,
        "instructions": instructions,
    }
    if required_context:
        data["required_context"] = required_context
    if voice:
        data["voice"] = voice
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


class FakeHistoryItem:
    """Lightweight stand-in for a Realtime API transcript item."""

    def __init__(self, role: str, content: list[Any]):
        self.role = role
        self.content = content


class FakeContentEntry:
    """Stand-in for a content entry with optional transcript/text fields."""

    def __init__(self, transcript: str | None = None, text: str | None = None):
        self.transcript = transcript
        self.text = text
