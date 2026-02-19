import logging
import os
import re
import uuid

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from twilio.rest import Client as TwilioClient

from .agent_factory.realtime import create_incoming_call_agent, create_outgoing_call_agent
from .agent_factory.post_call import run_post_call_agent
from .agent_factory.sms import SmsAgentManager
from .prompts import list_outgoing_prompts
from .sms import send_sms
from .twilio_handler import TwilioHandler
from .tools.user_info import load_user_info

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
PHONE_NUMBER_FROM = os.getenv("PHONE_NUMBER_FROM")
raw_domain = os.getenv("DOMAIN", "")
DOMAIN = re.sub(r"(^\w+:|^)\/\/|\/+$", "", raw_domain)


class OutgoingCallRequest(BaseModel):
    to: str
    prompt: str | None = None


class TwilioWebSocketManager:
    def __init__(self):
        self._pending_calls: dict[str, dict] = {}

    def register_pending_call(self, call_id: str, context: dict) -> None:
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
            logger.info("Creating outgoing call handler (call_id=%s, to=%s, prompt=%s)", call_id, context.get("to"), prompt_key)
            agent = create_outgoing_call_agent(prompt_key=prompt_key)
        else:
            logger.info("Creating incoming call handler")
            agent = create_incoming_call_agent()

        return TwilioHandler(websocket, agent)


manager = TwilioWebSocketManager()
app = FastAPI()

sms_manager: SmsAgentManager | None = None


def _get_sms_manager() -> SmsAgentManager:
    """Lazily initialize the SMS agent manager to avoid import-time side effects."""
    global sms_manager
    if sms_manager is None:
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        sms_manager = SmsAgentManager(
            ws_manager=manager,
            twilio_client=twilio_client,
            phone_from=PHONE_NUMBER_FROM or "",
            domain=DOMAIN,
        )
    return sms_manager


@app.get("/")
async def root():
    return {"message": "Twilio Media Stream Server is running!"}


@app.get("/prompts")
async def prompts():
    """List available outgoing-call prompts."""
    return [
        {"key": p.key, "name": p.name, "description": p.description}
        for p in list_outgoing_prompts()
    ]


@app.post("/incoming-call")
@app.get("/incoming-call")
async def incoming_call(request: Request):
    """Handle incoming Twilio phone calls."""
    host = request.headers.get("Host")

    twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Hello! You're now connected to an AI assistant. You can start talking!</Say>
    <Connect>
        <Stream url="wss://{host}/media-stream" />
    </Connect>
</Response>"""
    return PlainTextResponse(content=twiml_response, media_type="text/xml")


@app.post("/outgoing-call")
async def outgoing_call(request: OutgoingCallRequest):
    """Initiate an outgoing phone call via Twilio."""
    required_vars = {
        "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
        "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
        "PHONE_NUMBER_FROM": PHONE_NUMBER_FROM,
        "DOMAIN": DOMAIN,
    }
    missing = [name for name, val in required_vars.items() if not val]
    if missing:
        return {"error": f"Missing required environment variables: {', '.join(missing)}"}

    call_id = str(uuid.uuid4())
    manager.register_pending_call(call_id, {"to": request.to, "prompt": request.prompt})

    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    outbound_twiml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Connect>"
        f'<Stream url="wss://{DOMAIN}/media-stream/{call_id}" />'
        f"</Connect></Response>"
    )

    call = twilio_client.calls.create(
        from_=PHONE_NUMBER_FROM,
        to=request.to,
        twiml=outbound_twiml,
    )

    logger.info("Outgoing call initiated: call_id=%s, call_sid=%s, to=%s", call_id, call.sid, request.to)

    return {"call_id": call_id, "call_sid": call.sid, "status": call.status}


@app.post("/incoming-sms")
async def incoming_sms(request: Request):
    """Handle incoming Twilio SMS messages."""
    form = await request.form()
    from_number = form.get("From", "")
    body = form.get("Body", "")
    logger.info("SMS from %s: %s", from_number, body)

    mgr = _get_sms_manager()
    reply = await mgr.handle_message(str(from_number), str(body))

    twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{reply}</Message></Response>'
    return PlainTextResponse(content=twiml, media_type="text/xml")


async def _handle_media_stream(websocket: WebSocket, call_id: str | None = None):
    """Shared handler for Twilio Media Stream WebSocket connections."""
    handler: TwilioHandler | None = None
    try:
        handler = await manager.new_session(websocket, call_id=call_id)
        await handler.start()
        await handler.wait_until_done()
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        if handler is not None:
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
async def media_stream_endpoint(websocket: WebSocket):
    """WebSocket endpoint for incoming calls (no call_id)."""
    await _handle_media_stream(websocket)


@app.websocket("/media-stream/{call_id}")
async def media_stream_with_call_id_endpoint(websocket: WebSocket, call_id: str):
    """WebSocket endpoint for outgoing calls (with call_id in path)."""
    await _handle_media_stream(websocket, call_id=call_id)
