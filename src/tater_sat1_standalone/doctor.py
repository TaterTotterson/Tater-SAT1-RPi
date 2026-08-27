from __future__ import annotations

from dataclasses import dataclass
import platform
from pathlib import Path

from .config import StandaloneConfig
from .provisioning import effective_server_url


@dataclass(frozen=True)
class Check:
    level: str
    label: str
    detail: str


def inspect_host(config: StandaloneConfig) -> list[Check]:
    checks: list[Check] = []
    machine = platform.machine().lower()
    checks.append(Check("ok" if machine in {"aarch64", "arm64"} else "warn", "architecture", machine))

    memory_mb = _memory_total_mb()
    if memory_mb is None:
        checks.append(Check("warn", "memory", "unable to read /proc/meminfo"))
    elif memory_mb < 400:
        checks.append(Check("error", "memory", f"{memory_mb} MB detected; at least 400 MB is required"))
    elif memory_mb < 900:
        checks.append(Check("warn", "memory", f"{memory_mb} MB detected; edge profile and zram are required"))
    else:
        checks.append(Check("ok", "memory", f"{memory_mb} MB detected"))

    if config.runtime.flavor == "standalone":
        checks.extend(
            (
                _path_check(config.runtime.tater_python, executable=True, label="Tater Python"),
                _path_check(config.runtime.tater_app_dir / "tateros_app.py", label="Tater app"),
            )
        )
    else:
        checks.append(Check("ok", "Tater server", effective_server_url(config)))
    checks.append(_path_check(config.runtime.satellite_executable, executable=True, label="satellite runtime"))
    if config.leds.enabled:
        checks.append(
            _path_check(
                config.runtime.satellite_executable.parent / "tater-sat1-leds",
                executable=True,
                label="LED runtime",
            )
        )
    return checks


def _path_check(path: Path, *, executable: bool = False, label: str) -> Check:
    if not path.exists():
        return Check("error", label, f"missing: {path}")
    if executable and not path.is_file():
        return Check("error", label, f"not a file: {path}")
    if executable and path.stat().st_mode & 0o111 == 0:
        return Check("error", label, f"not executable: {path}")
    return Check("ok", label, str(path))


def _memory_total_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None
