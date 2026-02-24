from __future__ import annotations

import uuid
from typing import Any

from agents import function_tool
from twilio.twiml.voice_response import Connect, VoiceResponse


def build_sms_tools(
    ws_manager: Any,
    twilio_client: Any,
    phone_from: str,
    domain: str,
) -> list:
    """Build the SMS-agent-specific tools that require Twilio/server context.

    Returns a list of function_tool-decorated callables ready to be passed
    to an Agent's tools parameter.
    """
    from ..agent_factory.realtime.agent import list_outgoing_prompts

    @function_tool
    def make_outgoing_call(to: str, prompt: str = "doctor_appointment") -> str:
        """Initiate an outgoing phone call via Twilio.

        Args:
            to: The phone number to call (E.164 format, e.g. "+15551234567").
            prompt: The prompt key to use (e.g. "doctor_appointment",
                    "restaurant_reservation"). Use list_available_prompts
                    to see options.
        """
        call_id = str(uuid.uuid4())
        ws_manager.register_pending_call(call_id, {"to": to, "prompt": prompt})

        response = VoiceResponse()
        connect = Connect()
        connect.stream(url=f"wss://{domain}/media-stream/{call_id}")
        response.append(connect)

        call = twilio_client.calls.create(
            from_=phone_from, to=to, twiml=str(response)
        )
        return f"Call initiated (sid={call.sid}, status={call.status}). The user will receive a summary when the call completes."

    @function_tool
    def list_available_prompts() -> str:
        """List available outgoing-call prompt scenarios."""
        prompts = list_outgoing_prompts()
        lines = [f"- {p.key}: {p.description}" for p in prompts]
        return "\n".join(lines) if lines else "No prompts available."

    return [make_outgoing_call, list_available_prompts]
