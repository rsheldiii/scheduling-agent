"""Tests for TwilioHandler.get_transcript().

We instantiate TwilioHandler with dummy dependencies and directly populate
its _history list to test transcript formatting in isolation, without needing
a real WebSocket or OpenAI session.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.twilio_handler import TwilioHandler
from tests.conftest import FakeContentEntry, FakeHistoryItem


def _make_handler() -> TwilioHandler:
    """Build a TwilioHandler with a stubbed WebSocket and agent."""
    ws = MagicMock()
    agent = MagicMock()
    return TwilioHandler(twilio_websocket=ws, agent=agent)


class TestGetTranscript:
    def test_empty_history(self):
        handler = _make_handler()
        assert handler.get_transcript() == ""

    def test_single_user_message(self):
        handler = _make_handler()
        handler._history = [
            FakeHistoryItem("user", [FakeContentEntry(transcript="Hello")])
        ]
        assert handler.get_transcript() == "User: Hello"

    def test_single_assistant_message(self):
        handler = _make_handler()
        handler._history = [
            FakeHistoryItem("assistant", [FakeContentEntry(transcript="Hi there!")])
        ]
        assert handler.get_transcript() == "Assistant: Hi there!"

    def test_multi_turn_conversation(self):
        handler = _make_handler()
        handler._history = [
            FakeHistoryItem("user", [FakeContentEntry(transcript="Book me an appointment")]),
            FakeHistoryItem("assistant", [FakeContentEntry(transcript="Sure, when works for you?")]),
            FakeHistoryItem("user", [FakeContentEntry(transcript="Next Tuesday")]),
        ]
        lines = handler.get_transcript().splitlines()
        assert len(lines) == 3
        assert lines[0].startswith("User:")
        assert lines[1].startswith("Assistant:")
        assert lines[2].startswith("User:")

    def test_falls_back_to_text_attribute(self):
        handler = _make_handler()
        handler._history = [
            FakeHistoryItem("user", [FakeContentEntry(text="via text attr")])
        ]
        assert handler.get_transcript() == "User: via text attr"

    def test_transcript_preferred_over_text(self):
        handler = _make_handler()
        handler._history = [
            FakeHistoryItem("user", [FakeContentEntry(transcript="preferred", text="fallback")])
        ]
        assert handler.get_transcript() == "User: preferred"

    def test_multiple_content_entries_joined(self):
        handler = _make_handler()
        handler._history = [
            FakeHistoryItem("assistant", [
                FakeContentEntry(transcript="Part one."),
                FakeContentEntry(transcript="Part two."),
            ])
        ]
        assert handler.get_transcript() == "Assistant: Part one. Part two."

    def test_items_without_role_skipped(self):
        handler = _make_handler()
        handler._history = [
            {"some": "dict"},  # no role/content attrs
            FakeHistoryItem("user", [FakeContentEntry(transcript="Real message")]),
        ]
        assert handler.get_transcript() == "User: Real message"

    def test_items_with_empty_content_skipped(self):
        handler = _make_handler()
        handler._history = [
            FakeHistoryItem("user", [FakeContentEntry()]),
            FakeHistoryItem("assistant", [FakeContentEntry(transcript="Reply")]),
        ]
        assert handler.get_transcript() == "Assistant: Reply"
