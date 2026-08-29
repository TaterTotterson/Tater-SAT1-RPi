from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .tater_source import prepare
from .update_installer import _systemctl, read_flavor


DEFAULT_REPOSITORY = "TaterTotterson/Tater"
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_EXTRACTED_BYTES = 768 * 1024 * 1024
MIN_FREE_BYTES = 512 * 1024 * 1024
TRUSTED_DOWNLOAD_HOSTS = {"api.github.com", "codeload.github.com", "github.com"}
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class Release:
    tag: str
    published_at: str
    tarball_url: str
    commit: str


@dataclass(frozen=True)
class AppLayout:
    root: Path = Path("/")

    def path(self, absolute: str) -> Path:
        value = Path(absolute)
        if not value.is_absolute():
            raise ValueError(f"managed path must be absolute: {absolute}")
        return self.root / value.relative_to("/")

    @property
    def config(self) -> Path:
        return self.path("/etc/tater-sat1-standalone/config.toml")

    @property
    def app_root(self) -> Path:
        return self.path("/opt/tater")

    @property
    def release_root(self) -> Path:
        return self.path("/opt/tater-app-releases")

    @property
    def state_dir(self) -> Path:
        return self.path("/var/lib/tater-sat1-standalone")

    @property
    def update_dir(self) -> Path:
        return self.state_dir / "tater-app-updates"

    @property
    def status(self) -> Path:
        return self.update_dir / "status.json"

    @property
    def app_lock(self) -> Path:
        return self.update_dir / "app-update.lock"

    @property
    def appliance_lock(self) -> Path:
        return self.state_dir / "updates" / "update.lock"

    @property
    def pending_appliance_update(self) -> Path:
        return self.state_dir / "updates" / "pending.sat1-ota"

    @property
    def appliance_health_marker(self) -> Path:
        return self.state_dir / "updates" / "health-pending.json"


