from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from agents import Agent, Runner

from ...prompts import PromptLoader
from ...tools.sms import build_sms_tools
from ...tools.user_info import get_user_info, load_user_info, render_template

logger = logging.getLogger(__name__)

_prompts = PromptLoader(Path(__file__).parent / "prompts")

_DEFAULT_TTL_SECONDS = 3600  # 1 hour
_MAX_TURNS = 50


class SmsAgentManager:
    """Manages SMS conversations and the non-realtime chat agent.

    Dependencies (Twilio client, WebSocket manager, etc.) are injected at
    construction so this module has no circular imports with server.py.

    Conversations are evicted after *conversation_ttl* seconds of inactivity
    to prevent unbounded memory growth over long-running deployments.
    """

    def __init__(
        self,
        ws_manager: Any,
        twilio_client: Any,
        phone_from: str,
        domain: str,
        conversation_ttl: float = _DEFAULT_TTL_SECONDS,
    ):
        self._ws_manager = ws_manager
        self._twilio_client = twilio_client
        self._phone_from = phone_from
        self._domain = domain
        self._conversation_ttl = conversation_ttl

        # phone_number -> (last_activity_timestamp, message_history)
        self._conversations: dict[str, tuple[float, list[dict[str, str]]]] = {}
        self._agent = self._build_agent()

    def _build_agent(self) -> Agent:
        sms_tools = build_sms_tools(
            self._ws_manager,
            self._twilio_client,
            self._phone_from,
            self._domain,
        )

        user_info = load_user_info()
        prompt = _prompts.get("default")
        instructions = render_template(prompt.instructions, user_info)

        return Agent(
            name=prompt.name,
            instructions=instructions,
            tools=sms_tools + [get_user_info],
        )

    def _evict_stale(self) -> None:
        """Remove conversations that have been idle longer than the TTL."""
        now = time.monotonic()
        stale = [
            number
            for number, (last_active, _) in self._conversations.items()
            if now - last_active > self._conversation_ttl
        ]
        for number in stale:
            del self._conversations[number]
        if stale:
            logger.info("Evicted %d stale SMS conversation(s)", len(stale))

    async def handle_message(self, from_number: str, body: str) -> str:
        """Process an incoming SMS and return the agent's reply."""
        self._evict_stale()

        now = time.monotonic()
        if from_number in self._conversations:
            _, history = self._conversations[from_number]
        else:
            history = []

        history.append({"role": "user", "content": body})

        result = await Runner.run(self._agent, input=history)  # type: ignore[arg-type]
        reply = result.final_output or ""

        history.append({"role": "assistant", "content": reply})

        if len(history) > _MAX_TURNS * 2:
            history = history[-_MAX_TURNS * 2 :]

        self._conversations[from_number] = (now, history)

        return reply
