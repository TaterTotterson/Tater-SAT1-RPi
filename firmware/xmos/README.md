# Tater Satellite1 XMOS firmware

`sat1_xmos_1_2_0_dev13_factory.bin` is the exact image shared with native
Satellite1 `native-satellite1-0.7.0-r4`. Both RPi image flavors select this payload.

- XMOS version: `v1.2.0-dev.13`
- Native source release: `native-satellite1-0.7.0-r4`
- Native source commit: `f951b3e632cf7f7d9446c42ce39067a8c89d02ba`, pinned in `upstreams.toml`
- SHA-256: `2af046f6d95372f332cdc48236c74098ce4f8bcf8608efe8c04925122c75865f`
- Original path: `main/boards/sat1/xmos/sat1_xmos_1_2_0_dev13_factory.bin`
- Size: 270,336 bytes; normal production image with bench capture disabled

The signal path is four microphones → four-microphone AEC → speech-aware
direction tracking and calibrated beamforming → protected interference and
residual-echo cleanup → noise suppression → AGC. Playback is still stereo;
the echo-cancellation reference is mixed to mono.

DSP frame transfers use a separate intertile communication link from I2S/GPIO
control, removing the communication lock cycle that could stall startup or
playback. The image also includes bounded frame buffering and ownership fixes.
SPI protocol 0x11, the 32-byte DoA response on resource 233, 48 kHz I2S,
microphone calibration/health and Tater's GPIO/LED controls remain compatible
with the RPi adapter. This change adds no new host hint writes or SPI polling.

The boot verifier checks the payload hash, installs it only when the running
version differs, and accepts it only after XMOS reports `v1.2.0-dev.13` over SPI.
The pinned vendor utility still writes and verifies flash. Tater-host hardware
testing of this exact DSP image passed on native Sat1, including music, immediate
commands from two sides, direction LEDs and a full power cycle. That does not
establish a Raspberry Pi hardware pass. The Pi's existing audio watchdog stays
enabled because Pi I2S/ALSA stalls can have a separate cause.

The dev.8, dev.1 and 1.1.1 images remain unchanged at their original paths so
installed signed OTA verifiers can accept replacement application trees and
application rollback can still select its previous DSP. They are recovery
images, not the selected boot target.
