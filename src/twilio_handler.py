from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any

from fastapi import WebSocket

from agents import function_tool
from agents.realtime import (
    RealtimeAgent,
    RealtimePlaybackTracker,
    RealtimeRunner,
    RealtimeSession,
    RealtimeSessionEvent,
)

logger = logging.getLogger(__name__)


class TwilioHandler:
    def __init__(self, twilio_websocket: WebSocket, agent: RealtimeAgent, voice: str | None = None):
        self.agent = agent
        self.twilio_websocket = twilio_websocket
        self._voice = voice
        self.session: RealtimeSession | None = None
        self.playback_tracker = RealtimePlaybackTracker()

        self._realtime_session_task: asyncio.Task[None] | None = None
        self._message_loop_task: asyncio.Task[None] | None = None
        self._end_call_task: asyncio.Task[None] | None = None
        self._end_call_event = asyncio.Event()
        self._audio_done_after_end = asyncio.Event()

        self._stream_sid: str | None = None

        self._mark_counter = 0
        self._mark_data: dict[
            str, tuple[str, int, int]
        ] = {}

        self._history: list[Any] = []

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> TwilioHandler:
        await self._setup_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self._cancel_tasks()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Set up the session and spawn background tasks.

        Prefer using the async context manager (``async with handler:``)
        which guarantees cleanup.  If you call ``start()`` directly, you
        are responsible for calling ``cleanup()`` afterwards.
        """
        await self._setup_session()

    async def wait_until_done(self) -> None:
        """Block until the Twilio message loop terminates."""
        if self._message_loop_task is not None:
            await self._message_loop_task

    async def cleanup(self) -> None:
        """Cancel all background tasks.  Safe to call multiple times."""
        await self._cancel_tasks()

    def get_transcript(self) -> str:
        """Format captured history into a human-readable transcript."""
        lines: list[str] = []
        for item in self._history:
            if not hasattr(item, "role") or not hasattr(item, "content"):
                continue
            role = "User" if item.role == "user" else "Assistant"
            parts: list[str] = []
            for entry in item.content:
                text = getattr(entry, "transcript", None) or getattr(entry, "text", None)
                if text:
                    parts.append(text)
            if parts:
                lines.append(f"{role}: {' '.join(parts)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _setup_session(self) -> None:
        """Create the realtime session and spawn background tasks."""
        from .secrets import get_secret

        api_key = get_secret("openai_api_key", "OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not configured")

        end_call_event = self._end_call_event

        @function_tool
        def end_call() -> str:
            """End the phone call. Call this when the conversation is complete and goodbyes have been exchanged."""
            end_call_event.set()
            return "Ending the call now."

        agent = self.agent.clone(tools=[*self.agent.tools, end_call])
        runner = RealtimeRunner(agent)

        from .voices import DEFAULT_VOICE
        voice = self._voice or os.getenv("REALTIME_VOICE") or DEFAULT_VOICE

        self.session = await runner.run(
            model_config={
                "api_key": api_key,
                "initial_model_settings": {
                    "input_audio_format": "audio/pcmu",
                    "output_audio_format": "audio/pcmu",
                    "voice": voice,
                    "turn_detection": {
                        "type": "semantic_vad",
                        "interrupt_response": True,
                        "create_response": True,
                    },
                },
                "playback_tracker": self.playback_tracker,
            }
        )

        await self.session.enter()
        await self.twilio_websocket.accept()
        logger.info("Twilio WebSocket connection accepted")

        # Spawn tasks with structured cleanup: if any creation fails,
        # already-created tasks are cancelled before re-raising.
        tasks_created: list[asyncio.Task[None]] = []
        try:
            task = asyncio.create_task(self._realtime_session_loop())
            self._realtime_session_task = task
            tasks_created.append(task)

            task = asyncio.create_task(self._twilio_message_loop())
            self._message_loop_task = task
            tasks_created.append(task)

            task = asyncio.create_task(self._end_call_watcher())
            self._end_call_task = task
            tasks_created.append(task)
        except Exception:
            for t in tasks_created:
                t.cancel()
            raise

    async def _cancel_tasks(self) -> None:
        """Cancel all background tasks and wait for them to finish."""
        tasks = [
            self._realtime_session_task,
            self._message_loop_task,
            self._end_call_task,
        ]
        live = [t for t in tasks if t is not None and not t.done()]
        for t in live:
            t.cancel()
        if live:
            await asyncio.gather(*live, return_exceptions=True)

    # ------------------------------------------------------------------
    # Event loops
    # ------------------------------------------------------------------

    async def _realtime_session_loop(self) -> None:
        """Listen for events from the realtime session."""
        assert self.session is not None
        try:
            async for event in self.session:
                await self._handle_realtime_event(event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error in realtime session loop: %s", e)

    async def _twilio_message_loop(self) -> None:
        """Listen for messages from Twilio WebSocket and handle them."""
        try:
            while True:
                message_text = await self.twilio_websocket.receive_text()
                message = json.loads(message_text)
                await self._handle_twilio_message(message)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Twilio message as JSON: %s", e)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self._end_call_event.is_set():
                logger.debug("Twilio message loop ended (expected after end_call)")
            else:
                logger.info("Twilio message loop ended: %s", e)

    async def _end_call_watcher(self) -> None:
        """Wait for the end_call tool to fire, let the model finish speaking, then disconnect.

        After the tool fires we wait for the next ``audio_end`` event (the
        model finishing its final response) before closing.  A hard timeout
        prevents hanging forever if the event never arrives.
        """
        try:
            await self._end_call_event.wait()
            logger.info("end_call triggered, waiting for final audio to finish")
            try:
                await asyncio.wait_for(self._audio_done_after_end.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for final audio after end_call")
            await asyncio.sleep(0.5)
            logger.info("Closing Twilio WebSocket")
            await self.twilio_websocket.close()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Error in end_call watcher: %s", e)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_realtime_event(self, event: RealtimeSessionEvent) -> None:
        """Handle events from the realtime session."""
        if event.type == "audio":
            base64_audio = base64.b64encode(event.audio.data).decode("utf-8")
            await self.twilio_websocket.send_text(
                json.dumps(
                    {
                        "event": "media",
                        "streamSid": self._stream_sid,
                        "media": {"payload": base64_audio},
                    }
                )
            )

            self._mark_counter += 1
            mark_id = str(self._mark_counter)
            self._mark_data[mark_id] = (
                event.audio.item_id,
                event.audio.content_index,
                len(event.audio.data),
            )

            await self.twilio_websocket.send_text(
                json.dumps(
                    {
                        "event": "mark",
                        "streamSid": self._stream_sid,
                        "mark": {"name": mark_id},
                    }
                )
            )

        elif event.type == "audio_interrupted":
            logger.debug("Sending audio interrupted to Twilio")
            await self.twilio_websocket.send_text(
                json.dumps({"event": "clear", "streamSid": self._stream_sid})
            )
        elif event.type == "audio_end":
            logger.debug("Audio end")
            if self._end_call_event.is_set():
                self._audio_done_after_end.set()
        elif event.type == "history_updated":
            self._history = list(event.history)
        elif event.type == "history_added":
            self._history.append(event.item)
            self._log_transcript_item(event.item)
        elif event.type == "raw_model_event":
            pass
        else:
            pass

    def _log_transcript_item(self, item: Any) -> None:
        """Log a single transcript item as it arrives."""
        if not hasattr(item, "role") or not hasattr(item, "content"):
            return
        role = "User" if item.role == "user" else "Assistant"
        parts: list[str] = []
        for entry in item.content:
            text = getattr(entry, "transcript", None) or getattr(entry, "text", None)
            if text:
                parts.append(text)
        if parts:
            logger.info("[Transcript] %s: %s", role, " ".join(parts))

    async def _handle_twilio_message(self, message: dict[str, Any]) -> None:
        """Handle incoming messages from Twilio Media Stream."""
        try:
            event = message.get("event")

            if event == "connected":
                logger.info("Twilio media stream connected")
            elif event == "start":
                start_data = message.get("start", {})
                self._stream_sid = start_data.get("streamSid")
                logger.info("Media stream started with SID: %s", self._stream_sid)
            elif event == "media":
                await self._handle_media_event(message)
            elif event == "mark":
                await self._handle_mark_event(message)
            elif event == "stop":
                logger.info("Media stream stopped")
        except Exception as e:
            logger.error("Error handling Twilio message: %s", e)

    async def _handle_media_event(self, message: dict[str, Any]) -> None:
        """Forward audio from Twilio directly to OpenAI with no buffering."""
        if not self.session:
            return
        media = message.get("media", {})
        payload = media.get("payload", "")
        if payload:
            try:
                await self.session.send_audio(base64.b64decode(payload))
            except Exception as e:
                logger.error("Error forwarding audio to OpenAI: %s", e)

    async def _handle_mark_event(self, message: dict[str, Any]) -> None:
        """Handle mark events from Twilio to update playback tracker."""
        try:
            mark_data = message.get("mark", {})
            mark_id = mark_data.get("name", "")

            if mark_id in self._mark_data:
                item_id, item_content_index, byte_count = self._mark_data[mark_id]
                audio_bytes = b"\x00" * byte_count
                self.playback_tracker.on_play_bytes(item_id, item_content_index, audio_bytes)
                logger.debug(
                    "Playback tracker updated: %s, index %s, %s bytes",
                    item_id, item_content_index, byte_count,
                )
                del self._mark_data[mark_id]

        except Exception as e:
            logger.error("Error handling mark event: %s", e)
