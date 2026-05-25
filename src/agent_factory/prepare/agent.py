"""LLM-powered prepare agent: scenario selection, question generation, call brief."""
from __future__ import annotations

import logging

from agents import Agent, Runner
from pydantic import BaseModel

from ...prompts import PromptLoader
from ...tools.user_info import load_public_user_info

logger = logging.getLogger(__name__)


class PrepareResult(BaseModel):
    scenario: str
    questions: list[str]
    call_instructions: str


async def run_prepare_agent(user_prompt: str, prompt_loader: PromptLoader) -> PrepareResult:
    """Analyze the user's request and produce a scenario, question list, and call brief."""
    available = prompt_loader.list(category="outgoing")
    scenarios_text = "\n".join(
        f"- {p.key}: {p.description}"
        + (
            f"\n  Required context: {', '.join(p.required_context)}"
            if p.required_context
            else ""
        )
        for p in available
    )

    user_info = load_public_user_info()
    user_info_text = (
        "\n".join(f"  {k}: {v}" for k, v in user_info.items())
        or "  (none available)"
    )

    instructions = f"""\
You prepare outgoing phone calls. You have the caller's profile and their request.
Your job is to produce three things: scenario, questions, and call_instructions.

CALLER PROFILE (already known — never ask about these):
{user_info_text}

Available scenarios:
{scenarios_text}
- custom: Use for anything that doesn't fit the above scenarios.

─────────────────────────────────────────
STEP 1 — SIMULATE THE CALL

Before deciding what to ask, walk through the call as if you are both sides:

  Opening: How does the agent introduce themselves and state the purpose?
  Purpose: Can they state the goal clearly and completely without hedging?
  Recipient reaction: What does the other party say or ask in response?
    Be realistic and somewhat skeptical — assume they ask clarifying questions,
    not that they simply accept what they're told.
  Follow-ups: For each likely follow-up question, can the agent answer it
    from what is currently known? Be specific: if the recipient would need
    an address, a time, an order number, a name, or any concrete detail to
    act on the call — and that detail isn't already known — that is a gap.
  Close: Can the agent confirm any outcome before hanging up?

Any moment where the agent would have to say "I'll have to check and call you
back" is a GAP. Gaps become questions.

─────────────────────────────────────────
STEP 2 — CLASSIFY EACH GAP

For each gap, ask which lens applies:

  CALLER REPRESENTATION — Is the agent calling on behalf of a business or
    organization? If so, what is the business name, and what is the agent's
    role within it? (e.g. receptionist, service advisor, manager)

  SUBJECT SPECIFICITY — Is there a specific thing being discussed (a car,
    a patient record, an order, a reservation)? If so, what details identify
    it uniquely? The recipient will ask. If those details aren't known, ask.

  ACTIONABLE INFORMATION — What does the recipient need in order to actually
    follow through on what they're being told? For notification calls this
    might be a location, a time window, a reference number, or next steps.
    If the agent can't provide it, that's a gap.

  ANTICIPATED RECIPIENT QUESTIONS — What specific questions will the
    recipient likely ask that can't be answered from what's available?
    Each unanswerable question is a gap.

  RECIPIENT IDENTIFICATION — Is the agent calling a specific individual
    (not a business front desk)? If so, is the recipient's name known? A
    name is needed to greet them and confirm you have the right person.

ANONYMITY EXCEPTION: If the call is intentionally anonymous or the script
is fully self-contained (the agent has a complete script and the recipient's
identity doesn't matter), skip RECIPIENT IDENTIFICATION entirely.

─────────────────────────────────────────

NEVER ASK:
- What time to place the call — we always call immediately
- Anything in the caller profile above
- Anything the user already stated in their request

OUTPUT FIELDS:

1. scenario — best-matching scenario key ("custom" if nothing fits)

2. questions — one question per gap identified in STEP 2. May be empty if
   the simulation completes without gaps. No artificial limit.

3. call_instructions — a complete brief for the call agent. Include:
   - Role/context (who is the caller representing, if a business call)
   - Goal of the call
   - Key facts to state or confirm
   - How to handle likely recipient questions
   Do NOT include the phone number (agent is already connected).
   Do NOT restate the caller's name (the prompt template handles identity).
"""

    agent: Agent[PrepareResult] = Agent(
        name="PrepareAnalyzer",
        instructions=instructions,
        output_type=PrepareResult,
    )
    result = await Runner.run(agent, input=user_prompt)
    analysis: PrepareResult = result.final_output
    logger.info(
        "Prepared call — scenario=%s questions=%d call_instructions=%r",
        analysis.scenario,
        len(analysis.questions),
        analysis.call_instructions[:120],
    )
    return analysis
