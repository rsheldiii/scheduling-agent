"""MCP surface exposing the scheduling agent as three tools via FastMCP."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .agent_factory.prepare.agent import PrepareResult, run_prepare_agent
from .persistence import create_request, get_request, update_request
from .prompts import PromptLoader
from .secrets import get_secret

logger = logging.getLogger(__name__)

_OUTGOING_PROMPTS_DIR = (
    Path(__file__).parent / "agent_factory" / "realtime" / "prompts"
)
_prompt_loader = PromptLoader(_OUTGOING_PROMPTS_DIR)

_SERVER_DESCRIPTION = """\
You are connected to the Scheduling Agent MCP server. This server places real \
outgoing phone calls on behalf of the user — for scheduling appointments, \
making reservations, or any other phone-based task.

REQUIRED WORKFLOW — follow this exact sequence every time:

1. PREPARE: When the user wants to make a phone call or schedule something, \
call `prepare_call` with their exact request. The tool will identify the best \
scenario and return a `request_id` plus a list of questions you must ask the \
user before the call can proceed. If the questions list is empty, skip to step 3.

2. ASK: Present those questions to the user in a single conversational message. \
Do NOT invent extra questions — ask only what was returned.

3. PLACE: Call `place_call` with the `request_id`, the target phone number \
(`to` in E.164 format, e.g. "+15551234567"), and the user's answers as a JSON \
object. The call is placed immediately and the tool returns a `request_id` to \
track it.

4. INFORM: Tell the user the call is being placed.

5. WAIT: Call `get_call_outcome` with the `request_id`. It will block (with \
keepalive) until the call finishes — typically 1–5 minutes — then return the \
outcome. Relay the summary to the user.

RULES:
- Never call `prepare_call` more than once per user request.
- Never ask more questions than `prepare_call` returned.
- The call is placed immediately — never ask the user what time to call.
- If `place_call` returns an error, explain it and offer to retry.
- Do NOT call `get_call_outcome` with `poll=True` in the normal flow — that is \
for quick status checks only.
"""

def _build_transport_security() -> TransportSecuritySettings:
    domain = os.getenv("DOMAIN", "")
    if domain:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[domain, f"{domain}:*", "localhost:*", "127.0.0.1:*"],
            allowed_origins=[f"https://{domain}", "http://localhost:*", "http://127.0.0.1:*"],
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


mcp = FastMCP(
    "scheduling-agent",
    instructions=_SERVER_DESCRIPTION,
    transport_security=_build_transport_security(),
    streamable_http_path="/",
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def prepare_call(user_prompt: str) -> dict:
    """Prepare an outgoing phone call. Pass the user's request and get back a request_id, any questions to ask the user, and confirmation of the scenario. Call this once before anything else — never call it again for the same request."""
    if not user_prompt:
        raise ValueError("user_prompt is required")

    analysis = await run_prepare_agent(user_prompt, _prompt_loader)
    request_id = str(uuid.uuid4())

    create_request(
        request_id=request_id,
        scenario=analysis.scenario,
        user_prompt=user_prompt,
        call_instructions=analysis.call_instructions,
        questions=analysis.questions,
    )

    logger.info("Prepared request %s (scenario=%s)", request_id, analysis.scenario)
    return {
        "request_id": request_id,
        "scenario": analysis.scenario,
        "questions": analysis.questions,
        "next_step": (
            "Ask the user these questions, then call place_call with the request_id and their answers."
            if analysis.questions
            else "No questions needed — call place_call with the request_id and an empty answers object."
        ),
    }


_POLL_INTERVAL = int(os.getenv("QUERY_POLL_INTERVAL", "10"))


@mcp.tool()
async def place_call(
    request_id: str,
    to: str,
    answers: dict[str, str],
) -> dict:
    """Place the outgoing phone call. Requires the request_id from prepare_call, the phone number to call in E.164 format (e.g. +15551234567), and the user's answers to any questions (empty dict if there were none). Returns immediately — call get_call_outcome to wait for the result."""
    row = get_request(request_id)
    if row is None:
        raise ValueError(f"Unknown request_id: {request_id}")
    if row.status != "awaiting_info":
        raise ValueError(
            f"Request {request_id} is already in status '{row.status}' — cannot trigger again."
        )

    answer_lines = "\n".join(f"  {k}: {v}" for k, v in answers.items())
    additional_context = row.call_instructions
    if answer_lines:
        additional_context += f"\n\nAdditional details:\n{answer_lines}"

    agent_url = os.getenv("SCHEDULING_AGENT_URL", "http://localhost:2255")
    bearer_token = get_secret("api_bearer_token", "API_BEARER_TOKEN") or ""

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{agent_url}/outgoing-call",
            json={
                "to": to,
                "prompt": row.scenario,
                "additional_context": additional_context,
                "request_id": request_id,
            },
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
        resp.raise_for_status()
        call_data = resp.json()

    update_request(
        request_id,
        answers=answers,
        status="in_progress",
        call_sid=call_data.get("call_sid"),
    )

    logger.info(
        "Placed call for request %s (call_sid=%s)",
        request_id,
        call_data.get("call_sid"),
    )
    return {
        "status": "in_progress",
        "call_sid": call_data.get("call_sid"),
        "next_step": "Call is being placed. Call get_call_outcome with this request_id to wait for the result.",
    }


@mcp.tool()
async def get_call_outcome(request_id: str, poll: bool = False, ctx: Context = None) -> dict:  # type: ignore[assignment]
    """Wait for a call to complete and return its outcome. By default blocks with SSE keepalive until the call finishes — call this once after place_call and wait. If poll=True, returns the current status immediately without waiting (useful for quick status checks or recovery)."""
    row = get_request(request_id)
    if row is None:
        raise ValueError(f"Unknown request_id: {request_id}")

    if poll or row.status in ("completed", "failed"):
        return {"status": row.status, "scenario": row.scenario, "summary": row.summary}

    # Block until completed, sending progress notifications as keepalives.
    elapsed = 0
    while True:
        await asyncio.sleep(_POLL_INTERVAL)
        elapsed += _POLL_INTERVAL
        if ctx is not None:
            await ctx.report_progress(elapsed, 300)
        row = get_request(request_id)
        if row is None:
            raise ValueError(f"Request {request_id} disappeared during call")
        if row.status in ("completed", "failed"):
            logger.info("Call for request %s finished with status=%s", request_id, row.status)
            return {"status": row.status, "scenario": row.scenario, "summary": row.summary}
