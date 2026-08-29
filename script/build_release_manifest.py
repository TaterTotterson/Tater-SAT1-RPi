#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote


_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
RELEASE_REPO = "TaterTotterson/Tater-SAT1-RPi"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_url(repo: str, tag: str, name: str) -> str:
    return f"https://github.com/{repo.strip('/')}/releases/download/{quote(tag, safe='')}/{quote(name, safe='')}"


def find_one(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected one {pattern} artifact in {directory}, found {len(matches)}")
    return matches[0]


def artifact(path: Path, kind: str, target: str, transport: str) -> dict[str, object]:
    return {
        "kind": kind,
        "path": target,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "flash_transport": transport,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Tater SAT1 release manifests")
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--release-repo", default=RELEASE_REPO)
    parser.add_argument("--release-tag")
    args = parser.parse_args()
    version = args.version.strip()
    if not _VERSION.fullmatch(version):
        raise SystemExit(f"invalid SAT1 release version: {version}")
    release_dir = args.release_dir.resolve()
    if "/" not in args.release_repo.strip("/"):
        raise SystemExit("--release-repo must use OWNER/REPO format")

    def target(path: Path) -> str:
        return release_url(args.release_repo, args.release_tag, path.name) if args.release_tag else path.name

    devices: list[dict[str, object]] = []
    boards: dict[str, dict[str, str]] = {}
    for flavor in ("standalone", "satellite"):
        ota_path = find_one(release_dir, f"tater-sat1-{flavor}-*-ota.sat1")
        board = f"satellite1_rpi_{flavor}"
        firmware_version = f"tater-sat1-{flavor}-{version}"
        device = {
            "key": board,
            "label": f"Tater SAT1 Raspberry Pi — {flavor.title()}",
            "board": board,
            "firmware_version": firmware_version,
            "display_version": version,
            "project": "tater.sat1_rpi",
            "artifacts": {
                "ota": artifact(ota_path, "ota", target(ota_path), "tater_native_ota"),
            },
        }
        devices.append(device)
        boards[board] = {
            "label": str(device["label"]),
            "board": board,
            "version": firmware_version,
            "display_version": version,
        }

    manifest_name = f"tater-sat1-rpi-{version}-manifest.json"
    manifest_path = release_dir / manifest_name
    manifest = {
        "schema": 1,
        "kind": "tater_native_satellite_firmware",
        "project": "tater.sat1_rpi",
        "version": version,
        "display_version": version,
        "devices": devices,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_target = target(manifest_path)
    for board in boards.values():
        board["manifest"] = manifest_target
    latest = {
        "schema": 1,
        "kind": "tater_native_satellite_firmware_latest",
        "version": version,
        "display_version": version,
        "manifest": manifest_target,
        "boards": boards,
    }
    (release_dir / "latest.json").write_text(json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
