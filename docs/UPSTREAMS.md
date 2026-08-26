# Upstream references

The project should assemble existing Tater components rather than fork their
behavior unnecessarily. `upstreams.toml` records the revisions used while
developing the first image.

## Reachy Tater Standalone

This is the primary application-lifecycle reference. Reuse its approach for:

- installing a pinned Tater bundle separately from persistent state
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

## ThirdReality firmware

Use its Buildroot work as a reference for an appliance-style boot flow,
hardware bridge, captive provisioning, signed updates, and recovery. The SAT1
base OS remains Raspberry Pi OS because the FutureProofHomes kernel and device
tree support are already there.

## Tater

The full app remains upstream Tater. The desired edge profile belongs in Tater
itself if possible, while this repository owns the appliance image, service
configuration, source pinning, and SAT1-specific integration.

## FutureProofHomes Satellite1-RPi

The flashable image embeds the v0.1.4 custom kernel, board setup, and Python SDK
packages. Their filenames and SHA-256 hashes are recorded in
`packaging/image.lock`; the corresponding source revision is recorded in
`upstreams.toml`.
