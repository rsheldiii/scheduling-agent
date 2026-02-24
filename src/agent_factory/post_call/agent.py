from __future__ import annotations

import logging
from pathlib import Path

from agents import Agent, Runner

from ...prompts import PromptLoader
from ...tools.google_calendar import create_calendar_event

logger = logging.getLogger(__name__)

_prompts = PromptLoader(Path(__file__).parent / "prompts")


def _build_agent() -> Agent:
    prompt = _prompts.get("default")
    return Agent(
        name=prompt.name,
        instructions=prompt.instructions,
        tools=[create_calendar_event],
    )


async def run_post_call_agent(transcript: str) -> str:
    """Run the post-call agent with a call transcript and return its summary."""
    agent = _build_agent()
    logger.info("Running post-call agent with transcript (%d chars)", len(transcript))
    result = await Runner.run(agent, input=transcript)
    summary = result.final_output or ""
    logger.info("Post-call agent result: %s", summary)
    return summary
