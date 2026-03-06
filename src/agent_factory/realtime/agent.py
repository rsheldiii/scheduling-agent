from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.realtime import RealtimeAgent

from ...prompts import Prompt, PromptLoader
from ...tools.common import get_current_time, get_weather
from ...tools.user_info import get_user_info, load_user_info, render_template

_prompts = PromptLoader(Path(__file__).parent / "prompts")

_SHARED_TOOLS: list[Any] = [get_weather, get_current_time, get_user_info]


@dataclass(frozen=True)
class AgentWithVoice:
    """Bundles a RealtimeAgent with the voice preference from its prompt."""
    agent: RealtimeAgent
    voice: str | None


def create_incoming_call_agent() -> AgentWithVoice:
    """Create a RealtimeAgent configured for handling incoming calls.

    Incoming calls could be from anyone, so the agent uses a generic,
    receptive prompt that asks the caller to identify themselves and
    state the purpose of their call.
    """
    user_info = load_user_info()
    prompt = _prompts.get("default", category="incoming")
    agent = RealtimeAgent(
        name=prompt.name,
        instructions=render_template(prompt.instructions, user_info),
        tools=_SHARED_TOOLS,
    )
    return AgentWithVoice(agent=agent, voice=prompt.voice)


def create_outgoing_call_agent(
    prompt_key: str | None = None,
    additional_context: str | None = None,
) -> AgentWithVoice:
    """Create a RealtimeAgent configured for making outgoing calls.

    Outgoing calls have a known purpose -- we know exactly who we are
    calling and why. The prompt_key selects which scenario to use;
    defaults to 'doctor_appointment' if not specified. The caller can
    supply additional_context with instance-specific details (dates,
    preferences, etc.) that get injected into the prompt template.
    """
    user_info = load_user_info()
    prompt = _prompts.get(prompt_key or "doctor_appointment", category="outgoing")
    template_vars = {
        **user_info,
        "additional_context": additional_context or "No additional context provided.",
    }
    agent = RealtimeAgent(
        name=prompt.name,
        instructions=render_template(prompt.instructions, template_vars),
        tools=_SHARED_TOOLS,
    )
    return AgentWithVoice(agent=agent, voice=prompt.voice)


def list_outgoing_prompts() -> list[Prompt]:
    """Return all available outgoing-call prompts."""
    return _prompts.list(category="outgoing")
