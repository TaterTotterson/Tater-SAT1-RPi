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

Both image flavors pin Linux Satellite **1.2.1** at
`4c0762e5919741875b2a976712ac421bf8eb3908`, including the concurrent custom
wake-model and boundary-cache write fixes. Install its ONNX extra and build its
checksum/revision-pinned Sendspin player with the shared install script. The
player binary and channel-routing support live under `/opt/tater-sat1/sendspin`
so the signed appliance update and rollback include them. Pairing state, wake
downloads, live settings and satellite identity stay in persistent state.

SAT1 advertises the XMOS hardware AEC path to the shared wake/playback logic.
The adapter also keeps the shared Bluetooth latency guards and pauses discovery
during signed appliance OTA. Bluetooth uses on-demand BlueZ/GATT operations;
the old continuous room-presence observer is no longer included. A service-user
D-Bus policy is applied before voice startup, including after updates of older
cards, without adding new paths to the signed OTA format.

The fleet image also reuses Linux Satellite's short-code pairing exchange and
durable per-device token persistence. This repository only supplies unique Pi
identity, service supervision, and the pairing command.

## ThirdReality firmware

Use its Buildroot work as a reference for an appliance-style boot flow,
hardware bridge, captive provisioning, signed updates, and recovery. The SAT1
base OS remains Raspberry Pi OS because the FutureProofHomes kernel and device
tree support are already there.

## Tater Native XMOS

Both RPi image flavors bundle the tested XMOS `1.2.0-dev.1` factory image from
the published `Tater-Native-Firmware` `native-0.7.0-r1` tag. Its source revision,
version, and binary SHA-256 are pinned in `upstreams.toml`. The boot verifier
uses the appliance protocol 0x10/0x11 reader to check the running version and
the FutureProofHomes utility to write and verify the external XMOS flash, while the audio processing itself remains the same four-microphone
DoA and beamforming implementation used by Tater Native on ESP32.

## Tater

The full app remains upstream Tater. Standalone builds use the manually
selected Tater `v3.0.9` stable release and exact commit recorded in
`upstreams.toml`. Downloaded cores, Verbas, and portals live in
persistent, service-owned SAT1 state instead of the protected Tater application
tree. Tater ships only the empty Python package scaffolding for these surfaces;
all installed content comes from the user. A narrowly scoped build overlay
supplies SAT1 hardware VAD defaults and becomes a no-op when upstream Tater
includes that behavior. This repository owns the appliance image, service
configuration, tested Linux Satellite pin, and SAT1-specific integration.

## FutureProofHomes Satellite1-RPi

The flashable image embeds the v0.1.4 custom kernel, board setup, and Python SDK
packages. Their filenames and SHA-256 hashes are recorded in
`packaging/image.lock`; the corresponding source revision is recorded in
`upstreams.toml`.
