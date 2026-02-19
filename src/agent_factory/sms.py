from __future__ import annotations

from typing import Any

from agents import Agent, Runner

from ..prompts import get_sms_prompt
from ..tools.sms import build_sms_tools
from ..tools.user_info import get_user_info, load_user_info, render_template


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
        sms_tools = build_sms_tools(
            self._ws_manager,
            self._twilio_client,
            self._phone_from,
            self._domain,
        )

        user_info = load_user_info()
        prompt = get_sms_prompt()
        instructions = render_template(prompt.instructions, user_info)

        return Agent(
            name=prompt.name,
            instructions=instructions,
            tools=sms_tools + [get_user_info],
        )

    async def handle_message(self, from_number: str, body: str) -> str:
        """Process an incoming SMS and return the agent's reply."""
        history = self._conversations.setdefault(from_number, [])
        history.append({"role": "user", "content": body})

        result = await Runner.run(self._agent, input=history)
        reply = result.final_output or ""

        history.append({"role": "assistant", "content": reply})

        max_turns = 50
        if len(history) > max_turns * 2:
            self._conversations[from_number] = history[-max_turns * 2 :]

        return reply
