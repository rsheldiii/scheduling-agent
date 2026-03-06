"""Tests for TwilioWebSocketManager and OutgoingCallRequest validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.server import OutgoingCallRequest, TwilioWebSocketManager


class TestOutgoingCallRequest:
    def test_valid_e164(self):
        req = OutgoingCallRequest(to="+14155551234")
        assert req.to == "+14155551234"

    def test_valid_with_all_fields(self):
        req = OutgoingCallRequest(
            to="+14155551234",
            prompt="doctor_appointment",
            additional_context="Tuesday morning",
            voice="alloy",
        )
        assert req.prompt == "doctor_appointment"
        assert req.additional_context == "Tuesday morning"
        assert req.voice == "alloy"

    def test_optional_fields_default_none(self):
        req = OutgoingCallRequest(to="+14155551234")
        assert req.prompt is None
        assert req.additional_context is None
        assert req.voice is None

    def test_invalid_phone_no_plus(self):
        with pytest.raises(ValidationError, match="E.164"):
            OutgoingCallRequest(to="14155551234")

    def test_invalid_phone_too_short(self):
        with pytest.raises(ValidationError, match="E.164"):
            OutgoingCallRequest(to="+0")

    def test_invalid_phone_letters(self):
        with pytest.raises(ValidationError, match="E.164"):
            OutgoingCallRequest(to="+1abc")

    def test_invalid_phone_leading_zero(self):
        with pytest.raises(ValidationError, match="E.164"):
            OutgoingCallRequest(to="+0123456789")


class TestTwilioWebSocketManager:
    def test_register_and_pop_pending(self):
        mgr = TwilioWebSocketManager()
        context = {"to": "+14155551234", "prompt": "test"}
        mgr.register_pending_call("call-1", context)
        assert "call-1" in mgr._pending_calls
        assert mgr._pending_calls["call-1"] == context

    def test_register_multiple(self):
        mgr = TwilioWebSocketManager()
        mgr.register_pending_call("a", {"to": "+1"})
        mgr.register_pending_call("b", {"to": "+2"})
        assert len(mgr._pending_calls) == 2

    def test_overwrite_pending(self):
        mgr = TwilioWebSocketManager()
        mgr.register_pending_call("a", {"to": "+1"})
        mgr.register_pending_call("a", {"to": "+2"})
        assert mgr._pending_calls["a"]["to"] == "+2"
