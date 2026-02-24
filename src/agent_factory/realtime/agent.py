from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.realtime import RealtimeAgent

from ...prompts import Prompt, PromptLoader
from ...tools.common import end_call, get_current_time, get_weather
from ...tools.user_info import get_user_info, load_user_info, render_template

_prompts = PromptLoader(Path(__file__).parent / "prompts")

_SHARED_TOOLS: list[Any] = [get_weather, get_current_time, get_user_info, end_call]


def create_incoming_call_agent() -> RealtimeAgent:
    """Create a RealtimeAgent configured for handling incoming calls.

    Incoming calls could be from anyone, so the agent uses a generic,
    receptive prompt that asks the caller to identify themselves and
    state the purpose of their call.
    """
    user_info = load_user_info()
    prompt = _prompts.get("default", category="incoming")
    return RealtimeAgent(
        name=prompt.name,
        instructions=render_template(prompt.instructions, user_info),
        tools=_SHARED_TOOLS,
    )


def create_outgoing_call_agent(prompt_key: str | None = None) -> RealtimeAgent:
    """Create a RealtimeAgent configured for making outgoing calls.

    Outgoing calls have a known purpose -- we know exactly who we are
    calling and why. The prompt_key selects which canned scenario to use;
    defaults to 'doctor_appointment' if not specified.
    """
    user_info = load_user_info()
    prompt = _prompts.get(prompt_key or "doctor_appointment", category="outgoing")
    return RealtimeAgent(
        name=prompt.name,
        instructions=render_template(prompt.instructions, user_info),
        tools=_SHARED_TOOLS,
    )


def list_outgoing_prompts() -> list[Prompt]:
    """Return all available outgoing-call prompts."""
    return _prompts.list(category="outgoing")
