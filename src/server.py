import logging
import os
import re
import secrets
import uuid
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, field_validator
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import Connect, VoiceResponse

from .agent_factory.realtime.agent import create_incoming_call_agent, create_outgoing_call_agent, list_outgoing_prompts
from .agent_factory.post_call.agent import run_post_call_agent
from .agent_factory.sms.agent import SmsAgentManager
from .secrets import get_secret
from .sms import send_sms
from .twilio_handler import TwilioHandler
from .tools.user_info import load_user_info

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer()


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

    @field_validator("to")
    @classmethod
    def validate_phone_number(cls, v: str) -> str:
        if not re.fullmatch(r"\+[1-9]\d{1,14}", v):
            raise ValueError(
                "Phone number must be in E.164 format (e.g. +14155551234)"
            )
        return v


class TwilioWebSocketManager:
    def __init__(self) -> None:
        self._pending_calls: dict[str, dict[str, str | None]] = {}

    def register_pending_call(self, call_id: str, context: dict[str, str | None]) -> None:
        self._pending_calls[call_id] = context

    async def new_session(
        self, websocket: WebSocket, call_id: str | None = None
    ) -> TwilioHandler:
        """Create a new TwilioHandler session.

        If call_id is provided and matches a pending outgoing call, an outgoing
        agent is created. Otherwise, a generic incoming-call agent is used.
        """
        if call_id and call_id in self._pending_calls:
            context = self._pending_calls.pop(call_id)
            prompt_key = context.get("prompt")
            additional_context = context.get("additional_context")
            request_voice = context.get("voice")
            logger.info("Creating outgoing call handler (call_id=%s, to=%s, prompt=%s)", call_id, context.get("to"), prompt_key)
            result = create_outgoing_call_agent(prompt_key=prompt_key, additional_context=additional_context)
            voice = request_voice or result.voice
        else:
            logger.info("Creating incoming call handler")
            result = create_incoming_call_agent()
            voice = result.voice

        return TwilioHandler(websocket, result.agent, voice=voice)


manager = TwilioWebSocketManager()
app = FastAPI()

sms_manager: SmsAgentManager | None = None


def _get_sms_manager() -> SmsAgentManager:
    """Lazily initialize the SMS agent manager to avoid import-time side effects."""
    global sms_manager
    if sms_manager is None:
        cfg = _get_config()
        twilio_client = TwilioClient(cfg["twilio_account_sid"], cfg["twilio_auth_token"])
        sms_manager = SmsAgentManager(
            ws_manager=manager,
            twilio_client=twilio_client,
            phone_from=cfg["phone_number_from"] or "",
            domain=cfg["domain"] or "",
        )
    return sms_manager


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
@app.get("/incoming-call")
async def incoming_call(request: Request) -> PlainTextResponse:
    """Handle incoming Twilio phone calls."""
    host = request.headers.get("Host")

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
    connect.stream(url=f"wss://{host}/media-stream")
    response.append(connect)
    return PlainTextResponse(content=str(response), media_type="text/xml")


@app.post("/outgoing-call", dependencies=[Depends(_validate_bearer_token)])
async def outgoing_call(request: OutgoingCallRequest) -> dict[str, str | None]:
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
            "to": request.to,
            "prompt": request.prompt,
            "additional_context": request.additional_context,
            "voice": request.voice,
        }
    )

    twilio_client = TwilioClient(cfg["twilio_account_sid"], cfg["twilio_auth_token"])

    response = VoiceResponse()
    connect = Connect()
    connect.stream(url=f"wss://{cfg['domain']}/media-stream/{call_id}")
    response.append(connect)

    call = twilio_client.calls.create(
        from_=cfg["phone_number_from"],
        to=request.to,
        twiml=str(response),
    )

    logger.info("Outgoing call initiated: call_id=%s, call_sid=%s, to=%s", call_id, call.sid, request.to)

    return {"call_id": call_id, "call_sid": call.sid, "status": call.status}


@app.post("/incoming-sms", dependencies=[Depends(_validate_twilio_signature)])
async def incoming_sms(request: Request) -> PlainTextResponse:
    """Handle incoming Twilio SMS messages."""
    form = await request.form()
    from_number = form.get("From", "")
    body = form.get("Body", "")
    logger.info("SMS from %s: %s", from_number, body)

    mgr = _get_sms_manager()
    reply = await mgr.handle_message(str(from_number), str(body))

    response = MessagingResponse()
    response.message(reply)
    return PlainTextResponse(content=str(response), media_type="text/xml")


async def _handle_media_stream(websocket: WebSocket, call_id: str | None = None) -> None:
    """Shared handler for Twilio Media Stream WebSocket connections."""
    handler = await manager.new_session(websocket, call_id=call_id)
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
        if transcript:
            try:
                summary = await run_post_call_agent(transcript)
                user_phone = load_user_info().get("phone_number")
                if user_phone and summary:
                    send_sms(user_phone, f"Call summary:\n{summary}")
            except Exception as e:
                logger.error("Post-call agent error: %s", e)


@app.websocket("/media-stream")
async def media_stream_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for incoming calls (no call_id)."""
    await _handle_media_stream(websocket)


@app.websocket("/media-stream/{call_id}")
async def media_stream_with_call_id_endpoint(websocket: WebSocket, call_id: str) -> None:
    """WebSocket endpoint for outgoing calls (with call_id in path)."""
    await _handle_media_stream(websocket, call_id=call_id)


# Chainlit chat UI -- must be mounted after all other routes.
from chainlit.utils import mount_chainlit  # noqa: E402

mount_chainlit(app=app, target="src/chat_app.py", path="/")
