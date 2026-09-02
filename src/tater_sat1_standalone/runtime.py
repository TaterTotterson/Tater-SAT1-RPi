from __future__ import annotations

import os
from pathlib import Path
import secrets

from .config import RuntimeConfig


def prepare_runtime(config: RuntimeConfig) -> str:
    for path in (
        config.state_dir,
        config.tater_runtime_dir,
        config.agent_lab_dir,
        config.core_dir,
        config.satellite_state_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    os.chmod(config.state_dir, 0o700)
    os.chmod(config.core_dir, 0o700)
    if config.flavor == "standalone":
        return ensure_private_token(config.token_path)
    try:
        token = config.token_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    if token:
        os.chmod(config.token_path, 0o600)
    return token


def mark_first_boot(config: RuntimeConfig) -> None:
    config.first_boot_marker_path.write_text("ready\n", encoding="utf-8")
    os.chmod(config.first_boot_marker_path, 0o600)


def ensure_private_token(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        try:
            token = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            token = ""
        if token:
            os.chmod(path, 0o600)
            return token

        candidate = secrets.token_urlsafe(32)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(candidate + "\n")
        return candidate
    raise RuntimeError(f"could not create or read token at {path}")
