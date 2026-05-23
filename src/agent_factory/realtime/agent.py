from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.realtime import RealtimeAgent

from ...prompts import Prompt, PromptLoader
from ...tools.common import get_current_time, get_weather
from ...tools.google_calendar import get_calendar_events
from ...tools.memory import get_memory, load_memory
from ...tools.user_info import (
    load_public_user_info,
    load_sensitive_user_info,
    render_template,
)

_prompts = PromptLoader(Path(__file__).parent / "prompts")

_SHARED_TOOLS: list[Any] = [get_weather, get_current_time, get_calendar_events, get_memory]

_PHONE_PERSONA = """\
You are on a real phone call with a real person. You must sound exactly like a \
normal human caller -- natural, conversational, and warm.

RULES:
- Use natural filler and reactions: "oh great", "gotcha", "perfect", "hmm", \
"alright", "sounds good", etc.
- Speak in short, casual sentences. Real people don't monologue on the phone.
- This is a live two-way call, not a voicemail. After you deliver your message \
or ask your question, stop talking and wait for the other person to respond. \
Do not linger with closing questions before they've had a chance to react.
- Let the conversation end naturally: when the other person signals they're \
done (acknowledges, thanks you, says bye), say a brief goodbye and hang up.
- GOODBYE RULE: Say a natural verbal goodbye before calling end_call. \
Never call end_call without first saying goodbye out loud in that same turn.
- Match the energy of the person you're speaking with. If they're casual, be \
casual. If they're formal, be polite but still human.
- It's okay to pause, react, or say "uh" / "um" occasionally -- that's normal.
- Don't over-explain or narrate what you're doing. Just have the conversation.
- SCHEDULING RULE: Before agreeing to or confirming any specific date or time, \
call get_calendar_events to check availability. Use your judgment: a vague \
all-day note like "buy flowers" is not a real conflict; a timed appointment or \
clear commitment is. If a proposed time conflicts with something real, offer an \
alternative. If the calendar is clear, confirm confidently.

"""


@dataclass(frozen=True)
class AgentWithVoice:
    """Bundles a RealtimeAgent with the voice preference from its prompt."""
    agent: RealtimeAgent
    voice: str | None


def _memory_block() -> str:
    memory = load_memory()
    if not memory:
        return ""
    return f"\nPAST CALL MEMORY:\n{memory}\n"


def create_incoming_call_agent(caller_name: str | None = None) -> AgentWithVoice:
    """Create a RealtimeAgent for incoming calls.

    Only public user info is injected — no sensitive fields are available.
    """
    public_info = load_public_user_info()
    prompt = _prompts.get("default", category="incoming")
    if caller_name:
        caller_context = (
            f"The caller has been identified as {caller_name}. "
            "You may greet them by name."
        )
    else:
        caller_context = (
            "You don't know who is calling. "
            "Greet them warmly and find out who they are and what they need."
        )
    template_vars = {**public_info, "caller_context": caller_context}
    instructions = _PHONE_PERSONA + _memory_block() + render_template(prompt.instructions, template_vars)
    agent = RealtimeAgent(
        name=prompt.name,
        instructions=instructions,
        tools=_SHARED_TOOLS,
    )
    return AgentWithVoice(agent=agent, voice=prompt.voice)


def create_outgoing_call_agent(
    prompt_key: str | None = None,
    additional_context: str | None = None,
) -> AgentWithVoice:
    """Create a RealtimeAgent for outgoing calls.

    Public user info is always injected. Sensitive fields are only injected
    when explicitly declared via ``sensitive_fields`` in the scenario's prompt YAML.
    """
    public_info = load_public_user_info()
    sensitive_info = load_sensitive_user_info()
    prompt = _prompts.get(prompt_key or "doctor_appointment", category="outgoing")
    scenario_sensitive = {k: v for k, v in sensitive_info.items() if k in prompt.sensitive_fields}
    template_vars = {
        **public_info,
        **scenario_sensitive,
        "additional_context": additional_context or "No additional context provided.",
    }
    instructions = _PHONE_PERSONA + _memory_block() + render_template(prompt.instructions, template_vars)
    agent = RealtimeAgent(
        name=prompt.name,
        instructions=instructions,
        tools=_SHARED_TOOLS,
    )
    return AgentWithVoice(agent=agent, voice=prompt.voice)


def list_outgoing_prompts() -> list[Prompt]:
    """Return all available outgoing-call prompts."""
    return _prompts.list(category="outgoing")
