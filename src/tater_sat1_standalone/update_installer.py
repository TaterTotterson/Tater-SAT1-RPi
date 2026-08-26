from __future__ import annotations

import argparse
from dataclasses import dataclass
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
import tomllib
from typing import Any, BinaryIO


BUNDLE_KIND = "tater_sat1_ota"
BUNDLE_SCHEMA = 1
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")

COMMON_DIRECTORIES = ("opt/tater-sat1",)
FLAVOR_DIRECTORIES = {"standalone": ("opt/tater",), "satellite": ()}
COMMON_FILES = (
    "etc/systemd/system/tater-sat1-audio.service",
    "etc/systemd/system/tater-sat1-firstboot.service",
    "etc/systemd/system/tater-sat1-provisioning.service",
    "etc/tater-sat1-standalone/version",
    "usr/local/sbin/tater-sat1-firstboot",
    "usr/local/sbin/tater-sat1-setup-hotspot",
)
FLAVOR_FILES = {
    "standalone": (
        "etc/systemd/system/tater-sat1-tater.service",
        "etc/systemd/system/tater-sat1-voice.service",
    ),
    "satellite": (
        "etc/systemd/system/tater-sat1-satellite.service",
        "usr/local/bin/tater-sat1-pair",
    ),
}


@dataclass(frozen=True)
class Layout:
    root: Path = Path("/")

    def path(self, absolute: str) -> Path:
        value = Path(absolute)
        if not value.is_absolute():
            raise ValueError(f"managed path must be absolute: {absolute}")
        return self.root / value.relative_to("/")

    @property
    def state_dir(self) -> Path:
        return self.path("/var/lib/tater-sat1-standalone")

    @property
    def update_dir(self) -> Path:
        return self.state_dir / "updates"

    @property
    def pending_bundle(self) -> Path:
        return self.update_dir / "pending.sat1-ota"

    @property
    def public_key(self) -> Path:
        return self.path("/etc/tater-sat1-standalone/update-public.pem")

    @property
    def config(self) -> Path:
        return self.path("/etc/tater-sat1-standalone/config.toml")

    @property
    def version(self) -> Path:
        return self.path("/etc/tater-sat1-standalone/version")

    @property
    def rollback_dir(self) -> Path:
        return self.update_dir / "rollback-current"

    @property
    def health_marker(self) -> Path:
        return self.update_dir / "health-pending.json"

    @property
    def lock(self) -> Path:
        return self.update_dir / "update.lock"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_flavor(config_path: Path) -> str:
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    flavor = str(runtime.get("flavor") or "").strip().lower()
    if flavor not in {"standalone", "satellite"}:
        raise ValueError("installed SAT1 flavor is missing or invalid")
    return flavor


def managed_directories(flavor: str) -> tuple[str, ...]:
    return COMMON_DIRECTORIES + FLAVOR_DIRECTORIES[flavor]


def managed_files(flavor: str) -> tuple[str, ...]:
    return COMMON_FILES + FLAVOR_FILES[flavor]


