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
    def make_outgoing_call(
        to: str,
        prompt: str = "doctor_appointment",
        additional_context: str = "",
    ) -> str:
        """Initiate an outgoing phone call via Twilio.

        Args:
            to: The phone number to call (E.164 format, e.g. "+15551234567").
            prompt: The prompt key to use (e.g. "doctor_appointment",
                    "restaurant_reservation", "custom"). Use
                    list_available_prompts to see options.  Use "custom" for
                    scenarios that don't fit a canned template -- in that case
                    put the full scenario description in additional_context.
            additional_context: Extra details to include in the call prompt
                (e.g. preferred dates, specific requests gathered from the
                user).  For the "custom" prompt this should be the complete
                scenario description written from the voice agent's
                perspective.
        """
        call_id = str(uuid.uuid4())
        ws_manager.register_pending_call(
            call_id, {"to": to, "prompt": prompt, "additional_context": additional_context}
        )

        response = VoiceResponse()
        connect = Connect()
        connect.stream(url=f"wss://{domain}/media-stream/{call_id}")
        response.append(connect)

        call = twilio_client.calls.create(
            from_=phone_from, to=to, twiml=str(response)
        )
        return f"Call initiated (sid={call.sid}, status={call.status}). A summary will be sent to the user's phone via SMS when the call completes."

    @function_tool
    def list_available_prompts() -> str:
        """List available outgoing-call prompt scenarios, including the context you need to gather from the user before initiating each one."""
        prompts = list_outgoing_prompts()
        lines: list[str] = []
        for p in prompts:
            ctx = ", ".join(p.required_context) if p.required_context else "none"
            lines.append(f"- {p.key}: {p.description}\n  Required context: {ctx}")
        return "\n".join(lines) if lines else "No prompts available."

    return [make_outgoing_call, list_available_prompts]
