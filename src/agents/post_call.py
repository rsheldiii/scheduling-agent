from __future__ import annotations

from agents import Agent, Runner

from ..prompts import get_post_call_prompt
from ..tools.google_calendar import create_calendar_event


def _build_agent() -> Agent:
    prompt = get_post_call_prompt()
    return Agent(
        name=prompt.name,
        instructions=prompt.instructions,
        tools=[create_calendar_event],
    )


async def run_post_call_agent(transcript: str) -> str:
    """Run the post-call agent with a call transcript and return its summary."""
    agent = _build_agent()
    print(f"Running post-call agent with transcript ({len(transcript)} chars)")
    result = await Runner.run(agent, input=transcript)
    summary = result.final_output or ""
    print(f"Post-call agent result: {summary}")
    return summary
