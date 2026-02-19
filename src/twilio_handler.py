from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any

from fastapi import WebSocket

from agents.realtime import (
    RealtimeAgent,
    RealtimePlaybackTracker,
    RealtimeRunner,
    RealtimeSession,
    RealtimeSessionEvent,
)

logger = logging.getLogger(__name__)


class TwilioHandler:
    CHUNK_LENGTH_S = 0.05
    SAMPLE_RATE = 8000
    BUFFER_SIZE_BYTES = int(SAMPLE_RATE * CHUNK_LENGTH_S)

    def __init__(self, twilio_websocket: WebSocket, agent: RealtimeAgent):
        self.agent = agent
        self.twilio_websocket = twilio_websocket
        self._message_loop_task: asyncio.Task[None] | None = None
        self.session: RealtimeSession | None = None
        self.playback_tracker = RealtimePlaybackTracker()

        self._stream_sid: str | None = None
        self._audio_buffer: bytearray = bytearray()
        self._last_buffer_send_time = time.time()

        # Mark event tracking for playback
        self._mark_counter = 0
        self._mark_data: dict[
            str, tuple[str, int, int]
        ] = {}  # mark_id -> (item_id, content_index, byte_count)

        # Transcript capture — latest history snapshot from the realtime session
        self._history: list[Any] = []

    async def start(self) -> None:
        """Start the session."""
        runner = RealtimeRunner(self.agent)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

        self.session = await runner.run(
            model_config={
                "api_key": api_key,
                "initial_model_settings": {
                    "input_audio_format": "g711_ulaw",
                    "output_audio_format": "g711_ulaw",
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

        self._realtime_session_task = asyncio.create_task(self._realtime_session_loop())
        self._message_loop_task = asyncio.create_task(self._twilio_message_loop())
        self._buffer_flush_task = asyncio.create_task(self._buffer_flush_loop())

    async def wait_until_done(self) -> None:
        """Wait until the session is done."""
        assert self._message_loop_task is not None
        await self._message_loop_task

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
        except Exception as e:
            logger.info("Twilio message loop ended: %s", e)
        finally:
            self._realtime_session_task.cancel()
            self._buffer_flush_task.cancel()

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

            # Send mark event for playback tracking
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
        elif event.type == "history_updated":
            self._history = list(event.history)
        elif event.type == "history_added":
            self._history.append(event.item)
        elif event.type == "raw_model_event":
            pass
        else:
            pass

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
        """Handle audio data from Twilio - buffer it before sending to OpenAI."""
        media = message.get("media", {})
        payload = media.get("payload", "")

        if payload:
            try:
                # Decode base64 audio from Twilio (µ-law format)
                ulaw_bytes = base64.b64decode(payload)

                # Add original µ-law to buffer for OpenAI (they expect µ-law)
                self._audio_buffer.extend(ulaw_bytes)

                # Send buffered audio if we have enough data
                if len(self._audio_buffer) >= self.BUFFER_SIZE_BYTES:
                    await self._flush_audio_buffer()

            except Exception as e:
                logger.error("Error processing audio from Twilio: %s", e)

    async def _handle_mark_event(self, message: dict[str, Any]) -> None:
        """Handle mark events from Twilio to update playback tracker."""
        try:
            mark_data = message.get("mark", {})
            mark_id = mark_data.get("name", "")

            # Look up stored data for this mark ID
            if mark_id in self._mark_data:
                item_id, item_content_index, byte_count = self._mark_data[mark_id]

                # Convert byte count back to bytes for playback tracker
                audio_bytes = b"\x00" * byte_count  # Placeholder bytes

                # Update playback tracker
                self.playback_tracker.on_play_bytes(item_id, item_content_index, audio_bytes)
                logger.debug(
                    "Playback tracker updated: %s, index %s, %s bytes",
                    item_id, item_content_index, byte_count,
                )

                # Clean up the stored data
                del self._mark_data[mark_id]

        except Exception as e:
            logger.error("Error handling mark event: %s", e)

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

    async def _flush_audio_buffer(self) -> None:
        """Send buffered audio to OpenAI."""
        if not self._audio_buffer or not self.session:
            return

        try:
            # Send the buffered audio
            buffer_data = bytes(self._audio_buffer)
            await self.session.send_audio(buffer_data)

            # Clear the buffer
            self._audio_buffer.clear()
            self._last_buffer_send_time = time.time()

        except Exception as e:
            logger.error("Error sending buffered audio to OpenAI: %s", e)

    async def _buffer_flush_loop(self) -> None:
        """Periodically flush audio buffer to prevent stale data."""
        try:
            while True:
                await asyncio.sleep(self.CHUNK_LENGTH_S)  # Check every 50ms

                # If buffer has data and it's been too long since last send, flush it
                current_time = time.time()
                if (
                    self._audio_buffer
                    and current_time - self._last_buffer_send_time > self.CHUNK_LENGTH_S * 2
                ):
                    await self._flush_audio_buffer()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error in buffer flush loop: %s", e)
