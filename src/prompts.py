from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Prompt:
    key: str
    name: str
    description: str
    instructions: str
    required_context: list[str] = field(default_factory=list)
    sensitive_fields: list[str] = field(default_factory=list)
    voice: str | None = None


class PromptLoader:
    """Lazy-loading prompt store backed by a local ``prompts/`` directory.

    Each agent instantiates its own loader pointed at the ``prompts/``
    directory co-located with its module::

        _prompts = PromptLoader(Path(__file__).parent / "prompts")

    Prompts can live directly in that directory or be organized into
    subdirectory *categories*::

        p = _prompts.get("default")                        # prompts/default.yaml
        p = _prompts.get("default", category="incoming")   # prompts/incoming/default.yaml
        all_outgoing = _prompts.list(category="outgoing")
    """

    def __init__(self, prompts_dir: Path | str) -> None:
        self._dir = Path(prompts_dir)
        self._cache: dict[str, dict[str, Prompt]] = {}

    @staticmethod
    def _parse(path: Path) -> Prompt:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return Prompt(
            key=path.stem,
            name=data["name"],
            description=data["description"],
            instructions=data["instructions"].strip(),
            required_context=data.get("required_context", []),
            sensitive_fields=data.get("sensitive_fields", []),
            voice=data.get("voice"),
        )

    def _load(self, category: str) -> dict[str, Prompt]:
        if category not in self._cache:
            directory = self._dir / category if category else self._dir
            prompts: dict[str, Prompt] = {}
            if directory.is_dir():
                for path in sorted(directory.glob("*.yaml")):
                    prompt = self._parse(path)
                    prompts[prompt.key] = prompt
            self._cache[category] = prompts
        return self._cache[category]

    def get(self, key: str = "default", *, category: str = "") -> Prompt:
        """Return a single prompt by *key* (filename stem).

        If *category* is given, look inside that subdirectory.
        """
        prompts = self._load(category)
        if key not in prompts:
            available = ", ".join(sorted(prompts.keys()))
            raise ValueError(
                f"Unknown prompt '{key}' (category='{category}'). "
                f"Available: {available}"
            )
        return prompts[key]

    def list(self, category: str = "") -> list[Prompt]:
        """Return all prompts, optionally filtered to a *category* subdirectory."""
        return list(self._load(category).values())
