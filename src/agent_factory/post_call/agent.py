from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from agents import Agent, Runner

from ...persistence import update_request
from ...prompts import PromptLoader
from ...tools.common import get_current_time
from ...tools.google_calendar import create_calendar_event
from ...tools.memory import add_memory

logger = logging.getLogger(__name__)

_prompts = PromptLoader(Path(__file__).parent / "prompts")


def _build_agent() -> Agent:
    prompt = _prompts.get("default")
    now = datetime.now(timezone.utc).astimezone()
    instructions = prompt.instructions.replace(
        "{current_datetime}", now.strftime("%A, %B %d, %Y at %I:%M %p %Z")
    )
    return Agent(
        name=prompt.name,
        instructions=instructions,
        tools=[create_calendar_event, get_current_time, add_memory],
    )


async def run_post_call_agent(transcript: str, *, request_id: str | None = None) -> str:
    """Run the post-call agent with a call transcript and return its summary.

    If request_id is provided (MCP-initiated calls), the result is written
    back to the persistence layer so the query tool can retrieve it.
    """
    agent = _build_agent()
    logger.info("Running post-call agent with transcript (%d chars)", len(transcript))
    result = await Runner.run(agent, input=transcript)
    summary = result.final_output or ""
    logger.info("Post-call agent result: %s", summary)

    if request_id:
        try:
            update_request(request_id, status="completed", summary=summary)
            logger.info("Updated request %s with summary", request_id)
        except Exception as e:
            logger.error("Failed to update request %s: %s", request_id, e)

    return summary
