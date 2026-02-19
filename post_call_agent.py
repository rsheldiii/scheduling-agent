from __future__ import annotations

from agents import Agent, Runner

from google_calendar import create_calendar_event

_POST_CALL_INSTRUCTIONS = """\
You are a post-call processing agent. You receive the transcript of a phone call
that was made by a scheduling assistant on behalf of a user.

Your job:
1. Determine whether an appointment, reservation, or event was successfully
   scheduled during the call.
2. If yes, extract the relevant details: title/summary, date, start time,
   end time, location, and any notes.
3. Use the create_calendar_event tool to add it to the user's calendar.
   Provide ISO 8601 datetimes including timezone offset (assume US Eastern
   if not specified, i.e. -05:00 / -04:00 for EDT).
4. If no appointment was clearly scheduled (e.g. the call ended inconclusively,
   or the user was told they'd receive a callback), do NOT create a calendar
   event — instead, return a brief summary of the call outcome.

Always return a short plain-text summary of what you did (created an event,
or why you didn't).
"""

_agent = Agent(
    name="Post-Call Processor",
    instructions=_POST_CALL_INSTRUCTIONS,
    tools=[create_calendar_event],
)


async def run_post_call_agent(transcript: str) -> str:
    """Run the post-call agent with a call transcript and return its summary."""
    print(f"Running post-call agent with transcript ({len(transcript)} chars)")
    result = await Runner.run(_agent, input=transcript)
    summary = result.final_output or ""
    print(f"Post-call agent result: {summary}")
    return summary
