from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_DEFAULT_OUTGOING_KEY = "doctor_appointment"


@dataclass(frozen=True)
class Prompt:
    key: str
    name: str
    description: str
    instructions: str


def _load_prompt(path: Path) -> Prompt:
    """Load a single prompt from a YAML file.  The key is the filename stem."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Prompt(
        key=path.stem,
        name=data["name"],
        description=data["description"],
        instructions=data["instructions"].strip(),
    )


def _load_prompts_from(directory: Path) -> dict[str, Prompt]:
    prompts: dict[str, Prompt] = {}
    if not directory.is_dir():
        return prompts
    for path in sorted(directory.glob("*.yaml")):
        prompt = _load_prompt(path)
        prompts[prompt.key] = prompt
    return prompts


_incoming_prompts: dict[str, Prompt] | None = None
_outgoing_prompts: dict[str, Prompt] | None = None
_sms_prompts: dict[str, Prompt] | None = None


def _get_incoming_prompts() -> dict[str, Prompt]:
    global _incoming_prompts
    if _incoming_prompts is None:
        _incoming_prompts = _load_prompts_from(_PROMPTS_DIR / "incoming")
    return _incoming_prompts


def _get_outgoing_prompts() -> dict[str, Prompt]:
    global _outgoing_prompts
    if _outgoing_prompts is None:
        _outgoing_prompts = _load_prompts_from(_PROMPTS_DIR / "outgoing")
    return _outgoing_prompts


def _get_sms_prompts() -> dict[str, Prompt]:
    global _sms_prompts
    if _sms_prompts is None:
        _sms_prompts = _load_prompts_from(_PROMPTS_DIR / "sms")
    return _sms_prompts


def get_incoming_prompt() -> Prompt:
    """Return the default incoming-call prompt."""
    return _get_incoming_prompts()["default"]


def get_outgoing_prompt(key: str | None = None) -> Prompt:
    """Return an outgoing-call prompt by key, defaulting to doctor_appointment."""
    key = key or _DEFAULT_OUTGOING_KEY
    prompts = _get_outgoing_prompts()
    if key not in prompts:
        available = ", ".join(sorted(prompts.keys()))
        raise ValueError(f"Unknown outgoing prompt '{key}'. Available: {available}")
    return prompts[key]


def get_sms_prompt() -> Prompt:
    """Return the default SMS agent prompt."""
    return _get_sms_prompts()["default"]


def list_outgoing_prompts() -> list[Prompt]:
    """Return all available outgoing-call prompts."""
    return list(_get_outgoing_prompts().values())
