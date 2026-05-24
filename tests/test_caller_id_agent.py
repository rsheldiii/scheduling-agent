"""Tests for the realtime agent factory — incoming and outgoing call agents."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_agent_patches(public: dict | None = None, sensitive: dict | None = None):
    return (
        patch("src.agent_factory.realtime.agent.load_public_user_info", return_value=public or {}),
        patch("src.agent_factory.realtime.agent.load_sensitive_user_info", return_value=sensitive or {}),
        patch("src.agent_factory.realtime.agent.load_memory", return_value=""),
    )


class TestCreateIncomingCallAgent:
    def _call(self, caller_name=None, public: dict | None = None) -> str:
        """Run create_incoming_call_agent and return the rendered instructions."""
        from src.agent_factory.realtime.agent import create_incoming_call_agent

        captured = {}

        def fake_realtime_agent(name, instructions, tools):
            captured["instructions"] = instructions
            return MagicMock()

        pub_patch, sens_patch, mem_patch = _make_agent_patches(public=public)
        with pub_patch, sens_patch, mem_patch, \
             patch("src.agent_factory.realtime.agent.RealtimeAgent", side_effect=fake_realtime_agent):
            create_incoming_call_agent(caller_name=caller_name)

        return captured["instructions"]

    def test_known_caller_name_in_instructions(self):
        instructions = self._call(caller_name="Jane Smith")
        assert "Jane Smith" in instructions

    def test_unknown_caller_falls_back_gracefully(self):
        instructions = self._call(caller_name=None)
        assert "Jane Smith" not in instructions
        assert "don't know" in instructions.lower() or "unknown" in instructions.lower()

    def test_known_caller_prompt_differs_from_unknown(self):
        known = self._call(caller_name="Bob")
        unknown = self._call(caller_name=None)
        assert known != unknown

    def test_public_user_info_is_loaded(self):
        """Verify load_public_user_info is called when building incoming agents."""
        from src.agent_factory.realtime.agent import create_incoming_call_agent

        pub_patch, sens_patch, mem_patch = _make_agent_patches(public={"name": "Alice"})
        with pub_patch as mock_pub, sens_patch, mem_patch, \
             patch("src.agent_factory.realtime.agent.RealtimeAgent", return_value=MagicMock()):
            create_incoming_call_agent()
        mock_pub.assert_called_once()

    def test_sensitive_fields_not_in_instructions(self):
        """Sensitive data must never appear in incoming call instructions."""
        from src.agent_factory.realtime.agent import create_incoming_call_agent

        captured = {}

        def fake_realtime_agent(name, instructions, tools):
            captured["instructions"] = instructions
            return MagicMock()

        pub_patch, _, mem_patch = _make_agent_patches(public={"name": "Alice"})
        # Sensitive info is loaded but should not be passed to template_vars.
        sensitive_patch = patch(
            "src.agent_factory.realtime.agent.load_sensitive_user_info",
            return_value={"ssn_last_four": "9999"},
        )
        with pub_patch, sensitive_patch, mem_patch, \
             patch("src.agent_factory.realtime.agent.RealtimeAgent", side_effect=fake_realtime_agent):
            create_incoming_call_agent(caller_name=None)

        assert "9999" not in captured["instructions"]


class TestCreateOutgoingCallAgent:
    def _call(
        self,
        prompt_key: str = "doctor_appointment",
        public: dict | None = None,
        sensitive: dict | None = None,
    ) -> str:
        from src.agent_factory.realtime.agent import create_outgoing_call_agent

        captured = {}

        def fake_realtime_agent(name, instructions, tools):
            captured["instructions"] = instructions
            return MagicMock()

        pub_patch, sens_patch, mem_patch = _make_agent_patches(public=public, sensitive=sensitive)
        with pub_patch, sens_patch, mem_patch, \
             patch("src.agent_factory.realtime.agent.RealtimeAgent", side_effect=fake_realtime_agent):
            create_outgoing_call_agent(prompt_key=prompt_key)

        return captured["instructions"]

    def test_public_fields_always_injected(self):
        instructions = self._call(
            prompt_key="doctor_appointment",
            public={"name": "Alice", "age": "32"},
        )
        assert "Alice" in instructions
        assert "32" in instructions

    def test_declared_sensitive_field_injected(self):
        """doctor_appointment declares ssn_last_four — it must appear."""
        instructions = self._call(
            prompt_key="doctor_appointment",
            sensitive={"ssn_last_four": "1234"},
        )
        assert "1234" in instructions

    def test_undeclared_sensitive_field_excluded(self):
        """A sensitive field not listed in the prompt's sensitive_fields must be absent."""
        instructions = self._call(
            prompt_key="restaurant_reservation",
            sensitive={"ssn_last_four": "9999", "cc_last_four": "8888"},
        )
        assert "9999" not in instructions
        assert "8888" not in instructions

    def test_restaurant_gets_no_sensitive_fields(self):
        """restaurant_reservation has no sensitive_fields declared."""
        instructions = self._call(
            prompt_key="restaurant_reservation",
            public={"name": "Bob"},
            sensitive={"ssn_last_four": "5555"},
        )
        assert "Bob" in instructions
        assert "5555" not in instructions
