from __future__ import annotations

from pathlib import Path
import re
import uuid

from .config import StandaloneConfig


IDENTITY_PATHS = (
    Path("/proc/device-tree/serial-number"),
    Path("/sys/firmware/devicetree/base/serial-number"),
    Path("/etc/machine-id"),
)


def hardware_suffix(paths: tuple[Path, ...] = IDENTITY_PATHS) -> str:
    for path in paths:
        try:
            value = path.read_bytes().decode("utf-8", errors="ignore")
        except OSError:
            continue
        cleaned = re.sub(r"[^a-z0-9]", "", value.lower())
        if cleaned:
            return cleaned[-6:].rjust(6, "0")
    return f"{uuid.getnode():012x}"[-6:]


def device_id(config: StandaloneConfig) -> str:
    configured = config.satellite.device_id.strip()
    if configured and configured.lower() != "auto":
        return configured
    return f"tater-sat1-{hardware_suffix()}"


def display_name(config: StandaloneConfig) -> str:
    override = _read_override(config.runtime.satellite_name_path)
    if override:
        return override
    configured = config.satellite.name.strip()
    if configured and configured.lower() != "auto":
        return configured
    suffix = device_id(config).rsplit("-", 1)[-1].upper()
    return f"Tater SAT1 {suffix}"


def room_name(config: StandaloneConfig) -> str:
    try:
        return config.runtime.satellite_room_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return config.satellite.room.strip()


def _read_override(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def hostname(config: StandaloneConfig) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", device_id(config).lower()).strip("-")
    return (normalized or "tater-sat1")[:63].rstrip("-")
