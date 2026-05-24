"""Tests for the call duration hard cap in TwilioHandler._end_call_watcher."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.twilio_handler import TwilioHandler


def _make_handler() -> TwilioHandler:
    ws = AsyncMock()
    agent = MagicMock()
    agent.tools = []
    return TwilioHandler(ws, agent)


class TestEndCallWatcher:
    @pytest.mark.asyncio
    async def test_closes_websocket_when_end_call_fires(self):
        """Normal path: end_call event fires and WebSocket is closed."""
        handler = _make_handler()
        handler._end_call_event.set()
        await handler._end_call_watcher()
        handler.twilio_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_closes_websocket_on_duration_timeout(self, monkeypatch):
        """WebSocket must be closed even when the call times out without end_call."""
        monkeypatch.setenv("MAX_CALL_DURATION_SECONDS", "0.05")
        handler = _make_handler()
        # end_call_event is never set — timeout fires instead
        await handler._end_call_watcher()
        handler.twilio_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_duration_is_600(self, monkeypatch):
        """Default MAX_CALL_DURATION_SECONDS must be 600."""
        monkeypatch.delenv("MAX_CALL_DURATION_SECONDS", raising=False)
        handler = _make_handler()
        handler._end_call_event.set()

        with patch("asyncio.timeout") as mock_timeout:
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=None)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_timeout.return_value = mock_ctx
            await handler._end_call_watcher()

        # asyncio.timeout is also called by _wait_for_marks_drained(timeout=10.0)
        mock_timeout.assert_any_call(600.0)

    @pytest.mark.asyncio
    async def test_custom_duration_is_respected(self, monkeypatch):
        """Custom MAX_CALL_DURATION_SECONDS env var must be used."""
        monkeypatch.setenv("MAX_CALL_DURATION_SECONDS", "120")
        handler = _make_handler()
        handler._end_call_event.set()

        with patch("asyncio.timeout") as mock_timeout:
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=None)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_timeout.return_value = mock_ctx
            await handler._end_call_watcher()

        mock_timeout.assert_any_call(120.0)

    @pytest.mark.asyncio
    async def test_cancelled_task_does_not_raise(self):
        """CancelledError must be swallowed cleanly."""
        handler = _make_handler()

        async def _watcher_then_cancel():
            task = asyncio.create_task(handler._end_call_watcher())
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # should not propagate

        await _watcher_then_cancel()
