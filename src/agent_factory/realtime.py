from __future__ import annotations

from agents.realtime import RealtimeAgent

from ..prompts import get_incoming_prompt, get_outgoing_prompt
from ..tools.common import end_call, get_current_time, get_weather
from ..tools.user_info import get_user_info, load_user_info, render_template

_user_info = load_user_info()

_SHARED_TOOLS = [get_weather, get_current_time, get_user_info, end_call]


def create_incoming_call_agent() -> RealtimeAgent:
    """Create a RealtimeAgent configured for handling incoming calls.

    Incoming calls could be from anyone, so the agent uses a generic,
    receptive prompt that asks the caller to identify themselves and
    state the purpose of their call.
    """
    prompt = get_incoming_prompt()
    return RealtimeAgent(
        name=prompt.name,
        instructions=render_template(prompt.instructions, _user_info),
        tools=_SHARED_TOOLS,
    )


def create_outgoing_call_agent(prompt_key: str | None = None) -> RealtimeAgent:
    """Create a RealtimeAgent configured for making outgoing calls.

    Outgoing calls have a known purpose -- we know exactly who we are
    calling and why. The prompt_key selects which canned scenario to use;
    defaults to 'doctor_appointment' if not specified.
    """
    prompt = get_outgoing_prompt(prompt_key)
    return RealtimeAgent(
        name=prompt.name,
        instructions=render_template(prompt.instructions, _user_info),
        tools=_SHARED_TOOLS,
    )
