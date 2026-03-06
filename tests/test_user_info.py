"""Tests for src.tools.user_info — encryption, decryption, render_template, get_user_info."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import src.tools.user_info as ui_module
from src.tools.user_info import (
    decrypt_and_load,
    encrypt_file,
    render_template,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level user-info cache between tests."""
    ui_module._cached_user_info = None
    yield
    ui_module._cached_user_info = None


# -------------------------------------------------------------------------
# render_template
# -------------------------------------------------------------------------

class TestRenderTemplate:
    def test_basic_substitution(self):
        assert render_template("Hello {name}!", {"name": "Alice"}) == "Hello Alice!"

    def test_multiple_substitutions(self):
        result = render_template("{name} is {age} years old", {"name": "Bob", "age": "30"})
        assert result == "Bob is 30 years old"

    def test_unknown_keys_left_as_is(self):
        assert render_template("Hi {name}, your {unknown} is ready", {"name": "Carol"}) == \
            "Hi Carol, your {unknown} is ready"

    def test_empty_user_info(self):
        assert render_template("Hello {name}!", {}) == "Hello {name}!"

    def test_no_placeholders(self):
        assert render_template("No placeholders here.", {"name": "X"}) == "No placeholders here."

    def test_braces_without_word_chars_preserved(self):
        assert render_template("JSON: {}", {}) == "JSON: {}"


# -------------------------------------------------------------------------
# encrypt_file / decrypt_and_load round-trip
# -------------------------------------------------------------------------

class TestEncryptDecrypt:
    def test_round_trip(self, tmp_path: Path):
        plaintext_path = tmp_path / "user_info.yaml"
        encrypted_path = tmp_path / "user_info.yaml.enc"
        data = {"name": "Alice", "phone_number": "+15551234567"}
        plaintext_path.write_text(yaml.dump(data), encoding="utf-8")

        password = "test-password-123"
        encrypt_file(plaintext_path, encrypted_path, password=password)

        assert encrypted_path.exists()
        payload = json.loads(encrypted_path.read_text())
        assert "salt" in payload
        assert "data" in payload

        result = decrypt_and_load(encrypted_path, password=password)
        assert result["name"] == "Alice"
        assert result["phone_number"] == "+15551234567"

    def test_wrong_password_fails(self, tmp_path: Path):
        plaintext_path = tmp_path / "user_info.yaml"
        encrypted_path = tmp_path / "user_info.yaml.enc"
        plaintext_path.write_text(yaml.dump({"key": "value"}), encoding="utf-8")

        encrypt_file(plaintext_path, encrypted_path, password="correct")

        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_and_load(encrypted_path, password="wrong")

    def test_encrypt_no_password_raises(self, tmp_path: Path):
        plaintext_path = tmp_path / "user_info.yaml"
        plaintext_path.write_text("x: y", encoding="utf-8")

        with patch.object(ui_module, "get_secret", return_value=None):
            with pytest.raises(ValueError, match="No password"):
                encrypt_file(plaintext_path, tmp_path / "out.enc")

    def test_decrypt_no_password_raises(self, tmp_path: Path):
        enc_path = tmp_path / "dummy.enc"
        enc_path.write_text(json.dumps({"salt": "AA==", "data": "x"}))

        with patch.object(ui_module, "get_secret", return_value=None):
            with pytest.raises(ValueError, match="No password"):
                decrypt_and_load(enc_path)


# -------------------------------------------------------------------------
# load_user_info
# -------------------------------------------------------------------------

class TestLoadUserInfo:
    def test_returns_empty_when_no_encrypted_file(self, tmp_path: Path):
        with patch.object(ui_module, "_ENCRYPTED_PATH", tmp_path / "missing.enc"):
            result = ui_module.load_user_info()
        assert result == {}

    def test_caches_result(self, tmp_path: Path):
        with patch.object(ui_module, "_ENCRYPTED_PATH", tmp_path / "missing.enc"):
            first = ui_module.load_user_info()
            second = ui_module.load_user_info()
        assert first is second

    def test_returns_empty_on_decrypt_failure(self, tmp_path: Path):
        enc = tmp_path / "bad.enc"
        enc.write_text("not valid json")
        with patch.object(ui_module, "_ENCRYPTED_PATH", enc), \
             patch.object(ui_module, "get_secret", return_value="password"):
            result = ui_module.load_user_info()
        assert result == {}


# -------------------------------------------------------------------------
# get_user_info (function tool)
# -------------------------------------------------------------------------

class TestGetUserInfo:
    @pytest.mark.asyncio
    async def test_returns_known_field(self):
        from unittest.mock import MagicMock
        ctx = MagicMock()
        with patch.object(ui_module, "load_user_info", return_value={"name": "Alice"}):
            result = await ui_module.get_user_info.on_invoke_tool(ctx, '{"field": "name"}')
        assert result == "Alice"

    @pytest.mark.asyncio
    async def test_unknown_field_lists_available(self):
        from unittest.mock import MagicMock
        ctx = MagicMock()
        with patch.object(ui_module, "load_user_info", return_value={"name": "A", "age": "30"}):
            result = await ui_module.get_user_info.on_invoke_tool(ctx, '{"field": "ssn"}')
        assert "No information found for 'ssn'" in result
        assert "age" in result
        assert "name" in result