def _enabled(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_status(layout: AppLayout, **values: Any) -> dict[str, Any]:
    payload = {"schema": 1, "timestamp": _utc_now(), **values}
    layout.update_dir.mkdir(parents=True, exist_ok=True)
    temporary = layout.status.with_name(f".{layout.status.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, layout.status)
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def installed_metadata(layout: AppLayout) -> dict[str, Any]:
    return _read_json(layout.app_root / "app" / ".tater-sat1-build.json")


def _api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Tater-SAT1-RPi-release-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("TATER_APP_GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_json(url: str) -> dict[str, Any]:
    request = Request(url, headers=_api_headers())
    try:
        with urlopen(request, timeout=20) as response:
            if int(response.status) != 200:
                raise RuntimeError(f"GitHub returned HTTP {response.status}")
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read the Tater release feed: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("the Tater release feed did not return a JSON object")
    return payload


def _repository(value: str) -> str:
    repository = value.strip()
    if not _REPOSITORY.fullmatch(repository):
        raise ValueError("Tater update repository must use the owner/repository form")
    return repository


def _validate_download_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() not in TRUSTED_DOWNLOAD_HOSTS:
        raise ValueError("Tater release archive must use a trusted GitHub HTTPS URL")
    return value


def _resolve_tag_commit(repository: str, tag: str) -> str:
    encoded_tag = quote(tag, safe="")
    payload = _request_json(f"https://api.github.com/repos/{repository}/git/ref/tags/{encoded_tag}")
    target = payload.get("object") if isinstance(payload.get("object"), dict) else {}
    for _attempt in range(5):
        object_type = str(target.get("type") or "")
        sha = str(target.get("sha") or "").lower()
        if not _COMMIT.fullmatch(sha):
            raise RuntimeError("the Tater release tag did not resolve to a Git commit")
        if object_type == "commit":
            return sha
        if object_type != "tag":
            raise RuntimeError(f"the Tater release tag points to unsupported object type {object_type!r}")
        payload = _request_json(f"https://api.github.com/repos/{repository}/git/tags/{sha}")
        target = payload.get("object") if isinstance(payload.get("object"), dict) else {}
    raise RuntimeError("the Tater release tag has too many nested annotated tags")


def latest_release(repository: str) -> Release:
    repository = _repository(repository)
    payload = _request_json(f"https://api.github.com/repos/{repository}/releases/latest")
    if bool(payload.get("draft")) or bool(payload.get("prerelease")):
        raise RuntimeError("GitHub's latest Tater release is not a stable published release")
    tag = str(payload.get("tag_name") or "").strip()
    published_at = str(payload.get("published_at") or "").strip()
    tarball_url = _validate_download_url(str(payload.get("tarball_url") or "").strip())
    if not tag or len(tag) > 128 or any(character in tag for character in ("\x00", "\n", "\r")):
        raise RuntimeError("the latest Tater release has an invalid tag")
    if not published_at:
        raise RuntimeError("the latest Tater release is missing its publication time")
    return Release(tag, published_at, tarball_url, _resolve_tag_commit(repository, tag))


def _compare_status(repository: str, base: str, head: str) -> str:
    if not (_COMMIT.fullmatch(base) and _COMMIT.fullmatch(head)):
        return "unknown"
    payload = _request_json(f"https://api.github.com/repos/{repository}/compare/{base}...{head}")
    return str(payload.get("status") or "unknown").strip().lower()


def update_needed(repository: str, release: Release, metadata: dict[str, Any]) -> tuple[bool, str]:
    installed_tag = str(metadata.get("tater_release_tag") or "").strip()
    installed_commit = str(metadata.get("tater_reference_revision") or "").strip().lower()
    installed_published_at = str(metadata.get("tater_release_published_at") or "").strip()
    if installed_tag == release.tag or installed_commit == release.commit:
        return False, "already_current"
    if installed_tag and installed_published_at and installed_published_at >= release.published_at:
        return False, "installed_release_is_newer"
    if not installed_tag and _COMMIT.fullmatch(installed_commit):
        comparison = _compare_status(repository, release.commit, installed_commit)
        if comparison in {"ahead", "identical"}:
            return False, "bundled_tater_is_at_or_ahead_of_release"
    return True, "new_release"


def _copy_limited(source: BinaryIO, destination: Path, maximum: int) -> int:
    total = 0
    with destination.open("wb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise ValueError(f"Tater release archive exceeds {maximum} bytes")
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    return total


def _download_release(release: Release, destination: Path) -> None:
    request = Request(release.tarball_url, headers=_api_headers())
    try:
        with urlopen(request, timeout=60) as response:
            _validate_download_url(response.geturl())
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_ARCHIVE_BYTES:
                raise ValueError("Tater release archive is too large")
            _copy_limited(response, destination, MAX_ARCHIVE_BYTES)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"could not download Tater release {release.tag}: {exc}") from exc


def _archive_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe Tater release archive path: {name}")
    if len(path.parts) == 1:
        return PurePosixPath()
    return PurePosixPath(*path.parts[1:])


def _extract_release(archive_path: Path, destination: Path) -> None:
    total = 0
    destination.mkdir(parents=True)
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive.getmembers():
            relative = _archive_path(member.name)
            if not relative.parts:
                continue
            target = destination / Path(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(f"unsupported entry in Tater release archive: {member.name}")
            total += int(member.size)
            if total > MAX_EXTRACTED_BYTES:
                raise ValueError("Tater release expands beyond the supported size")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"could not read Tater release archive member: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_limited(source, target, min(MAX_EXTRACTED_BYTES, int(member.size) + 1))
            os.chmod(target, stat.S_IMODE(member.mode) & 0o777)
    if not (destination / "setup_tater.sh").is_file():
        raise ValueError("Tater release archive is missing setup_tater.sh")


def _slot_name(release: Release) -> str:
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", release.tag).strip("-.")[:64] or "release"
    return f"{readable}-{release.commit[:12]}"


def _setup_release(layout: AppLayout, release: Release) -> Path:
    layout.release_root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(layout.release_root).free < MIN_FREE_BYTES:
        raise RuntimeError("not enough free storage to stage a safe Tater update")
    slot = layout.release_root / _slot_name(release)
    if slot.exists():
        metadata = _read_json(slot / "app" / ".tater-sat1-build.json")
        if (
            str(metadata.get("tater_reference_revision") or "") == release.commit
            and (slot / "venv/bin/python").is_file()
        ):
            return slot
        shutil.rmtree(slot)
    slot.mkdir(mode=0o755)
    try:
        with tempfile.TemporaryDirectory(prefix="release-", dir=layout.update_dir) as temporary:
            workspace = Path(temporary)
            archive_path = workspace / "tater-release.tar.gz"
            extracted = workspace / "source"
            _download_release(release, archive_path)
            _extract_release(archive_path, extracted)
            prepare(
                extracted,
                slot / "app",
                release.commit,
                release_tag=release.tag,
                release_published_at=release.published_at,
            )

        environment = os.environ.copy()
        environment.update(
            {
                "TATER_VENV_DIR": str(slot / "venv"),
                "TATER_RUNTIME_DIR": str(layout.state_dir / "tater-runtime"),
                "TATER_AGENT_ROOT": str(layout.state_dir / "agent-lab"),
                "TATER_SETUP_INSTALL_SYSTEM_DEPS": "0",
                "TATER_SETUP_LLAMA_CPP_NATIVE": "0",
                "TATER_SETUP_REQUIRE_LOCAL_LLM": "0",
            }
        )
        if os.getenv("TATER_SAT1_APP_UPDATE_SKIP_SETUP") == "1":
            (slot / "venv/bin").mkdir(parents=True, exist_ok=True)
            (slot / "venv/bin/python").write_text("#!/bin/sh\n", encoding="utf-8")
            os.chmod(slot / "venv/bin/python", 0o755)
        else:
            subprocess.run(
                ["sh", "setup_tater.sh", "edge"],
                cwd=slot / "app",
                env=environment,
                check=True,
            )
            subprocess.run(
                [str(slot / "venv/bin/python"), "-m", "pip", "install", "websockets>=12,<16"],
                check=True,
            )
            subprocess.run(
                [str(slot / "venv/bin/python"), "-c", "import fastapi, redis, uvicorn, websockets"],
                cwd=slot / "app",
                env=environment,
                check=True,
            )
            if layout.root == Path("/"):
                subprocess.run(["chown", "-R", "tater:tater", str(layout.state_dir)], check=True)
        return slot
    except Exception:
        shutil.rmtree(slot, ignore_errors=True)
        raise


def _resolved_link(path: Path) -> Path:
    target = Path(os.readlink(path))
    return target if target.is_absolute() else (path.parent / target).resolve()


def _replace_link(path: Path, target: Path) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.new")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, path)


def _bundled_slot(layout: AppLayout) -> Path:
    metadata = installed_metadata(layout)
    revision = str(metadata.get("tater_reference_revision") or "bundled")
    suffix = hashlib.sha256(revision.encode("utf-8")).hexdigest()[:12]
    return layout.release_root / f"bundled-{suffix}"


def _activate(layout: AppLayout, slot: Path) -> Path:
    if layout.app_root.is_symlink():
        previous = _resolved_link(layout.app_root)
    elif layout.app_root.is_dir():
        previous = _bundled_slot(layout)
        if previous.exists():
            shutil.rmtree(previous)
        os.replace(layout.app_root, previous)
    else:
        raise RuntimeError("the installed Tater application root is missing")
    _replace_link(layout.app_root, slot)
    return previous


def _healthy() -> bool:
    if os.getenv("TATER_SAT1_APP_UPDATE_SKIP_HTTP_HEALTH") == "1":
        return True
    attempts = max(1, int(os.getenv("TATER_SAT1_APP_UPDATE_HEALTH_ATTEMPTS", "12")))
    interval = max(0, int(os.getenv("TATER_SAT1_APP_UPDATE_HEALTH_INTERVAL_SECONDS", "5")))
    for attempt in range(attempts):
        try:
            with urlopen("http://127.0.0.1:8501/api/health", timeout=5) as response:
                if 200 <= int(response.status) < 300:
                    return True
        except Exception:  # pylint: disable=broad-except
            pass
        if attempt + 1 < attempts and interval:
            time.sleep(interval)
    return False


def _switch_and_check(layout: AppLayout, slot: Path) -> Path:
    services = ("tater-sat1-voice.service", "tater-sat1-tater.service")
    _systemctl("stop", *services, check=False)
    previous = _activate(layout, slot)
    try:
        _systemctl("start", "tater-sat1-tater.service")
        if not _healthy():
            raise RuntimeError("the updated Tater release did not pass its local health check")
        _systemctl("start", "tater-sat1-voice.service")
        return previous
    except Exception:
        _systemctl("stop", *services, check=False)
        _replace_link(layout.app_root, previous)
        _systemctl("start", "tater-sat1-tater.service", check=False)
        _systemctl("start", "tater-sat1-voice.service", check=False)
        raise


def _clean_releases(layout: AppLayout, keep: set[Path]) -> None:
    resolved_keep = {path.resolve() for path in keep if path.exists()}
    if not layout.release_root.is_dir():
        return
    for candidate in layout.release_root.iterdir():
        if candidate.is_dir() and candidate.resolve() not in resolved_keep:
            shutil.rmtree(candidate, ignore_errors=True)


def run_update(
    layout: AppLayout,
    *,
    repository: str = DEFAULT_REPOSITORY,
    automatic: bool = False,
    check_only: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    if os.geteuid() != 0 and layout.root == Path("/") and not check_only:
        raise PermissionError("installing a Tater app update requires root")
    if read_flavor(layout.config) != "standalone":
        return _write_status(
            layout,
            ok=True,
            status="not_applicable",
            message="satellite-only image has no Tater app",
        )
    if automatic and not _enabled(os.getenv("TATER_APP_AUTO_UPDATE"), True):
        return _write_status(
            layout,
            ok=True,
            status="disabled",
            message="automatic Tater release updates are disabled",
        )

    layout.update_dir.mkdir(parents=True, exist_ok=True)
    layout.app_lock.touch(mode=0o600, exist_ok=True)
    with layout.app_lock.open("r+") as app_lock:
        try:
            fcntl.flock(app_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return _write_status(
                layout,
                ok=True,
                status="already_running",
                message="a Tater app check is already running",
            )
        if layout.pending_appliance_update.exists() or layout.appliance_health_marker.exists():
            return _write_status(
                layout,
                ok=True,
                status="firmware_update_pending",
                message="the signed SAT1 appliance update takes priority",
            )

        release = latest_release(repository)
        current = installed_metadata(layout)
        needed, reason = update_needed(repository, release, current)
        previous_status = _read_json(layout.status)
        if not force and str(previous_status.get("failed_release_tag") or "") == release.tag:
            return _write_status(
                layout,
                ok=True,
                status="waiting_for_new_release",
                release_tag=release.tag,
                message="this release previously failed health checks; waiting for a newer release",
                failed_release_tag=release.tag,
            )
        if not needed:
            return _write_status(
                layout,
                ok=True,
                status="current",
                release_tag=release.tag,
                installed_revision=str(current.get("tater_reference_revision") or ""),
                message=reason,
            )
        if check_only:
            return _write_status(
                layout,
                ok=True,
                status="update_available",
                release_tag=release.tag,
                release_revision=release.commit,
            )

        _write_status(
            layout,
            ok=True,
            status="staging",
            release_tag=release.tag,
            release_revision=release.commit,
        )
        slot = _setup_release(layout, release)
        layout.appliance_lock.parent.mkdir(parents=True, exist_ok=True)
        layout.appliance_lock.touch(mode=0o600, exist_ok=True)
        with layout.appliance_lock.open("r+") as appliance_lock:
            try:
                fcntl.flock(appliance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("a signed SAT1 appliance update is currently running") from exc
            if layout.pending_appliance_update.exists() or layout.appliance_health_marker.exists():
                return _write_status(
                    layout,
                    ok=True,
                    status="firmware_update_pending",
                    release_tag=release.tag,
                    message="the staged app release will wait because a signed SAT1 update takes priority",
                )
            try:
                previous = _switch_and_check(layout, slot)
            except Exception as exc:
                return _write_status(
                    layout,
                    ok=False,
                    status="rolled_back",
                    release_tag=release.tag,
                    failed_release_tag=release.tag,
                    message=str(exc),
                )

        _clean_releases(layout, {slot, previous})
        return _write_status(
            layout,
            ok=True,
            status="updated",
            release_tag=release.tag,
            release_revision=release.commit,
            previous_path=str(previous),
            message="Tater updated from an official stable release and passed its health check",
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update embedded Tater from its latest stable GitHub release")
    parser.add_argument("--root", type=Path, default=Path(os.getenv("TATER_SAT1_APP_UPDATE_ROOT", "/")))
    parser.add_argument("--repository", default=os.getenv("TATER_APP_UPDATE_REPOSITORY", DEFAULT_REPOSITORY))
    parser.add_argument("--automatic", action="store_true", help="honor TATER_APP_AUTO_UPDATE before installing")
    parser.add_argument("--check-only", action="store_true", help="report a newer release without installing it")
    parser.add_argument("--force", action="store_true", help="retry a release that previously failed health checks")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    layout = AppLayout(args.root)
    try:
        result = run_update(
            layout,
            repository=args.repository,
            automatic=args.automatic,
            check_only=args.check_only,
            force=args.force,
        )
    except Exception as exc:  # pylint: disable=broad-except
        result = _write_status(layout, ok=False, status="failed", message=str(exc))
        print(json.dumps(result, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
