from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Callable


TARGET_VERSION = "v1.1.1"
FIRMWARE_SHA256 = "8ab57bd9da5f114746fcbc3d25ea57b32ea3938c61ed4b545d5d93a3d410c0e5"
DEFAULT_FIRMWARE = Path("/opt/tater-sat1/firmware/xmos/sat1_xmos_1_1_1_factory.bin")
DEFAULT_TOOL = Path("/usr/bin/sat1-xmos")
_VERSION = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:-(?:alpha|beta|rc|dev)(?:\.[0-9]+)?)?$")

Runner = Callable[..., subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class EnsureResult:
    status: str
    installed_version: str
    target_version: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_version(output: str) -> str | None:
    for line in reversed(output.splitlines()):
        candidate = line.strip()
        if _VERSION.fullmatch(candidate):
            return candidate
    return None


def read_version(tool: Path, *, runner: Runner = subprocess.run) -> str | None:
    completed = runner(
        [str(tool), "read-firmware"],
        check=False,
        capture_output=True,
        text=True,
    )
    return parse_version(completed.stdout or "")


def wait_for_version(
    tool: Path,
    *,
    attempts: int,
    delay_seconds: float,
    runner: Runner = subprocess.run,
    sleeper: Sleeper = time.sleep,
) -> str | None:
    for attempt in range(max(1, attempts)):
        version = read_version(tool, runner=runner)
        if version:
            return version
        if attempt + 1 < attempts:
            sleeper(delay_seconds)
    return None


def ensure_xmos_firmware(
    firmware: Path = DEFAULT_FIRMWARE,
    *,
    expected_sha256: str = FIRMWARE_SHA256,
    target_version: str = TARGET_VERSION,
    tool: Path = DEFAULT_TOOL,
    initial_attempts: int = 12,
    verify_attempts: int = 40,
    delay_seconds: float = 0.25,
    runner: Runner = subprocess.run,
    sleeper: Sleeper = time.sleep,
) -> EnsureResult:
    if not _VERSION.fullmatch(target_version):
        raise ValueError(f"invalid XMOS target version: {target_version}")
    if not firmware.is_file():
        raise FileNotFoundError(f"XMOS factory image is missing: {firmware}")
    actual_sha256 = sha256_file(firmware)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"XMOS factory image checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    if not tool.is_file():
        raise FileNotFoundError(f"Satellite1 XMOS utility is missing: {tool}")

    installed = wait_for_version(
        tool,
        attempts=initial_attempts,
        delay_seconds=delay_seconds,
        runner=runner,
        sleeper=sleeper,
    )
    if installed == target_version:
        return EnsureResult("unchanged", installed, target_version)

    print(f"SAT1 XMOS update required: installed={installed or 'unavailable'} target={target_version}", flush=True)
    try:
        # The v0.1.4 SDK's flash command returns status 1 even after a
        # successful write, so the authoritative result is the version read
        # after its flashrom write-and-verify pass.
        runner(
            [str(tool), "-v", "flash-firmware", str(firmware), "--verify"],
            check=False,
        )
    finally:
        # Always release reset if flashrom or its wrapper fails partway.
        runner([str(tool), "disable-flashing"], check=False)

    installed = wait_for_version(
        tool,
        attempts=verify_attempts,
        delay_seconds=delay_seconds,
        runner=runner,
        sleeper=sleeper,
    )
    if installed != target_version:
        raise RuntimeError(
            f"XMOS firmware verification failed: expected {target_version}, got {installed or 'unavailable'}"
        )
    return EnsureResult("updated", installed, target_version)


def ensure_xmos_firmware_once(
    marker: Path,
    firmware: Path = DEFAULT_FIRMWARE,
    *,
    expected_sha256: str = FIRMWARE_SHA256,
    target_version: str = TARGET_VERSION,
    tool: Path = DEFAULT_TOOL,
    runner: Runner = subprocess.run,
    sleeper: Sleeper = time.sleep,
) -> EnsureResult:
    try:
        cached = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        cached = {}
    if (
        isinstance(cached, dict)
        and cached.get("target_version") == target_version
        and cached.get("firmware_sha256") == expected_sha256
    ):
        return EnsureResult("already_verified_this_boot", target_version, target_version)

    result = ensure_xmos_firmware(
        firmware,
        expected_sha256=expected_sha256,
        target_version=target_version,
        tool=tool,
        runner=runner,
        sleeper=sleeper,
    )
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_name(f".{marker.name}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "firmware_sha256": expected_sha256,
                "installed_version": result.installed_version,
                "target_version": target_version,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(marker)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify and update the Satellite1 XMOS audio firmware")
    parser.add_argument("--image", type=Path, default=DEFAULT_FIRMWARE)
    parser.add_argument("--expected-sha256", default=FIRMWARE_SHA256)
    parser.add_argument("--target-version", default=TARGET_VERSION)
    parser.add_argument("--tool", type=Path, default=DEFAULT_TOOL)
    parser.add_argument(
        "--once-marker",
        type=Path,
        help="skip a repeated SPI check after this boot marker records the same verified firmware",
    )
    args = parser.parse_args(argv)
    options = {
        "expected_sha256": args.expected_sha256.strip().lower(),
        "target_version": args.target_version.strip(),
        "tool": args.tool,
    }
    if args.once_marker:
        result = ensure_xmos_firmware_once(args.once_marker, args.image, **options)
    else:
        result = ensure_xmos_firmware(args.image, **options)
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
