from __future__ import annotations

import os
from pathlib import Path

_SECRETS_DIR = Path("/run/secrets")


def get_secret(
    name: str,
    env_var: str | None = None,
    default: str | None = None,
) -> str | None:
    """Read a secret from Docker secrets, falling back to an environment variable.

    In production Docker Compose mounts each secret as a file under
    ``/run/secrets/<name>``.  During local development (no Docker secrets)
    the value is read from the corresponding environment variable instead.
    """
    secret_path = _SECRETS_DIR / name
    if secret_path.exists():
        return secret_path.read_text().strip()
    return os.getenv(env_var or name.upper(), default)
