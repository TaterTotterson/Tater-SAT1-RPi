#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
import sys

sys.path.insert(0, str(SRC))

from tater_sat1_standalone.update_installer import (  # noqa: E402
    BUNDLE_KIND,
    BUNDLE_SCHEMA,
    managed_directories,
    managed_files,
)


_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_bundle(rootfs: Path, flavor: str, version: str, private_key: Path, output: Path) -> dict[str, object]:
    if flavor not in {"standalone", "satellite"}:
        raise ValueError(f"unsupported SAT1 flavor: {flavor}")
    if not _VERSION.fullmatch(version):
        raise ValueError(f"invalid SAT1 firmware version: {version}")
    if not private_key.is_file():
        raise FileNotFoundError(f"OTA private key is missing: {private_key}")
    required = (*managed_directories(flavor), *managed_files(flavor))
    for relative in required:
        if not (rootfs / relative).exists():
            raise FileNotFoundError(f"OTA rootfs input is missing: /{relative}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tater-sat1-bundle-") as temporary:
        staging = Path(temporary)
        payload = staging / "payload.tar.xz"
        with tarfile.open(payload, "w:xz", preset=6) as archive:
            for relative in required:
                archive.add(rootfs / relative, arcname=relative, recursive=True)
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "kind": BUNDLE_KIND,
            "product": "tater-sat1-rpi",
            "flavor": flavor,
            "version": version,
            "payload": {
                "path": payload.name,
                "size_bytes": payload.stat().st_size,
                "sha256": sha256_file(payload),
            },
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        signature = staging / "manifest.sig"
        subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                str(private_key),
                "-out",
                str(signature),
                str(manifest_path),
            ],
            check=True,
        )
        temporary_output = output.with_name(f".{output.name}.tmp")
        with tarfile.open(temporary_output, "w") as archive:
            for path in (manifest_path, signature, payload):
                info = archive.gettarinfo(str(path), arcname=path.name)
                info.uid = 0
                info.gid = 0
                info.uname = "root"
                info.gname = "root"
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
        temporary_output.replace(output)
    return {
        "path": str(output),
        "size_bytes": output.stat().st_size,
        "sha256": sha256_file(output),
        "flavor": flavor,
        "version": version,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a signed Tater SAT1 appliance OTA bundle")
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--flavor", choices=("standalone", "satellite"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_bundle(
        args.rootfs.resolve(),
        args.flavor,
        args.version.strip(),
        args.private_key.resolve(),
        args.output.resolve(),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
