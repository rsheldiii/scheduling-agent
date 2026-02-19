from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_PROMPTS_DIR = Path(__file__).parent / "prompts"
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


_incoming_prompts: dict[str, Prompt] = _load_prompts_from(_PROMPTS_DIR / "incoming")
_outgoing_prompts: dict[str, Prompt] = _load_prompts_from(_PROMPTS_DIR / "outgoing")


def get_incoming_prompt() -> Prompt:
    """Return the default incoming-call prompt."""
    return _incoming_prompts["default"]


def get_outgoing_prompt(key: str | None = None) -> Prompt:
    """Return an outgoing-call prompt by key, defaulting to doctor_appointment."""
    key = key or _DEFAULT_OUTGOING_KEY
    if key not in _outgoing_prompts:
        available = ", ".join(sorted(_outgoing_prompts.keys()))
        raise ValueError(f"Unknown outgoing prompt '{key}'. Available: {available}")
    return _outgoing_prompts[key]


def list_outgoing_prompts() -> list[Prompt]:
    """Return all available outgoing-call prompts."""
    return list(_outgoing_prompts.values())
