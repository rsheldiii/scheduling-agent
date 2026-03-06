"""Integration tests for FastAPI endpoints using httpx.AsyncClient.

External services (Twilio, OpenAI) are mocked; these tests exercise the
HTTP layer, request validation, and response formats.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _isolate_server(monkeypatch):
    """Ensure server module state is clean for each test.

    - Disables Twilio signature validation
    - Clears the cached config so env changes take effect
    - Prevents Chainlit mount (it requires its own config files)
    """
    monkeypatch.setenv("TWILIO_SIGNATURE_VALIDATION", "false")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test_token")
    monkeypatch.setenv("PHONE_NUMBER_FROM", "+15550001111")
    monkeypatch.setenv("DOMAIN", "test.example.com")


@pytest.fixture()
def app():
    """Import and return the FastAPI app after env is configured.

    We need a fresh module import each time because the server caches config
    at module level via lru_cache.
    """
    import importlib
    import src.server as server_mod

    # Clear the lru_cache so our monkeypatched env vars are picked up
    server_mod._get_config.cache_clear()

    # Reset the global sms_manager so it gets re-created per test
    server_mod.sms_manager = None

    return server_mod.app


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestPromptsEndpoint:
    @pytest.mark.asyncio
    async def test_prompts_returns_list(self, client):
        """The /prompts endpoint should return outgoing-call prompt metadata."""
        resp = await client.get("/prompts")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # Each entry should have these fields
        if data:
            keys_present = set(data[0].keys())
            assert {"key", "name", "description", "required_context"} <= keys_present


class TestIncomingCallEndpoint:
    @pytest.mark.asyncio
    async def test_incoming_call_get_returns_twiml(self, client):
        resp = await client.get("/incoming-call")
        assert resp.status_code == 200
        assert "text/xml" in resp.headers["content-type"]
        body = resp.text
        assert "<Response>" in body
        assert "Stream" in body
        assert "media-stream" in body


class TestOutgoingCallEndpoint:
    @pytest.mark.asyncio
    async def test_outgoing_call_missing_env_vars(self, client, monkeypatch):
        """If required config is missing, should return 500."""
        import src.server as server_mod
        monkeypatch.delenv("DOMAIN", raising=False)
        server_mod._get_config.cache_clear()

        resp = await client.post(
            "/outgoing-call",
            json={"to": "+14155551234"},
        )
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_outgoing_call_invalid_phone(self, client):
        resp = await client.post(
            "/outgoing-call",
            json={"to": "not-a-phone"},
        )
        assert resp.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_outgoing_call_success(self, client):
        mock_call = MagicMock(sid="CA_test_sid", status="queued")
        mock_calls = MagicMock()
        mock_calls.create = MagicMock(return_value=mock_call)
        mock_twilio = MagicMock()
        mock_twilio.calls = mock_calls

        with patch("src.server.TwilioClient", return_value=mock_twilio):
            resp = await client.post(
                "/outgoing-call",
                json={"to": "+14155551234", "prompt": "doctor_appointment"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["call_sid"] == "CA_test_sid"
        assert "call_id" in data


class TestIncomingSmsEndpoint:
    @pytest.mark.asyncio
    async def test_incoming_sms_returns_twiml(self, client):
        mock_manager = MagicMock()
        mock_manager.handle_message = AsyncMock(return_value="Got it!")

        with patch("src.server._get_sms_manager", return_value=mock_manager):
            resp = await client.post(
                "/incoming-sms",
                data={"From": "+14155551234", "Body": "Hello"},
            )

        assert resp.status_code == 200
        assert "text/xml" in resp.headers["content-type"]
        assert "Got it!" in resp.text
        assert "<Message>" in resp.text
