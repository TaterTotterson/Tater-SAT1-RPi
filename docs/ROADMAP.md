# Roadmap

## Phase 1: host-side skeleton

- [x] Separate Tater and satellite systemd services
- [x] Shared private local satellite credential
- [x] Configuration, execution plans, and host diagnostics
- [x] Reproducible remote-only dependency manifest and pinned installer
- [x] Tater import and live health test without local-model packages installed

## Phase 2: Satellite1 hardware

- [ ] Validate capture and playback ALSA device names on a Pi Zero 2 W
- [ ] Initialize PCM5122/TAS2780 and XMOS through the Satellite1 SDK
- [ ] Add the 24-pixel LED ring and physical buttons
- [ ] Bridge volume, microphone mute, sensors, and DoA telemetry
- [ ] Verify playback-reference AEC and wake-word operation during playback

## Phase 3: self-contained image

- [x] Build a Bookworm image with pinned FutureProofHomes Satellite1 packages
- [ ] Add first-boot Wi-Fi and Tater provider setup
- [x] Configure zram and bounded journal storage
- [ ] Add read-only-root/overlay options and graceful power-loss handling
- [ ] Add signed appliance updates and recovery documentation

## Phase 4: performance gate

- [ ] Measure cold boot, idle RSS, wake latency, and request latency
- [ ] Run a 24-hour memory/reconnect soak test
- [ ] Confirm music playback does not starve Tater or wake detection
- [ ] Establish the minimum supported Raspberry Pi model
