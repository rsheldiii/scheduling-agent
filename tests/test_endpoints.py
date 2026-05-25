"""Integration tests for FastAPI endpoints using httpx.AsyncClient.

External services (Twilio, OpenAI) are mocked; these tests exercise the
HTTP layer, request validation, and response formats.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


TEST_BEARER_TOKEN = "test-bearer-token"


@pytest.fixture(autouse=True)
def _isolate_server(monkeypatch):
    """Ensure server module state is clean for each test.

    - Disables Twilio signature validation
    - Sets a known bearer token
    - Clears lru_cache'd config so env changes take effect
    - Resets per-caller rate limit state
    """
    monkeypatch.setenv("TWILIO_SIGNATURE_VALIDATION", "false")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test_token")
    monkeypatch.setenv("PHONE_NUMBER_FROM", "+15550001111")
    monkeypatch.setenv("DOMAIN", "test.example.com")
    monkeypatch.setenv("API_BEARER_TOKEN", TEST_BEARER_TOKEN)

    import src.auth as auth_mod
    import src.rate_limit as rate_limit_mod
    auth_mod._get_bearer_token.cache_clear()
    rate_limit_mod._incoming_call_timestamps.clear()


@pytest.fixture()
def app():
    """Import and return the FastAPI app after env is configured."""
    import src.server as server_mod
    server_mod._get_config.cache_clear()
    return server_mod.app


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {TEST_BEARER_TOKEN}"}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as c:
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


class TestIncomingCallEndpoint:
    @pytest.mark.asyncio
    async def test_incoming_call_returns_twiml(self, client):
        """Should return valid TwiML with a media stream URL."""
        with patch("src.server._lookup_caller_name", new=AsyncMock(return_value=None)):
            resp = await client.post(
                "/incoming-call",
                content="From=%2B14155551234&CallSid=CAtest123",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        assert resp.status_code == 200
        assert "text/xml" in resp.headers["content-type"]
        body = resp.text
        assert "<Stream" in body
        assert "/media-stream" in body

    @pytest.mark.asyncio
    async def test_incoming_call_embeds_call_sid_in_stream_url(self, client):
        """CallSid should appear as a query param in the stream URL."""
        with patch("src.server._lookup_caller_name", new=AsyncMock(return_value=None)):
            resp = await client.post(
                "/incoming-call",
                content="From=%2B14155551234&CallSid=CAabc999",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        assert "call_sid=CAabc999" in resp.text

    @pytest.mark.asyncio
    async def test_incoming_call_registers_caller_name(self, client):
        """Looked-up caller name should be stored in the manager."""
        import src.server as server_mod

        with patch("src.server._lookup_caller_name", new=AsyncMock(return_value="Jane Smith")):
            await client.post(
                "/incoming-call",
                content="From=%2B14155551234&CallSid=CAnamed123",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert server_mod.manager._caller_info.get("CAnamed123") == "Jane Smith"

    @pytest.mark.asyncio
    async def test_incoming_call_unknown_caller_stores_none(self, client):
        """None caller name (lookup returned nothing) should still be registered."""
        import src.server as server_mod

        with patch("src.server._lookup_caller_name", new=AsyncMock(return_value=None)):
            await client.post(
                "/incoming-call",
                content="From=%2B14155551234&CallSid=CAunknown",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        assert "CAunknown" in server_mod.manager._caller_info
        assert server_mod.manager._caller_info["CAunknown"] is None


class TestIncomingCallRateLimit:
    @pytest.mark.asyncio
    async def test_first_call_succeeds(self, client, monkeypatch):
        """A single call from a number should always get through."""
        monkeypatch.setenv("RATE_LIMIT_INCOMING_CALLS_PER_HOUR", "3")
        with patch("src.server._lookup_caller_name", new=AsyncMock(return_value=None)):
            resp = await client.post(
                "/incoming-call",
                content="From=%2B14155550001&CallSid=CArl001",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_exceeding_limit_returns_429(self, client, monkeypatch):
        """After the limit is hit, the next call from the same number should get 429."""
        monkeypatch.setenv("RATE_LIMIT_INCOMING_CALLS_PER_HOUR", "2")
        with patch("src.server._lookup_caller_name", new=AsyncMock(return_value=None)):
            for i in range(2):
                resp = await client.post(
                    "/incoming-call",
                    content=f"From=%2B14155550002&CallSid=CArl00{i}",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                assert resp.status_code == 200

            resp = await client.post(
                "/incoming-call",
                content="From=%2B14155550002&CallSid=CArl009",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        assert resp.status_code == 429

    @pytest.mark.asyncio
    async def test_different_callers_have_independent_limits(self, client, monkeypatch):
        """Caller A hitting the limit must not affect Caller B."""
        monkeypatch.setenv("RATE_LIMIT_INCOMING_CALLS_PER_HOUR", "1")
        with patch("src.server._lookup_caller_name", new=AsyncMock(return_value=None)):
            # Exhaust caller A's limit
            await client.post(
                "/incoming-call",
                content="From=%2B14155550010&CallSid=CArlA1",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            # Caller A is now rate-limited
            resp_a = await client.post(
                "/incoming-call",
                content="From=%2B14155550010&CallSid=CArlA2",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert resp_a.status_code == 429

            # Caller B should still get through
            resp_b = await client.post(
                "/incoming-call",
                content="From=%2B14155550011&CallSid=CArlB1",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert resp_b.status_code == 200

    def test_check_rate_limit_function_directly(self, monkeypatch):
        """Unit test for _check_incoming_rate_limit."""
        from fastapi import HTTPException
        import src.rate_limit as rate_limit_mod
        from src.rate_limit import _check_incoming_rate_limit

        monkeypatch.setenv("RATE_LIMIT_INCOMING_CALLS_PER_HOUR", "2")
        rate_limit_mod._incoming_call_timestamps.clear()

        _check_incoming_rate_limit("+15550099")
        _check_incoming_rate_limit("+15550099")
        with pytest.raises(HTTPException) as exc_info:
            _check_incoming_rate_limit("+15550099")
        assert exc_info.value.status_code == 429


class TestSanitizeCallerName:
    def test_normal_name_unchanged(self):
        from src.server import _sanitize_caller_name
        assert _sanitize_caller_name("Jane Smith") == "Jane Smith"

    def test_name_with_allowed_punctuation(self):
        from src.server import _sanitize_caller_name
        assert _sanitize_caller_name("O'Brien-Smith, Jr.") == "O'Brien-Smith Jr."

    def test_strips_disallowed_characters(self):
        from src.server import _sanitize_caller_name
        result = _sanitize_caller_name("Alice\x00{inject}")
        assert "\x00" not in result
        assert "{" not in result
        assert "}" not in result

    def test_caps_at_max_length(self):
        from src.server import _sanitize_caller_name
        long_name = "A" * 200
        assert len(_sanitize_caller_name(long_name)) == 64

    def test_strips_leading_trailing_whitespace(self):
        from src.server import _sanitize_caller_name
        assert _sanitize_caller_name("  Bob  ") == "Bob"

    def test_none_input_returns_none(self):
        from src.server import _sanitize_caller_name
        assert _sanitize_caller_name(None) is None

    def test_empty_string_returns_none(self):
        from src.server import _sanitize_caller_name
        assert _sanitize_caller_name("") is None

    def test_all_stripped_chars_returns_none(self):
        from src.server import _sanitize_caller_name
        assert _sanitize_caller_name("{{{") is None

    @pytest.mark.asyncio
    async def test_incoming_call_sanitizes_caller_name(self, client):
        """Stored caller name must be the sanitized version."""
        import src.server as server_mod

        with patch("src.server._lookup_caller_name", new=AsyncMock(return_value="Evil\x00{Name}")):
            await client.post(
                "/incoming-call",
                content="From=%2B14155551234&CallSid=CAsanitize",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        stored = server_mod.manager._caller_info.get("CAsanitize")
        assert stored is not None
        assert "\x00" not in stored
        assert "{" not in stored


class TestLookupCallerName:
    @pytest.mark.asyncio
    async def test_returns_name_on_success(self):
        """Should extract caller name from a successful Twilio Lookup response."""
        import httpx

        from src.server import _lookup_caller_name

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "phone_number": "+14155551234",
            "caller_name": {"caller_name": "Alice Example", "caller_type": "CONSUMER", "error_code": None},
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await _lookup_caller_name("+14155551234", "ACtest", "token")

        assert result == "Alice Example"

    @pytest.mark.asyncio
    async def test_returns_none_when_name_unavailable(self):
        """Should return None when the lookup succeeds but name field is null."""
        from src.server import _lookup_caller_name

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "phone_number": "+14155551234",
            "caller_name": {"caller_name": None, "caller_type": None, "error_code": None},
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await _lookup_caller_name("+14155551234", "ACtest", "token")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_http_error(self):
        """Should return None gracefully when Twilio returns a non-200 status."""
        from src.server import _lookup_caller_name

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await _lookup_caller_name("+14155551234", "ACtest", "token")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self):
        """Should swallow network exceptions and return None."""
        import httpx

        from src.server import _lookup_caller_name

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_client_cls.return_value = mock_client

            result = await _lookup_caller_name("+14155551234", "ACtest", "token")

        assert result is None
