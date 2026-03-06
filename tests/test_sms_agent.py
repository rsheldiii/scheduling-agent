"""Tests for SmsAgentManager — conversation tracking, eviction, message flow.

The Agent/Runner calls are mocked so these tests don't hit OpenAI.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_manager(ttl: float = 3600):
    """Build a SmsAgentManager with all external deps mocked out."""
    with patch("src.agent_factory.sms.agent.build_sms_tools", return_value=[]), \
         patch("src.agent_factory.sms.agent.load_user_info", return_value={"name": "Test User"}), \
         patch("src.agent_factory.sms.agent.render_template", side_effect=lambda t, _: t):
        from src.agent_factory.sms.agent import SmsAgentManager
        mgr = SmsAgentManager(
            ws_manager=MagicMock(),
            twilio_client=MagicMock(),
            phone_from="+15550001111",
            domain="example.com",
            conversation_ttl=ttl,
        )
    return mgr


class TestConversationTracking:
    @pytest.mark.asyncio
    async def test_new_conversation_created(self):
        mgr = _make_manager()
        mock_result = MagicMock(final_output="Hello back!")
        with patch("src.agent_factory.sms.agent.Runner.run", new_callable=AsyncMock, return_value=mock_result):
            reply = await mgr.handle_message("+15559999999", "Hi")

        assert reply == "Hello back!"
        assert "+15559999999" in mgr._conversations

    @pytest.mark.asyncio
    async def test_conversation_history_grows(self):
        mgr = _make_manager()
        mock_result = MagicMock(final_output="Reply")
        with patch("src.agent_factory.sms.agent.Runner.run", new_callable=AsyncMock, return_value=mock_result):
            await mgr.handle_message("+15559999999", "First")
            await mgr.handle_message("+15559999999", "Second")

        _, history = mgr._conversations["+15559999999"]
        assert len(history) == 4  # 2 user + 2 assistant

    @pytest.mark.asyncio
    async def test_separate_conversations_per_number(self):
        mgr = _make_manager()
        mock_result = MagicMock(final_output="Reply")
        with patch("src.agent_factory.sms.agent.Runner.run", new_callable=AsyncMock, return_value=mock_result):
            await mgr.handle_message("+15551111111", "Hi")
            await mgr.handle_message("+15552222222", "Hello")

        assert "+15551111111" in mgr._conversations
        assert "+15552222222" in mgr._conversations

    @pytest.mark.asyncio
    async def test_empty_reply_when_no_final_output(self):
        mgr = _make_manager()
        mock_result = MagicMock(final_output=None)
        with patch("src.agent_factory.sms.agent.Runner.run", new_callable=AsyncMock, return_value=mock_result):
            reply = await mgr.handle_message("+15559999999", "Hi")

        assert reply == ""


class TestConversationEviction:
    @pytest.mark.asyncio
    async def test_stale_conversations_evicted(self):
        mgr = _make_manager(ttl=0.0)  # immediate expiry
        mock_result = MagicMock(final_output="Reply")
        with patch("src.agent_factory.sms.agent.Runner.run", new_callable=AsyncMock, return_value=mock_result):
            await mgr.handle_message("+15551111111", "Old message")

        # Tiny sleep so monotonic time advances past TTL of 0
        time.sleep(0.01)

        with patch("src.agent_factory.sms.agent.Runner.run", new_callable=AsyncMock, return_value=mock_result):
            await mgr.handle_message("+15552222222", "New message")

        # Old conversation should have been evicted
        assert "+15551111111" not in mgr._conversations
        assert "+15552222222" in mgr._conversations


class TestHistoryTruncation:
    @pytest.mark.asyncio
    async def test_history_capped_at_max_turns(self):
        mgr = _make_manager()
        mock_result = MagicMock(final_output="R")
        with patch("src.agent_factory.sms.agent.Runner.run", new_callable=AsyncMock, return_value=mock_result):
            # _MAX_TURNS is 50, so 50*2 = 100 messages max
            for i in range(60):
                await mgr.handle_message("+15559999999", f"msg {i}")

        _, history = mgr._conversations["+15559999999"]
        assert len(history) <= 100  # 50 turns * 2 messages each
