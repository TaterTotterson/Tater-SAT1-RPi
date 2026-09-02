# Upstream references

The project should assemble existing Tater components rather than fork their
behavior unnecessarily. `upstreams.toml` records the tested revisions and the
policy used to resolve each build input.

## Reachy Tater Standalone

This is the primary application-lifecycle reference. Reuse its approach for:

- installing Tater separately from persistent state
- creating one stable owner-only native-satellite credential
- passing that credential to Tater and the local satellite
- connecting the satellite to `http://127.0.0.1:8501`
- keeping the Tater Web UI reachable on the LAN
- preserving state across application bundle replacements

SAT1 differs by using independently supervised Tater, audio, and voice services
instead of the Reachy SDK app process tree. The protocol and credential
lifecycle should remain equivalent.

## Tater Linux Satellite

Use its wake-word, audio session, playback, reconnect, and native WebSocket
implementations. Add SAT1 hardware through an adapter rather than copying the
transport into this repository.

The fleet image also reuses Linux Satellite's short-code pairing exchange and
durable per-device token persistence. This repository only supplies unique Pi
identity, service supervision, and the pairing command.

## ThirdReality firmware

Use its Buildroot work as a reference for an appliance-style boot flow,
hardware bridge, captive provisioning, signed updates, and recovery. The SAT1
base OS remains Raspberry Pi OS because the FutureProofHomes kernel and device
tree support are already there.

## Tater Native XMOS

Both RPi image flavors bundle the production XMOS `1.1.1` factory image from
the published `Tater-Native-Firmware` `native-0.3.15` tag. Its source revision,
version, and binary SHA-256 are pinned in `upstreams.toml`. The boot verifier
uses the FutureProofHomes host utility to read, write, and verify the external
XMOS flash, while the audio processing itself remains the same four-microphone
DoA and beamforming implementation used by Tater Native on ESP32.

## Tater

The full app remains upstream Tater. Standalone builds use the manually
selected stable release and exact commit recorded in `upstreams.toml`; version
`0.1.10` carries Tater `v1.1.23`. Downloaded cores live in persistent,
service-owned SAT1 state while bundled cores remain in the protected Tater
application tree. A narrowly scoped build overlay supplies SAT1 hardware VAD
defaults and becomes a no-op when upstream Tater includes that behavior. This
repository owns the appliance image, service configuration, tested Linux
Satellite pin, and SAT1-specific integration.

## FutureProofHomes Satellite1-RPi

The flashable image embeds the v0.1.4 custom kernel, board setup, and Python SDK
packages. Their filenames and SHA-256 hashes are recorded in
`packaging/image.lock`; the corresponding source revision is recorded in
`upstreams.toml`.
