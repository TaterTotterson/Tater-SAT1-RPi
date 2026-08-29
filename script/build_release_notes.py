#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


RELEASE_REPO = "TaterTotterson/Tater-SAT1-RPi"
_TAG = re.compile(r"^v[0-9][A-Za-z0-9._+-]{0,126}$")


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
    args = parser.parse_args()

    tag = args.tag.strip()
    repo = args.release_repo.strip("/")
    if not _TAG.fullmatch(tag):
        raise SystemExit(f"invalid release tag: {tag}")
    if repo.count("/") != 1:
        raise SystemExit("--release-repo must use OWNER/REPO format")

    repo_root = args.repo_root.resolve()
    previous_tag = previous_release_tag(repo_root, tag)
    commits = release_commits(repo_root, tag, previous_tag)
    notes = render_release_notes(repo, tag, previous_tag, commits)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(notes, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
