# Roadmap

## Phase 1: host-side skeleton

- [x] Separate Tater and satellite systemd services
- [x] Shared private local satellite credential
- [x] Configuration, execution plans, and host diagnostics
- [x] Reproducible dependency manifest with latest-at-build Tater policy
- [x] Tater import and live health test without local-model packages installed

## Phase 2: Satellite1 hardware

- [x] Validate capture and playback device routing on a Pi Zero 2 W
- [x] Initialize the TAS2780 amplifier and XMOS services for the Pi runtime
- [x] Add the 24-pixel LED ring with the ESP32 firmware's animations
- [x] Add physical volume buttons and the microphone-mute input
- [x] Use XMOS DoA data for the listening animation
- [ ] Bridge environmental sensor telemetry
- [ ] Verify playback-reference AEC and wake-word operation during playback

## Phase 3: self-contained image

- [x] Build a Bookworm image with pinned FutureProofHomes Satellite1 packages
- [x] Add first-boot Wi-Fi hotspot and satellite pairing setup
- [x] Configure zram and bounded journal storage
- [x] Add a satellite-only fleet image with unique first-boot identity
- [x] Add per-device pairing with a main Tater server
- [ ] Add read-only-root/overlay options and graceful power-loss handling
- [x] Add signed appliance updates and automatic rollback documentation

## Phase 4: performance gate

- [ ] Measure cold boot, idle RSS, wake latency, and request latency
- [ ] Run a 24-hour memory/reconnect soak test
- [ ] Confirm music playback does not starve Tater or wake detection
- [ ] Establish the minimum supported Raspberry Pi model
- [ ] Soak-test multiple satellite-only devices against one main Tater
