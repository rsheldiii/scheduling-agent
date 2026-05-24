import asyncio
import logging
import os
import re
import secrets
import time
import uuid
from functools import lru_cache

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import Response
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import Connect, VoiceResponse

from .agent_factory.realtime.agent import create_incoming_call_agent, create_outgoing_call_agent, list_outgoing_prompts
from .agent_factory.post_call.agent import run_post_call_agent
from .persistence import init_db
from .secrets import get_secret
from .twilio_handler import TwilioHandler

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer()

def _rate_limit_key(request: Request) -> str:
    """Use the bearer token as the rate-limit key so limits are per-token."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):]
    return get_remote_address(request)

_limiter = Limiter(key_func=_rate_limit_key)


@lru_cache
def _get_bearer_token() -> str:
    """Return the API bearer token, generating one if not configured."""
    token = get_secret("api_bearer_token", "API_BEARER_TOKEN")
    if token:
        return token
    token = secrets.token_urlsafe(32)
    logger.warning("API_BEARER_TOKEN not set — generated token: %s", token)
    return token


async def _validate_bearer_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> None:
    """FastAPI dependency that validates the Authorization: Bearer header."""
    if credentials.credentials != _get_bearer_token():
        raise HTTPException(status_code=401, detail="Invalid bearer token")


@lru_cache
def _get_config() -> dict[str, str | None]:
    """Read Twilio / app config from the environment lazily.

    Cached after the first call so env vars are only read once, but not at
    import time -- this keeps the module testable and order-independent.
    """
    raw_domain = os.getenv("DOMAIN", "")
    return {
        "twilio_account_sid": get_secret("twilio_account_sid", "TWILIO_ACCOUNT_SID"),
        "twilio_auth_token": get_secret("twilio_auth_token", "TWILIO_AUTH_TOKEN"),
        "phone_number_from": get_secret("twilio_phone_from", "PHONE_NUMBER_FROM"),
        "domain": re.sub(r"(^\w+:|^)\/\/|\/+$", "", raw_domain),
    }


async def _validate_twilio_signature(request: Request) -> None:
    """FastAPI dependency that validates the X-Twilio-Signature header.

    Skipped when TWILIO_SIGNATURE_VALIDATION is set to "false" (useful for
    local development behind ngrok).
    """
    if os.getenv("TWILIO_SIGNATURE_VALIDATION", "true").lower() == "false":
        return

    cfg = _get_config()
    auth_token = cfg["twilio_auth_token"]
    if not auth_token:
        raise HTTPException(status_code=500, detail="TWILIO_AUTH_TOKEN not configured")

    validator = RequestValidator(auth_token)
    signature = request.headers.get("X-Twilio-Signature", "")

    # Twilio sends POST form data; we need the form params for validation
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    url = str(request.url)

    if not validator.validate(url, params, signature):
        logger.warning("Invalid Twilio signature for %s", url)
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


class OutgoingCallRequest(BaseModel):
    to: str
    prompt: str | None = None
    additional_context: str | None = None
    voice: str | None = None
    request_id: str | None = None

    @field_validator("to")
    @classmethod
    def validate_phone_number(cls, v: str) -> str:
        if not re.fullmatch(r"\+[1-9]\d{1,14}", v):
            raise ValueError(
                "Phone number must be in E.164 format (e.g. +14155551234)"
            )
        return v

    @field_validator("voice")
    @classmethod
    def validate_voice(cls, v: str | None) -> str | None:
        if v is not None:
            from .voices import is_valid_voice
            if not is_valid_voice(v):
                raise ValueError(f"Unknown voice '{v}'. See GET /voices for valid options.")
        return v


_PENDING_CALL_TTL = 5 * 60  # seconds

_CALLER_NAME_SAFE_RE = re.compile(r"[^\w\s'\-.]", re.UNICODE)
_MAX_CALLER_NAME_LEN = 64


def _sanitize_caller_name(name: str) -> str:
    """Strip unusual characters and cap length before injecting into a prompt."""
    sanitized = _CALLER_NAME_SAFE_RE.sub("", name).strip()
    return sanitized[:_MAX_CALLER_NAME_LEN]


async def _lookup_caller_name(from_number: str, account_sid: str, auth_token: str) -> str | None:
    """Look up the caller's name via the Twilio Lookup v2 API.

    Returns None if the name is unavailable or the request fails.
    """
    url = f"https://lookups.twilio.com/v2/PhoneNumbers/{from_number}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                url,
                params={"Fields": "caller_name"},
                auth=(account_sid, auth_token),
            )
            if resp.status_code == 200:
                data = resp.json()
                caller_name_obj = data.get("caller_name") or {}
                return caller_name_obj.get("caller_name")  # str or None
            logger.warning("Caller ID lookup returned HTTP %s for %s", resp.status_code, from_number)
    except Exception:
        logger.warning("Caller ID lookup failed for %s", from_number, exc_info=True)
    return None


class TwilioWebSocketManager:
    def __init__(self) -> None:
        self._pending_calls: dict[str, dict[str, str | None]] = {}
        self._pending_call_times: dict[str, float] = {}
        self._completion_futures: dict[str, asyncio.Future[str]] = {}
        self._caller_info: dict[str, str | None] = {}
        self._caller_info_times: dict[str, float] = {}

    def register_pending_call(self, call_id: str, context: dict[str, str | None]) -> None:
        self._pending_calls[call_id] = context
        self._pending_call_times[call_id] = time.monotonic()

    def register_caller_info(self, call_sid: str, caller_name: str | None) -> None:
        self._caller_info[call_sid] = caller_name
        self._caller_info_times[call_sid] = time.monotonic()

    def pop_caller_info(self, call_sid: str) -> str | None:
        self._caller_info_times.pop(call_sid, None)
        return self._caller_info.pop(call_sid, None)

    def _sweep_stale_calls(self) -> None:
        now = time.monotonic()
        stale = [cid for cid, t in self._pending_call_times.items() if now - t > _PENDING_CALL_TTL]
        for cid in stale:
            self._pending_calls.pop(cid, None)
            self._pending_call_times.pop(cid, None)
            future = self._completion_futures.pop(cid, None)
            if future and not future.done():
                future.cancel()
            logger.warning("Swept stale pending call: %s", cid)

        stale_info = [sid for sid, t in self._caller_info_times.items() if now - t > _PENDING_CALL_TTL]
        for sid in stale_info:
            self._caller_info.pop(sid, None)
            self._caller_info_times.pop(sid, None)

    def register_completion_future(self, call_id: str) -> asyncio.Future[str]:
        """Create a Future that will be resolved when the call completes."""
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._completion_futures[call_id] = future
        return future

    def resolve_call(self, call_id: str, summary: str) -> None:
        """Resolve the completion Future for a finished call."""
        future = self._completion_futures.pop(call_id, None)
        if future and not future.done():
            future.set_result(summary)

    async def new_session(
        self, websocket: WebSocket, call_id: str | None = None, call_sid: str | None = None
    ) -> tuple[TwilioHandler, str | None]:
        """Create a new TwilioHandler session.

        Returns the handler and the MCP request_id (if this is an MCP-triggered call).
        """
        self._sweep_stale_calls()
        if call_id and call_id in self._pending_calls:
            context = self._pending_calls.pop(call_id)
            self._pending_call_times.pop(call_id, None)
            prompt_key = context.get("prompt")
            additional_context = context.get("additional_context")
            request_voice = context.get("voice")
            request_id = context.get("request_id")
            logger.info("Creating outgoing call handler (call_id=%s, to=%s, prompt=%s)", call_id, context.get("to"), prompt_key)
            result = create_outgoing_call_agent(prompt_key=prompt_key, additional_context=additional_context)
            voice = request_voice or result.voice
            return TwilioHandler(websocket, result.agent, voice=voice), request_id
        else:
            caller_name = self.pop_caller_info(call_sid) if call_sid else None
            logger.info("Creating incoming call handler (caller=%s)", caller_name or "unknown")
            result = create_incoming_call_agent(caller_name=caller_name)
            voice = result.voice
            request_id = None

        return TwilioHandler(websocket, result.agent, voice=voice), request_id


manager = TwilioWebSocketManager()
app = FastAPI()
app.state.limiter = _limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: Response("Rate limit exceeded", status_code=429),
)


@app.on_event("startup")
async def _startup() -> None:
    init_db()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/prompts", dependencies=[Depends(_validate_bearer_token)])
async def prompts() -> list[dict]:
    """List available outgoing-call prompts."""
    return [
        {"key": p.key, "name": p.name, "description": p.description, "required_context": p.required_context}
        for p in list_outgoing_prompts()
    ]


@app.post("/incoming-call", dependencies=[Depends(_validate_twilio_signature)])
async def incoming_call(request: Request) -> PlainTextResponse:
    """Handle incoming Twilio phone calls."""
    host = request.headers.get("Host")
    form = await request.form()
    from_number = str(form.get("From", ""))
    call_sid = str(form.get("CallSid", ""))

    if from_number and call_sid:
        cfg = _get_config()
        account_sid = cfg["twilio_account_sid"]
        auth_token = cfg["twilio_auth_token"]
        if account_sid and auth_token:
            caller_name = await _lookup_caller_name(from_number, account_sid, auth_token)
            if caller_name:
                caller_name = _sanitize_caller_name(caller_name)
            manager.register_caller_info(call_sid, caller_name)
            logger.info("Caller ID for %s: %s (call_sid=%s)", from_number, caller_name or "unknown", call_sid)

    response = VoiceResponse()
    response.say(
        "Please wait while we connect your call to the A. I. voice assistant.",
        voice="Google.en-US-Chirp3-HD-Aoede",
    )
    response.pause(length=1)
    response.say(
        "O.K. you can start talking!",
        voice="Google.en-US-Chirp3-HD-Aoede",
    )
    connect = Connect()
    stream_url = f"wss://{host}/media-stream"
    if call_sid:
        stream_url += f"?call_sid={call_sid}"
    connect.stream(url=stream_url)
    response.append(connect)
    return PlainTextResponse(content=str(response), media_type="text/xml")


def _call_rate_limit() -> str:
    limit = os.getenv("RATE_LIMIT_CALLS_PER_HOUR", "30")
    return f"{limit}/hour"


@app.post("/outgoing-call", dependencies=[Depends(_validate_bearer_token)])
@_limiter.limit(_call_rate_limit)
async def outgoing_call(request: Request, body: OutgoingCallRequest) -> dict[str, str | None]:
    """Initiate an outgoing phone call via Twilio."""
    cfg = _get_config()
    required_vars = {
        "TWILIO_ACCOUNT_SID": cfg["twilio_account_sid"],
        "TWILIO_AUTH_TOKEN": cfg["twilio_auth_token"],
        "PHONE_NUMBER_FROM": cfg["phone_number_from"],
        "DOMAIN": cfg["domain"],
    }
    missing = [name for name, val in required_vars.items() if not val]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing required environment variables: {', '.join(missing)}",
        )

    call_id = str(uuid.uuid4())
    manager.register_pending_call(
        call_id, {
            "to": body.to,
            "prompt": body.prompt,
            "additional_context": body.additional_context,
            "voice": body.voice,
            "request_id": body.request_id,
        }
    )

    twilio_client = TwilioClient(cfg["twilio_account_sid"], cfg["twilio_auth_token"])

    twiml = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{cfg['domain']}/media-stream/{call_id}")
    twiml.append(connect)

    try:
        call = twilio_client.calls.create(
            from_=cfg["phone_number_from"],
            to=body.to,
            twiml=str(twiml),
        )
    except Exception as e:
        manager._pending_calls.pop(call_id, None)
        logger.error("Twilio call creation failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Failed to initiate call: {e}") from e

    logger.info("Outgoing call initiated: call_id=%s, call_sid=%s, to=%s", call_id, call.sid, body.to)

    return {"call_id": call_id, "call_sid": call.sid, "status": call.status}



async def _handle_media_stream(
    websocket: WebSocket, call_id: str | None = None, call_sid: str | None = None
) -> None:
    """Shared handler for Twilio Media Stream WebSocket connections."""
    handler, request_id = await manager.new_session(websocket, call_id=call_id, call_sid=call_sid)
    try:
        async with handler:
            await handler.wait_until_done()
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        await handler.cleanup()
        transcript = handler.get_transcript()
        summary = ""
        if transcript:
            try:
                summary = await run_post_call_agent(transcript, request_id=request_id)
            except Exception as e:
                logger.error("Post-call agent error: %s", e)
        if call_id:
            manager.resolve_call(
                call_id, summary or "Call completed, no summary available."
            )


@app.websocket("/media-stream")
async def media_stream_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for incoming calls (no call_id)."""
    call_sid = websocket.query_params.get("call_sid")
    await _handle_media_stream(websocket, call_sid=call_sid)


@app.websocket("/media-stream/{call_id}")
async def media_stream_with_call_id_endpoint(websocket: WebSocket, call_id: str) -> None:
    """WebSocket endpoint for outgoing calls (with call_id in path)."""
    await _handle_media_stream(websocket, call_id=call_id)

