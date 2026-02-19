from __future__ import annotations

import uuid
from typing import Any

from agents import Agent, Runner, function_tool

from prompts import get_sms_prompt
from tools import get_user_info
from user_info import load_user_info, render_template


class SmsAgentManager:
    """Manages SMS conversations and the non-realtime chat agent.

    Dependencies (Twilio client, WebSocket manager, etc.) are injected at
    construction so this module has no circular imports with server.py.
    """

    def __init__(
        self,
        ws_manager: Any,
        twilio_client: Any,
        phone_from: str,
        domain: str,
    ):
        self._ws_manager = ws_manager
        self._twilio_client = twilio_client
        self._phone_from = phone_from
        self._domain = domain
        self._conversations: dict[str, list[dict[str, str]]] = {}
        self._agent = self._build_agent()

    def _build_agent(self) -> Agent:
        from prompts import list_outgoing_prompts

        ws_manager = self._ws_manager
        twilio_client = self._twilio_client
        phone_from = self._phone_from
        domain = self._domain

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

            outbound_twiml = (
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f"<Response><Connect>"
                f'<Stream url="wss://{domain}/media-stream/{call_id}" />'
                f"</Connect></Response>"
            )

            call = twilio_client.calls.create(
                from_=phone_from, to=to, twiml=outbound_twiml
            )
            return f"Call initiated (sid={call.sid}, status={call.status}). The user will receive a summary when the call completes."

        @function_tool
        def list_available_prompts() -> str:
            """List available outgoing-call prompt scenarios."""
            prompts = list_outgoing_prompts()
            lines = [f"- {p.key}: {p.description}" for p in prompts]
            return "\n".join(lines) if lines else "No prompts available."

        user_info = load_user_info()
        prompt = get_sms_prompt()
        instructions = render_template(prompt.instructions, user_info)

        return Agent(
            name=prompt.name,
            instructions=instructions,
            tools=[make_outgoing_call, list_available_prompts, get_user_info],
        )

    async def handle_message(self, from_number: str, body: str) -> str:
        """Process an incoming SMS and return the agent's reply."""
        history = self._conversations.setdefault(from_number, [])
        history.append({"role": "user", "content": body})

        result = await Runner.run(self._agent, input=history)
        reply = result.final_output or ""

        history.append({"role": "assistant", "content": reply})

        # Keep conversation history bounded to avoid unbounded growth
        max_turns = 50
        if len(history) > max_turns * 2:
            self._conversations[from_number] = history[-max_turns * 2 :]

        return reply
