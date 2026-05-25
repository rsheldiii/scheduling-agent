"""Tests for src.tools.user_info — encryption, decryption, tiered loading; and src.prompts — render_template."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import src.tools.user_info as ui_module
from src.prompts import render_template
from src.tools.user_info import (
    decrypt_and_load,
    encrypt_file,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset both tier caches between tests."""
    ui_module._cached_public = None
    ui_module._cached_sensitive = None
    yield
    ui_module._cached_public = None
    ui_module._cached_sensitive = None


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
    def _make_encrypted(self, tmp_path: Path, data: dict, password: str) -> Path:
        plaintext_path = tmp_path / "user_info.yaml"
        encrypted_path = tmp_path / "user_info.yaml.enc"
        plaintext_path.write_text(yaml.dump(data), encoding="utf-8")
        encrypt_file(plaintext_path, encrypted_path, password=password)
        return encrypted_path

    def test_round_trip_tiered(self, tmp_path: Path):
        data = {
            "public": {"name": "Alice", "age": "32"},
            "sensitive": {"ssn_last_four": "9999"},
        }
        enc = self._make_encrypted(tmp_path, data, "pass")
        public, sensitive = decrypt_and_load(enc, password="pass")
        assert public == {"name": "Alice", "age": "32"}
        assert sensitive == {"ssn_last_four": "9999"}

    def test_round_trip_public_only(self, tmp_path: Path):
        data = {"public": {"name": "Bob"}}
        enc = self._make_encrypted(tmp_path, data, "pass")
        public, sensitive = decrypt_and_load(enc, password="pass")
        assert public == {"name": "Bob"}
        assert sensitive == {}

    def test_legacy_flat_format_treated_as_public(self, tmp_path: Path):
        """A flat dict (old format) lands entirely in public with empty sensitive."""
        data = {"name": "Carol", "phone_number": "+15551234567"}
        enc = self._make_encrypted(tmp_path, data, "pass")
        public, sensitive = decrypt_and_load(enc, password="pass")
        assert public == {"name": "Carol", "phone_number": "+15551234567"}
        assert sensitive == {}

    def test_wrong_password_fails(self, tmp_path: Path):
        enc = self._make_encrypted(tmp_path, {"public": {"x": "y"}}, "correct")
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_and_load(enc, password="wrong")

    def test_encrypt_no_password_raises(self, tmp_path: Path):
        plaintext_path = tmp_path / "user_info.yaml"
        plaintext_path.write_text("public:\n  x: y", encoding="utf-8")
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
# load_public_user_info / load_sensitive_user_info
# -------------------------------------------------------------------------

class TestLoadUserInfo:
    def _patch_decrypt(self, public: dict, sensitive: dict):
        return patch.object(
            ui_module,
            "decrypt_and_load",
            return_value=(public, sensitive),
        )

    def test_public_returns_public_fields(self, tmp_path: Path):
        fake_enc = tmp_path / "user_info.yaml.enc"
        fake_enc.write_text("{}")  # content doesn't matter — decrypt is patched
        with patch.object(ui_module, "_ENCRYPTED_PATH", fake_enc), \
             self._patch_decrypt({"name": "Alice"}, {"ssn_last_four": "1234"}):
            result = ui_module.load_public_user_info()
        assert result == {"name": "Alice"}

    def test_sensitive_returns_sensitive_fields(self, tmp_path: Path):
        fake_enc = tmp_path / "user_info.yaml.enc"
        fake_enc.write_text("{}")
        with patch.object(ui_module, "_ENCRYPTED_PATH", fake_enc), \
             self._patch_decrypt({"name": "Alice"}, {"ssn_last_four": "1234"}):
            result = ui_module.load_sensitive_user_info()
        assert result == {"ssn_last_four": "1234"}

    def test_sensitive_not_in_public(self, tmp_path: Path):
        fake_enc = tmp_path / "user_info.yaml.enc"
        fake_enc.write_text("{}")
        with patch.object(ui_module, "_ENCRYPTED_PATH", fake_enc), \
             self._patch_decrypt({"name": "Alice"}, {"ssn_last_four": "1234"}):
            public = ui_module.load_public_user_info()
            sensitive = ui_module.load_sensitive_user_info()
        assert "ssn_last_four" not in public
        assert "name" not in sensitive

    def test_returns_empty_when_no_encrypted_file(self, tmp_path: Path):
        with patch.object(ui_module, "_ENCRYPTED_PATH", tmp_path / "missing.enc"):
            public = ui_module.load_public_user_info()
            sensitive = ui_module.load_sensitive_user_info()
        assert public == {}
        assert sensitive == {}

    def test_caches_result(self, tmp_path: Path):
        with patch.object(ui_module, "_ENCRYPTED_PATH", tmp_path / "missing.enc"):
            first = ui_module.load_public_user_info()
            second = ui_module.load_public_user_info()
        assert first is second

    def test_returns_empty_on_decrypt_failure(self, tmp_path: Path):
        enc = tmp_path / "bad.enc"
        enc.write_text("not valid json")
        with patch.object(ui_module, "_ENCRYPTED_PATH", enc), \
             patch.object(ui_module, "get_secret", return_value="password"):
            public = ui_module.load_public_user_info()
            sensitive = ui_module.load_sensitive_user_info()
        assert public == {}
        assert sensitive == {}

    def test_decrypt_called_once_for_both_tiers(self, tmp_path: Path):
        fake_enc = tmp_path / "user_info.yaml.enc"
        fake_enc.write_text("{}")
        with patch.object(ui_module, "_ENCRYPTED_PATH", fake_enc), \
             self._patch_decrypt({"name": "X"}, {"ssn_last_four": "0000"}) as mock_decrypt:
            ui_module.load_public_user_info()
            ui_module.load_sensitive_user_info()
        mock_decrypt.assert_called_once()