def _copy_stream(source: BinaryIO, destination: Path, maximum: int, *, durable: bool = False) -> int:
    total = 0
    with destination.open("wb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise ValueError(f"archive member exceeds {maximum} bytes")
            output.write(chunk)
        output.flush()
        if durable:
            os.fsync(output.fileno())
    return total


def _extract_bundle_members(bundle: Path, destination: Path) -> tuple[Path, Path, Path]:
    expected = {"manifest.json", "manifest.sig", "payload.tar.xz"}
    found: set[str] = set()
    with tarfile.open(bundle, "r:*") as archive:
        for member in archive.getmembers():
            if member.name not in expected or not member.isfile() or member.name in found:
                raise ValueError(f"unexpected OTA container member: {member.name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"could not read OTA container member: {member.name}")
            maximum = MAX_PAYLOAD_BYTES if member.name == "payload.tar.xz" else 1024 * 1024
            _copy_stream(extracted, destination / member.name, maximum)
            found.add(member.name)
    if found != expected:
        raise ValueError("OTA container is missing required members")
    return destination / "manifest.json", destination / "manifest.sig", destination / "payload.tar.xz"


def _verify_signature(manifest: Path, signature: Path, public_key: Path) -> None:
    if not public_key.is_file():
        raise ValueError(f"SAT1 OTA public key is missing: {public_key}")
    completed = subprocess.run(
        [
            "openssl",
            "dgst",
            "-sha256",
            "-verify",
            str(public_key),
            "-signature",
            str(signature),
            str(manifest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("OTA manifest signature verification failed")


def _load_manifest(path: Path, expected_flavor: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("OTA manifest is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("OTA manifest must be a JSON object")
    if payload.get("schema") != BUNDLE_SCHEMA or payload.get("kind") != BUNDLE_KIND:
        raise ValueError("OTA manifest kind or schema is unsupported")
    if str(payload.get("product") or "") != "tater-sat1-rpi":
        raise ValueError("OTA bundle targets a different product")
    flavor = str(payload.get("flavor") or "").strip().lower()
    if flavor != expected_flavor:
        raise ValueError(f"OTA bundle flavor {flavor or 'unknown'} does not match installed {expected_flavor}")
    version = str(payload.get("version") or "").strip()
    if not _VERSION.fullmatch(version):
        raise ValueError("OTA manifest version is invalid")
    artifact = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    if artifact.get("path") != "payload.tar.xz":
        raise ValueError("OTA manifest payload path is invalid")
    digest = str(artifact.get("sha256") or "").strip().lower()
    if not _SHA256.fullmatch(digest):
        raise ValueError("OTA payload SHA-256 is invalid")
    try:
        size = int(artifact.get("size_bytes"))
    except (TypeError, ValueError) as exc:
        raise ValueError("OTA payload size is invalid") from exc
    if size < 1 or size > MAX_PAYLOAD_BYTES:
        raise ValueError("OTA payload size is outside the supported range")
    return payload


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe OTA payload path: {name}")
    if path.parts[0] not in {"opt", "etc", "usr"}:
        raise ValueError(f"OTA payload path is outside the immutable appliance roots: {name}")
    return path


def _safe_extract_payload(payload: Path, destination: Path) -> None:
    with tarfile.open(payload, "r:xz") as archive:
        members = archive.getmembers()
        paths = {_safe_member_path(member.name): member for member in members}
        symlink_paths = {path for path, member in paths.items() if member.issym()}
        for path, member in paths.items():
            if member.ischr() or member.isblk() or member.isfifo() or member.isdev():
                raise ValueError(f"unsupported special file in OTA payload: {member.name}")
            for parent in path.parents:
                if parent in symlink_paths:
                    raise ValueError(f"OTA payload writes through a symlink: {member.name}")

        directories = [(path, member) for path, member in paths.items() if member.isdir()]
        regular = [(path, member) for path, member in paths.items() if member.isfile()]
        symlinks = [(path, member) for path, member in paths.items() if member.issym()]
        hardlinks = [(path, member) for path, member in paths.items() if member.islnk()]
        supported = len(directories) + len(regular) + len(symlinks) + len(hardlinks)
        if supported != len(members):
            raise ValueError("OTA payload contains an unsupported tar member")

        for path, _member in sorted(directories, key=lambda item: len(item[0].parts)):
            (destination / Path(*path.parts)).mkdir(parents=True, exist_ok=True)
        for path, member in regular:
            target = destination / Path(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"could not read OTA payload member: {member.name}")
            _copy_stream(source, target, MAX_PAYLOAD_BYTES)
            os.chmod(target, stat.S_IMODE(member.mode))
        for path, member in symlinks:
            target = destination / Path(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(member.linkname)
        for path, member in hardlinks:
            source_path = _safe_member_path(member.linkname)
            source = destination / Path(*source_path.parts)
            target = destination / Path(*path.parts)
            if not source.is_file():
                raise ValueError(f"OTA hard-link target is missing: {member.linkname}")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target)
        for path, member in sorted(directories, key=lambda item: len(item[0].parts), reverse=True):
            os.chmod(destination / Path(*path.parts), stat.S_IMODE(member.mode))


def verify_bundle_archive(
    bundle: Path, public_key: Path, expected_flavor: str, work_dir: Path
) -> tuple[dict[str, Any], Path]:
    container = work_dir / "container"
    container.mkdir(parents=True)
    manifest_path, signature_path, payload_path = _extract_bundle_members(bundle, container)
    _verify_signature(manifest_path, signature_path, public_key)
    manifest = _load_manifest(manifest_path, expected_flavor)
    artifact = manifest["payload"]
    if payload_path.stat().st_size != int(artifact["size_bytes"]):
        raise ValueError("OTA payload size does not match its signed manifest")
    if sha256_file(payload_path) != str(artifact["sha256"]):
        raise ValueError("OTA payload SHA-256 does not match its signed manifest")
    return manifest, payload_path


def verify_bundle(bundle: Path, public_key: Path, expected_flavor: str, work_dir: Path) -> tuple[dict[str, Any], Path]:
    manifest, payload_path = verify_bundle_archive(bundle, public_key, expected_flavor, work_dir)
    payload_root = work_dir / "payload-root"
    payload_root.mkdir(parents=True)
    _safe_extract_payload(payload_path, payload_root)
    validate_payload(payload_root, expected_flavor, str(manifest["version"]))
    return manifest, payload_root


def validate_payload(payload_root: Path, flavor: str, version: str) -> None:
    for relative in managed_directories(flavor):
        if not (payload_root / relative).is_dir():
            raise ValueError(f"OTA payload is missing directory: /{relative}")
    for relative in managed_files(flavor):
        if not (payload_root / relative).is_file():
            raise ValueError(f"OTA payload is missing file: /{relative}")
    installed_version = (payload_root / "etc/tater-sat1-standalone/version").read_text(encoding="utf-8").strip()
    if installed_version != version:
        raise ValueError("OTA payload version file does not match its signed manifest")
    executable = payload_root / "opt/tater-sat1/venv/bin/tater-sat1-voice"
    if not executable.is_file():
        raise ValueError("OTA payload is missing the SAT1 voice launcher")
    if flavor == "standalone" and not (payload_root / "opt/tater/app/tateros_app.py").is_file():
        raise ValueError("standalone OTA payload is missing Tater")
    if flavor == "satellite" and (payload_root / "opt/tater").exists():
        raise ValueError("satellite-only OTA payload unexpectedly contains Tater")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _service_names(flavor: str) -> tuple[str, ...]:
    if flavor == "standalone":
        return ("tater-sat1-voice.service", "tater-sat1-tater.service", "tater-sat1-audio.service")
    return ("tater-sat1-satellite.service", "tater-sat1-audio.service")


def _systemctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    if os.getenv("TATER_SAT1_UPDATE_NO_SYSTEMD") == "1":
        return subprocess.CompletedProcess(["systemctl", *arguments], 0, "", "")
    return subprocess.run(["systemctl", *arguments], check=check, text=True, capture_output=not check)


def restore_backup(layout: Layout) -> bool:
    metadata_path = layout.rollback_dir / "metadata.json"
    if not metadata_path.is_file():
        return False
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    flavor = str(metadata.get("flavor") or "")
    if flavor not in {"standalone", "satellite"}:
        raise ValueError("rollback metadata flavor is invalid")
    backup_root = layout.rollback_dir / "rootfs"
    for relative in managed_directories(flavor):
        destination = layout.root / relative
        backup = backup_root / relative
        if backup.exists():
            _remove_path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, destination)
    previous_files = set(metadata.get("previous_files") or [])
    for relative in managed_files(flavor):
        destination = layout.root / relative
        backup = backup_root / relative
        if relative in previous_files and backup.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, destination)
        else:
            destination.unlink(missing_ok=True)
    layout.health_marker.unlink(missing_ok=True)
    _systemctl("daemon-reload", check=False)
    return True


def apply_pending(layout: Layout) -> dict[str, Any]:
    if os.geteuid() != 0 and layout.root == Path("/"):
        raise PermissionError("the SAT1 update installer must run as root")
    flavor = read_flavor(layout.config)
    layout.update_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(layout.update_dir, 0o700)
    if not layout.pending_bundle.is_file():
        raise FileNotFoundError(f"pending SAT1 OTA bundle not found: {layout.pending_bundle}")
    layout.lock.touch(mode=0o600, exist_ok=True)
    with layout.lock.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix="verify-", dir=layout.update_dir) as temporary:
            work_dir = Path(temporary)
            manifest, payload_root = verify_bundle(layout.pending_bundle, layout.public_key, flavor, work_dir)
            version = str(manifest["version"])
            previous_version = layout.version.read_text(encoding="utf-8").strip() if layout.version.is_file() else ""

            _remove_path(layout.rollback_dir)
            backup_root = layout.rollback_dir / "rootfs"
            backup_root.mkdir(parents=True)
            previous_files: list[str] = []
            for relative in managed_files(flavor):
                current = layout.root / relative
                if current.is_file():
                    backup = backup_root / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(current, backup)
                    previous_files.append(relative)
            metadata = {
                "schema": 1,
                "flavor": flavor,
                "previous_version": previous_version,
                "version": version,
                "previous_files": previous_files,
            }
            _write_json_atomic(layout.rollback_dir / "metadata.json", metadata)
            _write_json_atomic(layout.health_marker, {**metadata, "phase": "applying"})

            services = _service_names(flavor)
            try:
                _systemctl("stop", *services, check=False)
                for relative in managed_directories(flavor):
                    current = layout.root / relative
                    backup = backup_root / relative
                    if current.exists():
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(current, backup)
                    replacement = payload_root / relative
                    current.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(replacement, current)
                for relative in managed_files(flavor):
                    source = payload_root / relative
                    destination = layout.root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                shutil.move(str(layout.pending_bundle), str(layout.rollback_dir / "applied.sat1-ota"))
                _write_json_atomic(layout.health_marker, {**metadata, "phase": "pending_health"})
                _systemctl("daemon-reload")
                _systemctl("enable", "tater-sat1-update.path", "tater-sat1-update-health.service")
                os.sync()
            except Exception:
                restore_backup(layout)
                _systemctl("start", *services, check=False)
                raise

    if os.getenv("TATER_SAT1_UPDATE_NO_REBOOT") != "1":
        subprocess.run(["systemctl", "reboot"], check=True)
    return {"ok": True, "flavor": flavor, "version": version, "rebooting": True}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify and install a signed Tater SAT1 OTA bundle")
    parser.add_argument("--verify", type=Path, help="verify a bundle without installing it")
    parser.add_argument("--flavor", choices=("standalone", "satellite"), help="expected flavor for --verify")
    parser.add_argument("--public-key", type=Path, help="public key for --verify")
    parser.add_argument("--root", type=Path, default=Path(os.getenv("TATER_SAT1_UPDATE_ROOT", "/")))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    layout = Layout(args.root)
    if args.verify:
        if not args.flavor:
            raise SystemExit("--verify requires --flavor")
        public_key = args.public_key or layout.public_key
        with tempfile.TemporaryDirectory(prefix="tater-sat1-verify-") as temporary:
            manifest, _payload = verify_bundle(args.verify, public_key, args.flavor, Path(temporary))
        print(json.dumps({"ok": True, "flavor": args.flavor, "version": manifest["version"]}, sort_keys=True))
        return 0
    result = apply_pending(layout)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
