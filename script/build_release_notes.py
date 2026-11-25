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
    "v0.1.20": (
        "Adds physical setup recovery to both SAT1 image flavors: click the center/action button five times "
        "quickly, then hold the sixth press for five seconds. The LED ring shows click progress and a countdown; "
        "releasing early cancels it.",
        "Clears saved Wi-Fi, satellite name/room and external Tater pairing, then reopens the setup hotspot. "
        "The installed image and embedded Tater settings and application data stay in place.",
        "Keeps recovery available when voice or pairing is disconnected and when ring output is disabled. "
        "Blocks setup reset while an appliance update is pending or running.",
        "Reserves the action-button input in the Pi boot settings. Existing cards may need one additional reboot "
        "after OTA to activate it; new images are ready from first boot.",
        "Explains the one-time XMOS write/verification delay when firmware changes. Matching firmware skips "
        "the rewrite on later boots. Retains XMOS `1.2.0-dev.8`, Linux Satellite `1.2.1` and Tater `3.0.9`.",
    ),
    "v0.1.19": (
        "Enables the XMOS interference-cancellation and voice/noise-ratio stage in both SAT1 image flavors "
        "using the shared Tater Native `1.2.0-dev.8` image from Sat1 `0.7.0-r2`.",
        "Retains calibrated four-microphone direction finding and pre-AEC beamforming, two-channel AEC "
        "with stereo echo references, noise suppression, gain control, and protocol 0x11.",
        "Updates the checksum-pinned boot verifier and keeps both prior XMOS image paths so existing "
        "signed OTA verifiers can accept the update. Tater-host hardware testing follows the builds.",
    ),
    "v0.1.18": (
        "Bundles the exact working XMOS `1.2.0-dev.1` image shared with native Sat1 `0.7.0-r1`, "
        "retaining four-microphone direction finding, calibration, pre-AEC beamforming, stereo echo "
        "references, noise suppression, and AGC.",
        "Adds protocol 0x10/0x11 framing, write acknowledgements, and DoA resource 233 support for "
        "firmware verification, buttons, and LEDs. Preserves the old image path for existing signed OTA verifiers.",
        "Includes fwk_voice 0.9.0 and upstream flash/DFU improvements. Excludes the failed four-microphone "
        "AEC and residual-beam experiments. The internal XMOS development identity is retained to keep "
        "the tested binary unchanged.",
        "Native Sat1 hardware checks passed; RPi protocol and packaging tests cover this migration, "
        "with separate RPi hardware qualification pending. Retains Tater `3.0.9` and Linux Satellite `1.2.1`.",
    ),
    "v0.1.17": (
        "Updates both satellite-only and Tater Embedded images to Tater Linux Satellite `1.2.1`, "
        "pinned to the exact release commit.",
        "Fixes custom wake-model activation when startup and incoming settings trigger overlapping downloads. "
        "Independent temporary files protect NanoWakeWord, openWakeWord, custom microWakeWord model writes, "
        "and boundary-model caching.",
        "Verifies overlapping-download regression tests on a SAT1 Raspberry Pi Zero 2 W and confirms its "
        "custom MWW + NanoWakeWord GRU profile loads and reports ready.",
        "Refreshes setup guidance for Tater and the Home Assistant bridge, wake boundaries, and recommended "
        "dual-detector wake confirmation.",
    ),
    "v0.1.16": (
        "Updates Tater Embedded (`standalone`) from Tater `1.1.23` to the stable Tater `3.0.9` release, "
        "including the refreshed TaterOS interface and current assistant and satellite features.",
        "Keeps the lightweight, remote-only edge profile: language models and speech providers run remotely, "
        "while wake detection and satellite audio stay on the SAT1.",
        "Verifies edge-profile tests, WebUI startup, Redis health, and an authenticated native-satellite "
        "connection in ARM64 Debian Bookworm with a 512 MiB container memory limit.",
        "Retains Linux Satellite `1.2.0`, Tater XMOS `1.1.1`, the orange comet startup animation, "
        "and the startup/audio fixes from `0.1.15` in both image flavors.",
    ),
    "v0.1.15": (
        "Shows two orange comets with glowing trails and amber sparkles while the voice runtime starts.",
        "Removes a 90-second I2C device wait and fixes audio initialization when USB-PD contract information "
        "is unavailable.",
        "Prevents login-session PulseAudio servers from claiming the sound card used by SAT1's private audio "
        "server. The fix applies to new images and existing cards receiving OTA.",
        "Repairs automatic XMOS firmware installation after switching from ESPHome, preserving flashrom's "
        "default write verification and checking the running firmware version before starting audio.",
        "Validates startup, wake detection, and spoken replies on a SAT1 with a Raspberry Pi Zero 2 W. "
        "Retains Tater Linux Satellite `1.2.0`, including dual-detector wake confirmation and wake-boundary support.",
    ),
    "v0.1.14": (
        "Updates both standalone and satellite images to Tater Linux Satellite `1.2.0`.",
        "Adds shared wake profiles, ONNX wake engines, and wake-boundary inference to preserve commands spoken "
        "immediately after the wake word.",
        "Bundles the shared Sendspin player for synchronized music, stereo channel routing, persistent player "
        "state, and speech ducking through SAT1's audio server.",
        "Replaces continuous Bluetooth room-presence scanning with on-demand discovery and the shared GATT proxy. "
        "Discovery pauses during voice, media, and appliance OTA work.",
        "Uses SAT1's XMOS echo cancellation with the shared wake/playback behavior and saves live satellite "
        "name and room changes alongside the local setup flow.",
        "Adds compatibility tests against the pinned runtime and an ARM64 Debian Bookworm Sendspin build check. "
        "Physical SAT1 audio and Bluetooth testing remains pending.",
    ),
    "v0.1.13": (
        "Adds always-on BLE advertisement observation to both SAT1 image flavors so Tater can place nearby "
        "devices in rooms using the same live presence interface as Tater Native satellites.",
        "Uses fixed-memory batching and a low-duty raw HCI scan that pauses automatically during voice, playback, "
        "and signed appliance OTA work.",
        "Keeps the voice process unprivileged with only the two Bluetooth capabilities it needs, and continues "
        "normal satellite operation when no Bluetooth adapter is available.",
    ),
    "v0.1.12": (
        "Completes the standalone AirPlay image repair by applying the managed sender's low-port permission on "
        "the Raspberry Pi's first boot instead of inside the restricted image-build container.",
        "Keeps the Tater service unprivileged and grants the capability only to the checksum-verified AirPlay "
        "sender executable.",
        "Retains Tater `v1.1.23`, the pinned native receiver, and persistent user-downloaded core, Verba, and "
        "portal storage.",
    ),
    "v0.1.11": (
        "Repairs the standalone image build by allowing Tater `v1.1.23` setup to install the pinned native "
        "AirPlay receiver and its build dependencies.",
        "Includes Linux capability tooling and grants only the managed AirPlay sender access to its low-numbered "
        "PTP clock ports; the Tater server remains unprivileged.",
        "Retains the persistent, Tater-owned core, Verba, and portal download directories introduced for this "
        "release series.",
    ),
    "v0.1.10": (
        "Standalone images now bundle Tater `v1.1.23`.",
        "Downloaded cores, Verbas, and portals now use persistent, Tater-owned SAT1 storage, fixing the "
        "permission-denied errors caused by attempts to write into the protected application bundle.",
        "User-installed extensions now survive signed SAT1 appliance updates; Tater's application tree retains only "
        "the empty package scaffolding shipped by the main project.",
    ),
    "v0.1.9": (
        "Standalone images now bundle Tater `v1.1.22`, including the selectable AdaFace IR-50 WebFace4M "
        "Face ID model alongside FaceNet512.",
        "Tater safely prepares model-specific face embeddings before switching, retains FaceNet profiles for "
        "rollback, and never compares embeddings from different models.",
        "SpudLink clients follow the Hub's selected Face ID model and re-embed linked face crops through the Hub "
        "without downloading AdaFace to the Spudlet.",
    ),
    "v0.1.8": (
        "Standalone images now bundle Tater `v1.1.17`, which streams large firmware downloads to disk instead of "
        "holding the complete package in Raspberry Pi memory.",
        "Embedded Tater can stage future SAT1 appliance packages without exhausting the limited RAM and swap on a "
        "Raspberry Pi Zero 2 W.",
        "ThirdReality S420 and SAT1 OTA tasks return after the signed update is accepted and let the appliance "
        "finish in the background; SAT1 keeps its device-side health check and automatic rollback protection.",
    ),
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
    elif not highlights:
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
