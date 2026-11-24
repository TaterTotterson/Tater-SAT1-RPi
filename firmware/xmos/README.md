# Tater Satellite1 XMOS firmware

`sat1_xmos_1_2_0_dev8_factory.bin` is the IC-enabled image shared with native
Satellite1 `native-0.7.0-r2`. Both RPi image flavors select the same payload.

- XMOS version: `v1.2.0-dev.8`
- Native source release: `native-0.7.0-r2`; exact commit pinned in `upstreams.toml`
- SHA-256: `da5d2bb570d8165e02f746dc35896a3954a09e07f3131e3530582f0b975a4ac4`
- Original path: `main/boards/sat1/xmos/sat1_xmos_1_2_0_dev8_factory.bin`

The signal path is four microphones → calibrated steered beam plus omni →
stereo-reference 2Y2X AEC → IC/VNR → noise suppression → AGC. The image retains
fwk_voice 0.9.0, protocol 0x11, DoA resource 233, microphone calibration/health
and Tater's GPIO/LED controls. It excludes the failed four-microphone AEC and
post-AEC residual-beam experiments.

The boot verifier checks the payload hash, installs it only when the running
version differs, and accepts it only after XMOS reports `v1.2.0-dev.8` over SPI.
The pinned vendor utility still writes and verifies flash. Tater-host hardware
testing follows these builds; the IC-enabled FPH ESPHome topology was tested
earlier with its own application glue.

The dev.1 and 1.1.1 images remain at their original paths so installed signed
OTA verifiers from previous releases can accept replacement application trees.
They are recovery images, not the selected boot target.
