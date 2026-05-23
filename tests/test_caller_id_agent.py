"""Tests for caller ID integration in the incoming call agent factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_agent_with_voice(instructions: str):
    """Patch out the heavy dependencies and call create_incoming_call_agent."""
    from src.agent_factory.realtime.agent import create_incoming_call_agent

    mock_agent = MagicMock()
    mock_agent.name = "Test"

    with (
        patch("src.agent_factory.realtime.agent.load_user_info", return_value={}),
        patch("src.agent_factory.realtime.agent.load_memory", return_value=""),
        patch(
            "src.agent_factory.realtime.agent.RealtimeAgent",
            side_effect=lambda name, instructions, tools: MagicMock(name=name, instructions=instructions),
        ),
    ):
        return create_incoming_call_agent, instructions


class TestCreateIncomingCallAgent:
    def _call(self, caller_name=None) -> str:
        """Run create_incoming_call_agent and return the rendered instructions."""
        from src.agent_factory.realtime.agent import create_incoming_call_agent

        captured = {}

        def fake_realtime_agent(name, instructions, tools):
            captured["instructions"] = instructions
            return MagicMock()

        with (
            patch("src.agent_factory.realtime.agent.load_user_info", return_value={}),
            patch("src.agent_factory.realtime.agent.load_memory", return_value=""),
            patch("src.agent_factory.realtime.agent.RealtimeAgent", side_effect=fake_realtime_agent),
        ):
            create_incoming_call_agent(caller_name=caller_name)

        return captured["instructions"]

    def test_known_caller_name_in_instructions(self):
        instructions = self._call(caller_name="Jane Smith")
        assert "Jane Smith" in instructions

    def test_unknown_caller_falls_back_gracefully(self):
        instructions = self._call(caller_name=None)
        assert "Jane Smith" not in instructions
        # Should tell the agent it doesn't know who's calling
        assert "don't know" in instructions.lower() or "unknown" in instructions.lower()

    def test_known_caller_prompt_differs_from_unknown(self):
        known = self._call(caller_name="Bob")
        unknown = self._call(caller_name=None)
        assert known != unknown
