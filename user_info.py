from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path

import yaml
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_PLAINTEXT_PATH = Path(__file__).parent / "user_info.yaml"
_ENCRYPTED_PATH = Path(__file__).parent / "user_info.yaml.enc"
_ENV_VAR = "USER_INFO_SECRET"
_PBKDF2_ITERATIONS = 600_000

_cached_user_info: dict[str, str] | None = None


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
    password = password or os.getenv(_ENV_VAR)
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
    print(f"Encrypted {plaintext_path} -> {encrypted_path}")


def decrypt_and_load(
    encrypted_path: Path = _ENCRYPTED_PATH,
    password: str | None = None,
) -> dict[str, str]:
    password = password or os.getenv(_ENV_VAR)
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
    return {str(k): str(v) for k, v in data.items()}


def load_user_info() -> dict[str, str]:
    """Load and cache decrypted user info. Returns empty dict on failure."""
    global _cached_user_info
    if _cached_user_info is not None:
        return _cached_user_info

    if not _ENCRYPTED_PATH.exists():
        print(f"Warning: {_ENCRYPTED_PATH} not found — user info unavailable")
        _cached_user_info = {}
        return _cached_user_info

    try:
        _cached_user_info = decrypt_and_load()
    except Exception as e:
        print(f"Warning: could not load user info: {e}")
        _cached_user_info = {}

    return _cached_user_info


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
        info = decrypt_and_load()
        print(yaml.dump(info, default_flow_style=False))


if __name__ == "__main__":
    _cli()
