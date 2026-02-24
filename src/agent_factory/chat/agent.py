from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agents import Agent, Runner

from ...prompts import PromptLoader
from ...tools.sms import build_sms_tools
from ...tools.user_info import get_user_info, load_user_info, render_template

logger = logging.getLogger(__name__)

_prompts = PromptLoader(Path(__file__).parent / "prompts")


class ChatAgentManager:
    """Manages web-chat conversations with the scheduling agent.

    Unlike SmsAgentManager, session history is owned by the caller (Chainlit
    keeps it in ``cl.user_session``), so this class is stateless.
    """

    def __init__(
        self,
        ws_manager: Any,
        twilio_client: Any,
        phone_from: str,
        domain: str,
    ):
        self._agent = self._build_agent(ws_manager, twilio_client, phone_from, domain)

    def _build_agent(
        self,
        ws_manager: Any,
        twilio_client: Any,
        phone_from: str,
        domain: str,
    ) -> Agent:
        sms_tools = build_sms_tools(ws_manager, twilio_client, phone_from, domain)

        user_info = load_user_info()
        prompt = _prompts.get("default")
        instructions = render_template(prompt.instructions, user_info)

        return Agent(
            name=prompt.name,
            instructions=instructions,
            tools=sms_tools + [get_user_info],
        )

    async def handle_message(self, history: list[dict[str, str]]) -> str:
        """Run the agent against the full conversation history and return the reply."""
        result = await Runner.run(self._agent, input=history)  # type: ignore[arg-type]
        return result.final_output or ""
