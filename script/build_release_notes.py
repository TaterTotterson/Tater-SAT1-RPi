#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


RELEASE_REPO = "TaterTotterson/Tater-SAT1-RPi"
_TAG = re.compile(r"^v[0-9][A-Za-z0-9._+-]{0,126}$")
RELEASE_HIGHLIGHTS = {
    "v0.1.7": (
        "Standalone images now bundle the manually selected Tater `v1.1.16` release instead of resolving Tater "
        "`main` during each build.",
        "The separate daily Tater downloader has been removed; Tater now changes only as part of a signed SAT1 "
        "appliance OTA, together with the tested voice and hardware integration.",
        "Signed OTA health checks and full-appliance rollback remain in place, and disabled compatibility units let "
        "older flashed cards accept this transition release safely.",
    ),
    "v0.1.6": (
        "Both image flavors now bundle the checksum-pinned Tater Native XMOS `v1.1.1` firmware with the same "
        "four-microphone beamforming, talker direction, AEC, noise suppression, and gain control used by the "
        "SAT1 ESP32 firmware.",
        "Boot checks the attached XMOS before voice audio starts, leaves an already-current device untouched, "
        "and writes an older or unavailable version with flash verification before accepting it.",
        "The XMOS payload and verifier are included in signed appliance OTA; Wi-Fi, setup, Tater, and the rest "
        "of the appliance can continue starting while only voice audio waits for the hardware check.",
    ),
    "v0.1.5": (
        "Both image flavors now let you choose the satellite name and room directly from the Wi-Fi setup page.",
        "Save and connect now closes setup mode and hands Wi-Fi back to the normal network service without a full "
        "device reboot, fixing the frozen setup LEDs and stalled first connection.",
        "The active voice service restarts automatically so the new identity and connection settings take effect "
        "while Tater and the LED service keep running.",
    ),
    "v0.1.4": (
        "Tater Embedded now checks once daily for a newer official stable Tater release; ordinary commits, "
        "drafts, and prereleases are ignored.",
        "Tater app updates are staged in a fresh edge environment, health checked after a brief restart, and "
        "automatically rolled back if the new release does not start cleanly.",
        "Signed SAT1 firmware remains authoritative and can replace the app-only release while preserving settings, "
        "memory, credentials, and other persistent state.",
    ),
}


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str


def git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def previous_release_tag(repo_root: Path, current_tag: str) -> str | None:
    tags = git(
        repo_root,
        "tag",
        "--merged",
        current_tag,
        "--list",
        "v*",
        "--sort=-version:refname",
    ).splitlines()
    return next((tag for tag in tags if tag and tag != current_tag), None)


def release_commits(repo_root: Path, current_tag: str, previous_tag: str | None) -> list[Commit]:
    revision = f"{previous_tag}..{current_tag}" if previous_tag else current_tag
    output = git(repo_root, "log", "--reverse", "--no-merges", "--format=%H%x09%s", revision)
    commits: list[Commit] = []
    for line in output.splitlines():
        sha, separator, subject = line.partition("\t")
        if separator and sha and subject:
            commits.append(Commit(sha=sha, subject=subject))
    return commits


def render_release_notes(repo: str, tag: str, previous_tag: str | None, commits: list[Commit]) -> str:
    lines = [
        "Ready-to-flash Satellite1 Raspberry Pi images:",
        "",
        "- `standalone` runs Tater and the voice satellite together.",
        "- `satellite` runs only the voice satellite and pairs with a main Tater server.",
        "",
        "Both flavors support signed appliance OTA from Tater after this OTA-capable image has been flashed once. "
        "Base OS and kernel changes still require flashing a new image.",
        "",
        "Flash the desired `.img.xz` with Raspberry Pi Imager, customize Wi-Fi and login settings, attach the "
        "Satellite1 HAT, and boot.",
        "",
        "## What's Changed",
        "",
    ]
    highlights = RELEASE_HIGHLIGHTS.get(tag, ())
    if highlights:
        lines.extend(f"- {highlight}" for highlight in highlights)
    if commits:
        lines.extend(
            f"- {commit.subject} ([`{commit.sha[:7]}`](https://github.com/{repo}/commit/{commit.sha}))"
            for commit in commits
        )
    else:
        lines.append("- No user-facing changes were recorded for this release.")
    lines.extend(["", _changelog_link(repo, tag, previous_tag), ""])
    return "\n".join(lines)


def _changelog_link(repo: str, tag: str, previous_tag: str | None) -> str:
    if previous_tag:
        target = f"https://github.com/{repo}/compare/{previous_tag}...{tag}"
    else:
        target = f"https://github.com/{repo}/commits/{tag}"
    return f"**Full Changelog**: {target}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build release notes from commits since the previous release tag")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-repo", default=RELEASE_REPO)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--previous-tag",
        help="previous published release tag; pass an empty value when no release exists",
    )
    args = parser.parse_args()

    tag = args.tag.strip()
    repo = args.release_repo.strip("/")
    if not _TAG.fullmatch(tag):
        raise SystemExit(f"invalid release tag: {tag}")
    if repo.count("/") != 1:
        raise SystemExit("--release-repo must use OWNER/REPO format")

    repo_root = args.repo_root.resolve()
    if args.previous_tag is None:
        previous_tag = previous_release_tag(repo_root, tag)
    else:
        previous_tag = args.previous_tag.strip() or None
        if previous_tag and not _TAG.fullmatch(previous_tag):
            raise SystemExit(f"invalid previous release tag: {previous_tag}")
    commits = release_commits(repo_root, tag, previous_tag)
    notes = render_release_notes(repo, tag, previous_tag, commits)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(notes, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
