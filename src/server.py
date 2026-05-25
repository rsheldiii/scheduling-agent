import logging
import os
import re
import uuid
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, field_validator
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import Connect, VoiceResponse

from .agent_factory.post_call.agent import run_post_call_agent
from .agent_factory.realtime.agent import list_outgoing_prompts
from .auth import _validate_bearer_token
from .call_registry import manager
from .caller_id import _lookup_caller_name, _sanitize_caller_name
from .persistence import init_db
from .rate_limit import _call_rate_limit, _check_incoming_rate_limit, limiter, setup_limiter
from .secrets import get_secret
from .twilio_handler import TwilioHandler

logger = logging.getLogger(__name__)


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


app = FastAPI()
setup_limiter(app)


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

    if from_number:
        _check_incoming_rate_limit(from_number)

    if from_number and call_sid:
        cfg = _get_config()
        account_sid = cfg["twilio_account_sid"]
        auth_token = cfg["twilio_auth_token"]
        if account_sid and auth_token:
            caller_name = _sanitize_caller_name(await _lookup_caller_name(from_number, account_sid, auth_token))
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


@app.post("/outgoing-call", dependencies=[Depends(_validate_bearer_token)])
@limiter.limit(_call_rate_limit)
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
