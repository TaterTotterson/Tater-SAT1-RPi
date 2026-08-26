from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from .config import StandaloneConfig


def validate_server_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.netloc:
        raise ValueError("Tater URL must be an http(s) or ws(s) URL with a hostname")
    return url


def effective_server_url(config: StandaloneConfig) -> str:
    try:
        override = config.runtime.server_url_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        override = ""
    if override:
        return validate_server_url(override)
    if config.tater.url:
        return validate_server_url(config.tater.url)
    if config.runtime.flavor == "standalone":
        return f"http://127.0.0.1:{config.tater.port}"
    return "http://tater.local:8501"


def provision_pairing(config: StandaloneConfig, pairing_code: str, server_url: str = "") -> str:
    if config.runtime.flavor != "satellite":
        raise ValueError("pairing is only available in the satellite image flavor")
    code = pairing_code.strip()
    if not code or any(character.isspace() for character in code):
        raise ValueError("pairing code must be a non-empty value without whitespace")
    url = validate_server_url(server_url) if server_url else effective_server_url(config)
    config.runtime.state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(config.runtime.state_dir, 0o700)
    _write_private(config.runtime.server_url_path, url, config.runtime.state_dir)
    _write_private(config.runtime.token_path, code, config.runtime.state_dir)
    return url


def _write_private(path: Path, value: str, owner_path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    try:
        owner = owner_path.stat()
        os.chown(temporary, owner.st_uid, owner.st_gid)
    except (AttributeError, PermissionError):
        pass
    os.replace(temporary, path)
    os.chmod(path, 0o600)
