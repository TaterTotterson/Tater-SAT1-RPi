from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import time
import tempfile
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import uuid

from .update_installer import verify_bundle_archive


MAX_UPDATE_BYTES = 2 * 1024 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HTTP_SCHEMES = {"http", "https"}


def validate_update_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _HTTP_SCHEMES or not parsed.netloc:
        raise ValueError("update URL must use HTTP or HTTPS")
    return url


def validate_update_integrity(sha256: Any, size_bytes: Any) -> tuple[str, int]:
    digest = str(sha256 or "").strip().lower()
    if not _SHA256.fullmatch(digest):
        raise ValueError("update SHA-256 must contain exactly 64 hexadecimal characters")
    try:
        size = int(size_bytes)
    except (TypeError, ValueError) as exc:
        raise ValueError("update size is invalid") from exc
    if size < 1 or size > MAX_UPDATE_BYTES:
        raise ValueError("update size is outside the supported SAT1 range")
    return digest, size


def download_update(
    url: str,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int,
    progress: Callable[[int, int], None] | None = None,
) -> str:
    validated_url = validate_update_url(url)
    digest_text, size = validate_update_integrity(expected_sha256, expected_size)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    digest = hashlib.sha256()
    received = 0
    request = Request(validated_url, headers={"User-Agent": "Tater-SAT1/1.0"})
    try:
        with urlopen(request, timeout=90) as response, temporary.open("wb") as output:
            validate_update_url(response.geturl())
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length and content_length != size:
                raise ValueError("update Content-Length does not match the release manifest")
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > size or received > MAX_UPDATE_BYTES:
                    raise ValueError("downloaded update is larger than the release manifest")
                output.write(chunk)
                digest.update(chunk)
                if progress is not None:
                    progress(received, size)
            output.flush()
            os.fsync(output.fileno())
        actual = digest.hexdigest()
        if received != size:
            raise ValueError("downloaded update size does not match the release manifest")
        if actual != digest_text:
            raise ValueError("downloaded update SHA-256 does not match the release manifest")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        return actual
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _frame(message_type: str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "v": 1,
            "type": message_type,
            "id": uuid.uuid4().hex,
            "ts": time.time(),
            "payload": payload,
        },
        separators=(",", ":"),
    )


class NativeOtaController:
    """Stage signed SAT1 update bundles received through Tater's native API."""

    def __init__(self, client: Any, state_dir: Path, flavor: str, public_key: Path) -> None:
        self.client = client
        self.update_dir = state_dir / "updates"
        if flavor not in {"standalone", "satellite"}:
            raise ValueError(f"unsupported SAT1 OTA flavor: {flavor}")
        self.flavor = flavor
        self.public_key = public_key
        self.task: asyncio.Task[None] | None = None
        self._last_progress = -1

    def _send(self, status: str, progress: int, message: str) -> None:
        self.client._submit_frame(  # pylint: disable=protected-access
            _frame(
                "ota.status",
                {
                    "status": status,
                    "progress": max(0, min(100, int(progress))),
                    "message": message,
                },
            )
        )

    def handle_message(self, body: dict[str, Any]) -> bool:
        if str(body.get("type") or "").strip() != "ota.url":
            return False
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        if self.task is not None and not self.task.done():
            self._send("error", 0, "An update is already running.")
            return True
        self.task = asyncio.create_task(self._run(dict(payload)))
        return True

    async def _run(self, payload: dict[str, Any]) -> None:
        staged = self.update_dir / "staged.sat1-ota"
        pending = self.update_dir / "pending.sat1-ota"
        try:
            if pending.exists():
                raise RuntimeError("A verified update is already waiting to install.")
            url = validate_update_url(payload.get("url"))
            expected_sha256, expected_size = validate_update_integrity(
                payload.get("sha256"), payload.get("size_bytes")
            )
            self._send("downloading", 0, "Downloading signed SAT1 appliance update.")
            loop = asyncio.get_running_loop()

            def report(received: int, total: int) -> None:
                percent = min(85, int((received * 85) / max(1, total)))
                if percent <= self._last_progress:
                    return
                self._last_progress = percent
                loop.call_soon_threadsafe(
                    self._send,
                    "downloading",
                    percent,
                    f"Downloaded {received} of {total} bytes.",
                )

            digest = await asyncio.to_thread(
                download_update,
                url,
                staged,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
                progress=report,
            )
            self._send("verifying", 88, "Verifying the SAT1 release signature.")

            def verify_staged() -> None:
                with tempfile.TemporaryDirectory(prefix="tater-sat1-ota-") as temporary:
                    verify_bundle_archive(staged, self.public_key, self.flavor, Path(temporary))

            await asyncio.to_thread(verify_staged)
            self._send(
                "rebooting",
                92,
                f"Verified update {digest[:12]}; installing with automatic rollback.",
            )
            await asyncio.sleep(0.5)
            os.replace(staged, pending)
            os.sync()
        except asyncio.CancelledError:
            staged.unlink(missing_ok=True)
            raise
        except Exception as exc:  # pylint: disable=broad-except
            staged.unlink(missing_ok=True)
            self._send("error", 0, str(exc).strip() or exc.__class__.__name__)

    async def close(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
