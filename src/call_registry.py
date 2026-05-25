"""Call-state registry: pending outgoing calls, completion futures, and caller info."""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_PENDING_CALL_TTL = 5 * 60  # seconds


class TwilioWebSocketManager:
    def __init__(self) -> None:
        self._pending_calls: dict[str, dict[str, str | None]] = {}
        self._pending_call_times: dict[str, float] = {}
        self._completion_futures: dict[str, asyncio.Future[str]] = {}
        self._caller_info: dict[str, str | None] = {}
        self._caller_info_times: dict[str, float] = {}

    def register_pending_call(self, call_id: str, context: dict[str, str | None]) -> None:
        self._pending_calls[call_id] = context
        self._pending_call_times[call_id] = time.monotonic()

    def register_caller_info(self, call_sid: str, caller_name: str | None) -> None:
        self._caller_info[call_sid] = caller_name
        self._caller_info_times[call_sid] = time.monotonic()

    def pop_caller_info(self, call_sid: str) -> str | None:
        self._caller_info_times.pop(call_sid, None)
        return self._caller_info.pop(call_sid, None)

    def _sweep_stale_calls(self) -> None:
        now = time.monotonic()
        stale = [cid for cid, t in self._pending_call_times.items() if now - t > _PENDING_CALL_TTL]
        for cid in stale:
            self._pending_calls.pop(cid, None)
            self._pending_call_times.pop(cid, None)
            future = self._completion_futures.pop(cid, None)
            if future and not future.done():
                future.cancel()
            logger.warning("Swept stale pending call: %s", cid)

        stale_info = [sid for sid, t in self._caller_info_times.items() if now - t > _PENDING_CALL_TTL]
        for sid in stale_info:
            self._caller_info.pop(sid, None)
            self._caller_info_times.pop(sid, None)

    def register_completion_future(self, call_id: str) -> asyncio.Future[str]:
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._completion_futures[call_id] = future
        return future

    def resolve_call(self, call_id: str, summary: str) -> None:
        future = self._completion_futures.pop(call_id, None)
        if future and not future.done():
            future.set_result(summary)

    async def new_session(
        self,
        websocket: WebSocket,
        call_id: str | None = None,
        call_sid: str | None = None,
    ) -> tuple:
        from .agent_factory.realtime.agent import create_incoming_call_agent, create_outgoing_call_agent
        from .twilio_handler import TwilioHandler

        self._sweep_stale_calls()
        if call_id and call_id in self._pending_calls:
            context = self._pending_calls.pop(call_id)
            self._pending_call_times.pop(call_id, None)
            prompt_key = context.get("prompt")
            additional_context = context.get("additional_context")
            request_voice = context.get("voice")
            request_id = context.get("request_id")
            logger.info(
                "Creating outgoing call handler (call_id=%s, to=%s, prompt=%s)",
                call_id, context.get("to"), prompt_key,
            )
            result = create_outgoing_call_agent(prompt_key=prompt_key, additional_context=additional_context)
            voice = request_voice or result.voice
            return TwilioHandler(websocket, result.agent, voice=voice), request_id
        else:
            caller_name = self.pop_caller_info(call_sid) if call_sid else None
            logger.info("Creating incoming call handler (caller=%s)", caller_name or "unknown")
            result = create_incoming_call_agent(caller_name=caller_name)
            request_id = None

        return TwilioHandler(websocket, result.agent, voice=result.voice), request_id


manager = TwilioWebSocketManager()
