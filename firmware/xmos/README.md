# Tater Satellite1 XMOS firmware

`sat1_xmos_1_1_1_factory.bin` is the production four-microphone XMOS image
published in `TaterTotterson/Tater-Native-Firmware` at tag `native-0.3.15`.

- XMOS version: `v1.1.1`
- Source revision: `b59aef124b29e97e3743105b5b6e1e3f863053d3`
- SHA-256: `8ab57bd9da5f114746fcbc3d25ea57b32ea3938c61ed4b545d5d93a3d410c0e5`
- Original path: `main/boards/sat1/xmos/sat1_xmos_1_1_1_factory.bin`

The image supplies four-microphone DoA, fractional-delay delay-and-sum
beamforming, microphone calibration and fallback, AEC, noise suppression, and
AGC. The RPi appliance verifies this checksum and installed XMOS version before
starting audio. A matching device is never rewritten.
