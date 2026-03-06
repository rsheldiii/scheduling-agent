"""Tests for src.secrets — get_secret resolution logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.secrets import get_secret


class TestGetSecret:
    def test_reads_from_docker_secret_file(self, tmp_path: Path):
        secret_file = tmp_path / "my_secret"
        secret_file.write_text("  docker-value  \n")

        with patch("src.secrets._SECRETS_DIR", tmp_path):
            assert get_secret("my_secret") == "docker-value"

    def test_falls_back_to_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_ENV_VAR", "env-value")
        with patch("src.secrets._SECRETS_DIR", Path("/nonexistent")):
            assert get_secret("my_secret", "MY_ENV_VAR") == "env-value"

    def test_falls_back_to_default(self):
        with patch("src.secrets._SECRETS_DIR", Path("/nonexistent")):
            assert get_secret("missing", "ALSO_MISSING", default="fallback") == "fallback"

    def test_returns_none_when_nothing_found(self):
        with patch("src.secrets._SECRETS_DIR", Path("/nonexistent")):
            assert get_secret("missing") is None

    def test_docker_secret_takes_priority_over_env(self, tmp_path: Path, monkeypatch):
        secret_file = tmp_path / "priority_test"
        secret_file.write_text("from-docker")
        monkeypatch.setenv("PRIORITY_TEST", "from-env")

        with patch("src.secrets._SECRETS_DIR", tmp_path):
            assert get_secret("priority_test", "PRIORITY_TEST") == "from-docker"

    def test_uses_name_as_env_var_when_no_env_var_given(self, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "uppercase-name")
        with patch("src.secrets._SECRETS_DIR", Path("/nonexistent")):
            # When env_var is None, falls back to name.upper()
            assert get_secret("my_secret") == "uppercase-name"
