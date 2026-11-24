# Tater Satellite1 XMOS firmware

`sat1_xmos_1_2_0_dev1_factory.bin` is the working image shared with the native
Satellite1 `native-0.7.0-r1` release. Its internal development version is retained
so this payload is byte-for-byte identical to the image tested on the ESP32 Sat1.

- XMOS version: `v1.2.0-dev.1`
- Native source release: `native-0.7.0-r1`; exact commit pinned in `upstreams.toml`
- SHA-256: `e5ad83ffd66f03b3ddba1dfef14d9829d15ead9fab0dc416f8a57f0cdf69ec88`
- Original path: `main/boards/sat1/xmos/sat1_xmos_1_2_0_dev1_factory.bin`

It retains four-microphone direction finding, calibration, a steered beam before
2Y2X AEC with stereo echo references, noise suppression, and AGC. It incorporates
fwk_voice 0.9.0, protocol 0x11, and upstream flash/DFU improvements. It does not
include the failed four-microphone AEC or post-AEC residual-beam experiments.

The appliance uses its protocol 0x10/0x11 SPI reader for boot verification,
status-register buttons, LED acknowledgements, and DoA resource 233. The pinned
vendor utility still writes and verifies flash. Matching devices are not
rewritten. Native hardware checks passed; separate RPi hardware qualification
of this migration remains pending.

The original `sat1_xmos_1_1_1_factory.bin` is retained as a recovery image and so
older immutable OTA verifiers accept the replacement appliance tree. It is not
the selected boot update target.
