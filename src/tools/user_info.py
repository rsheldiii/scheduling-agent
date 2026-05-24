from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
from pathlib import Path

import yaml
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ..secrets import get_secret

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PLAINTEXT_PATH = _PROJECT_ROOT / "user_info.yaml"
_ENCRYPTED_PATH = _PROJECT_ROOT / "user_info.yaml.enc"
_ENV_VAR = "USER_INFO_SECRET"
_PBKDF2_ITERATIONS = 600_000

logger = logging.getLogger(__name__)

# Separate caches for each tier — populated together on first load.
_cached_public: dict[str, str] | None = None
_cached_sensitive: dict[str, str] | None = None


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def encrypt_file(
    plaintext_path: Path = _PLAINTEXT_PATH,
    encrypted_path: Path = _ENCRYPTED_PATH,
    password: str | None = None,
) -> None:
    password = password or get_secret("user_info_secret", _ENV_VAR)
    if not password:
        raise ValueError(
            f"No password provided and {_ENV_VAR} environment variable is not set"
        )

    plaintext = plaintext_path.read_bytes()
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    token = Fernet(key).encrypt(plaintext)

    payload = {
        "salt": base64.b64encode(salt).decode(),
        "data": token.decode(),
    }
    encrypted_path.write_text(json.dumps(payload, indent=2))
    logger.info("Encrypted %s -> %s", plaintext_path, encrypted_path)


def decrypt_and_load(
    encrypted_path: Path = _ENCRYPTED_PATH,
    password: str | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Decrypt and return ``(public, sensitive)`` field dicts.

    The YAML must have top-level ``public:`` and ``sensitive:`` sections.
    A legacy flat dict is treated as entirely public for backward compatibility.
    """
    password = password or get_secret("user_info_secret", _ENV_VAR)
    if not password:
        raise ValueError(
            f"No password provided and {_ENV_VAR} environment variable is not set"
        )

    payload = json.loads(encrypted_path.read_text())
    salt = base64.b64decode(payload["salt"])
    token = payload["data"].encode()

    key = _derive_key(password, salt)
    try:
        plaintext = Fernet(key).decrypt(token)
    except InvalidToken:
        raise ValueError("Decryption failed — wrong password or corrupted file")

    data = yaml.safe_load(plaintext)
    if isinstance(data, dict) and ("public" in data or "sensitive" in data):
        public = {str(k): str(v) for k, v in (data.get("public") or {}).items()}
        sensitive = {str(k): str(v) for k, v in (data.get("sensitive") or {}).items()}
    else:
        # Legacy flat format — treat everything as public.
        public = {str(k): str(v) for k, v in data.items()}
        sensitive = {}
    return public, sensitive


def _load_all() -> None:
    """Decrypt and cache both tiers. No-op if already loaded."""
    global _cached_public, _cached_sensitive
    if _cached_public is not None:
        return

    if not _ENCRYPTED_PATH.exists():
        logger.warning("%s not found — user info unavailable", _ENCRYPTED_PATH)
        _cached_public = {}
        _cached_sensitive = {}
        return

    try:
        _cached_public, _cached_sensitive = decrypt_and_load()
    except Exception as e:
        logger.warning("Could not load user info: %s", e)
        _cached_public = {}
        _cached_sensitive = {}


def load_public_user_info() -> dict[str, str]:
    """Return non-sensitive user fields (name, age, DOB, etc.). Safe for all agents."""
    _load_all()
    assert _cached_public is not None
    return _cached_public


def load_sensitive_user_info() -> dict[str, str]:
    """Return sensitive user fields (SSN, CC info, etc.). For outgoing agents only."""
    _load_all()
    assert _cached_sensitive is not None
    return _cached_sensitive


def render_template(template: str, user_info: dict[str, str]) -> str:
    """Replace {key} placeholders with values from user_info.

    Unrecognized keys are left as-is so non-template braces are preserved.
    """

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return user_info[key] if key in user_info else match.group(0)

    return re.sub(r"\{(\w+)\}", replacer, template)


def _cli() -> None:
    usage = "Usage: python user_info.py [encrypt|decrypt]"
    if len(sys.argv) != 2 or sys.argv[1] not in ("encrypt", "decrypt"):
        print(usage)
        sys.exit(1)

    command = sys.argv[1]

    if command == "encrypt":
        if not _PLAINTEXT_PATH.exists():
            print(f"Error: {_PLAINTEXT_PATH} not found")
            sys.exit(1)
        encrypt_file()

    elif command == "decrypt":
        if not _ENCRYPTED_PATH.exists():
            print(f"Error: {_ENCRYPTED_PATH} not found")
            sys.exit(1)
        public, sensitive = decrypt_and_load()
        print(yaml.dump({"public": public, "sensitive": sensitive}, default_flow_style=False))


if __name__ == "__main__":
    _cli()
