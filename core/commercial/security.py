from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


def generate_fernet_key() -> str:
    """Generate a Fernet key string suitable for APP_SECRET_KEY."""
    return Fernet.generate_key().decode("utf-8")


def _normalize_key(raw: str) -> bytes:
    raw = str(raw or "").strip()
    if not raw:
        raise ValueError("APP_SECRET_KEY 为空。请设置 APP_SECRET_KEY，或调用 generate_commercial_secret_key 生成。")
    try:
        # A valid Fernet key is urlsafe-base64-encoded 32 bytes.
        Fernet(raw.encode("utf-8"))
        return raw.encode("utf-8")
    except Exception:
        # Allow a human string in dev mode by deriving a deterministic 32-byte key.
        import hashlib

        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)


class SecretBox:
    """Small encryption helper for credentials.

    Production recommendation: set APP_SECRET_KEY in the environment and keep it
    outside the project directory. For local MVP, a dev key file can be created
    in the workspace, but do not use that for a public service.
    """

    def __init__(self, workdir: Path):
        self.workdir = Path(workdir)
        self.key_source = "env"
        raw = os.getenv("APP_SECRET_KEY", "").strip()
        if not raw:
            key_file = self.workdir / "commercial_secret.key"
            if key_file.exists():
                raw = key_file.read_text(encoding="utf-8").strip()
                self.key_source = "workspace_file"
            else:
                raw = generate_fernet_key()
                key_file.write_text(raw, encoding="utf-8")
                self.key_source = "workspace_file_created"
        self._fernet = Fernet(_normalize_key(raw))

    def encrypt(self, value: str | None) -> str:
        if value is None:
            return ""
        value = str(value)
        if not value:
            return ""
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str | None) -> str:
        if not token:
            return ""
        try:
            return self._fernet.decrypt(str(token).encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("凭据解密失败：APP_SECRET_KEY 可能已变化。") from exc


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    value = str(value)
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "***" + value[-2:]


def public_record(row: dict[str, Any]) -> dict[str, Any]:
    """Remove encrypted secret fields before returning to UI/agent."""
    hidden = {"encrypted_username", "encrypted_password", "encrypted_cookie", "password", "cookie", "password_hash", "token_hash"}
    return {k: v for k, v in row.items() if k not in hidden}
