"""Tests for src.prompts — Prompt dataclass and PromptLoader."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.prompts import Prompt, PromptLoader


class TestPromptDataclass:
    def test_defaults(self):
        p = Prompt(key="k", name="n", description="d", instructions="i")
        assert p.required_context == []
        assert p.voice is None

    def test_frozen(self):
        p = Prompt(key="k", name="n", description="d", instructions="i")
        with pytest.raises(AttributeError):
            p.name = "changed"  # type: ignore[misc]


class TestPromptLoaderGet:
    def test_get_root_default(self, tmp_prompts: Path):
        loader = PromptLoader(tmp_prompts)
        prompt = loader.get("default")
        assert prompt.key == "default"
        assert prompt.name == "Root Default"

    def test_get_with_category(self, tmp_prompts: Path):
        loader = PromptLoader(tmp_prompts)
        prompt = loader.get("default", category="incoming")
        assert prompt.name == "Incoming Default"

    def test_get_outgoing_with_voice(self, tmp_prompts: Path):
        loader = PromptLoader(tmp_prompts)
        prompt = loader.get("doctor_appointment", category="outgoing")
        assert prompt.voice == "alloy"
        assert prompt.required_context == ["preferred date", "doctor name"]

    def test_get_unknown_key_raises(self, tmp_prompts: Path):
        loader = PromptLoader(tmp_prompts)
        with pytest.raises(ValueError, match="Unknown prompt 'nonexistent'"):
            loader.get("nonexistent")

    def test_get_unknown_category_raises(self, tmp_prompts: Path):
        loader = PromptLoader(tmp_prompts)
        with pytest.raises(ValueError, match="Unknown prompt"):
            loader.get("default", category="nope")

    def test_instructions_stripped(self, tmp_path: Path):
        """Instructions with leading/trailing whitespace should be stripped."""
        import yaml

        data = {
            "name": "Test",
            "description": "desc",
            "instructions": "  hello world  \n",
        }
        (tmp_path / "test.yaml").write_text(yaml.dump(data), encoding="utf-8")
        loader = PromptLoader(tmp_path)
        assert loader.get("test").instructions == "hello world"


class TestPromptLoaderList:
    def test_list_root(self, tmp_prompts: Path):
        loader = PromptLoader(tmp_prompts)
        prompts = loader.list()
        assert len(prompts) == 1
        assert prompts[0].key == "default"

    def test_list_outgoing(self, tmp_prompts: Path):
        loader = PromptLoader(tmp_prompts)
        prompts = loader.list(category="outgoing")
        keys = {p.key for p in prompts}
        assert keys == {"doctor_appointment", "restaurant_reservation"}

    def test_list_empty_category(self, tmp_prompts: Path):
        loader = PromptLoader(tmp_prompts)
        assert loader.list(category="nonexistent") == []


class TestPromptLoaderCaching:
    def test_same_category_returns_cached(self, tmp_prompts: Path):
        loader = PromptLoader(tmp_prompts)
        first = loader.get("default")
        second = loader.get("default")
        assert first is second

    def test_different_categories_independent(self, tmp_prompts: Path):
        loader = PromptLoader(tmp_prompts)
        root = loader.get("default")
        incoming = loader.get("default", category="incoming")
        assert root is not incoming
        assert root.name != incoming.name
