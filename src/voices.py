"""Available OpenAI Realtime API voices.

The Realtime API does not expose a dynamic endpoint for listing voices, so we
maintain the canonical set here.  Last updated for gpt-realtime-2.
"""

from __future__ import annotations

VOICES: dict[str, str] = {
    "alloy": "Neutral and balanced",
    "ash": "Clear and confident",
    "ballad": "Warm and expressive",
    "cedar": "Friendly and natural (recommended)",
    "coral": "Soft and approachable",
    "echo": "Smooth and resonant",
    "marin": "Bright and natural (recommended)",
    "sage": "Calm and thoughtful",
    "shimmer": "Light and energetic",
    "verse": "Rich and articulate",
}

DEFAULT_VOICE = "cedar"


def is_valid_voice(voice: str) -> bool:
    return voice.lower() in VOICES


def list_voices() -> list[dict[str, str]]:
    return [{"id": v, "description": d} for v, d in VOICES.items()]
