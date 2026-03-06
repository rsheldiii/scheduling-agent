"""Tests for src.sms — the send_sms helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import src.sms as sms_module


@pytest.fixture(autouse=True)
def _reset_sms_globals():
    """Clear the module-level cached client between tests."""
    sms_module._client = None
    sms_module._phone_from = None
    yield
    sms_module._client = None
    sms_module._phone_from = None


class TestSendSms:
    def test_send_with_injected_client(self):
        mock_msg = MagicMock(sid="SM_test_123")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg

        with patch("src.sms.get_secret", return_value="+15550001111"):
            sid = sms_module.send_sms("+15559999999", "Hello!", client=mock_client)

        assert sid == "SM_test_123"
        mock_client.messages.create.assert_called_once_with(
            from_="+15550001111", to="+15559999999", body="Hello!"
        )

    def test_client_is_cached(self):
        mock_msg = MagicMock(sid="SM_1")
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg

        with patch("src.sms.get_secret", return_value="+15550001111"):
            sms_module.send_sms("+15551111111", "A", client=mock_client)
            sms_module.send_sms("+15552222222", "B")  # should reuse cached client

        assert mock_client.messages.create.call_count == 2

    def test_auto_creates_client_from_env(self):
        mock_msg = MagicMock(sid="SM_auto")
        mock_twilio_client = MagicMock()
        mock_twilio_client.messages.create.return_value = mock_msg

        secrets = {
            ("twilio_account_sid", "TWILIO_ACCOUNT_SID"): "AC_test",
            ("twilio_auth_token", "TWILIO_AUTH_TOKEN"): "token_test",
            ("twilio_phone_from", "PHONE_NUMBER_FROM"): "+15550001111",
        }

        def fake_secret(name, env_var=None, default=None):
            return secrets.get((name, env_var), default)

        with patch("src.sms.get_secret", side_effect=fake_secret), \
             patch("src.sms.TwilioClient", return_value=mock_twilio_client):
            sid = sms_module.send_sms("+15559999999", "Test")

        assert sid == "SM_auto"

    def test_raises_when_no_credentials(self):
        with patch("src.sms.get_secret", return_value=None):
            with pytest.raises(RuntimeError, match="Twilio credentials"):
                sms_module.send_sms("+15559999999", "Test")

    def test_raises_when_no_phone_from(self):
        mock_client = MagicMock()

        with patch("src.sms.get_secret", return_value=None):
            with pytest.raises(RuntimeError, match="PHONE_NUMBER_FROM"):
                sms_module.send_sms("+15559999999", "Test", client=mock_client)
