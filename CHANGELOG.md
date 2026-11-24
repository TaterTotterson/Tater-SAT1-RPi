# 0.1.18

- Bundle the exact working XMOS 1.2.0-dev.1 image shared with native Sat1
  0.7.0-r1, retaining calibrated pre-AEC beamforming and stereo echo references.
- Support protocol 0x10/0x11 framing, write acknowledgements, and DoA resource
  233 in the SPI reader used by boot verification, buttons, and LEDs.
- Preserve the old factory image path for existing signed OTA verifiers.
- Keep Tater 3.0.9 and Linux Satellite 1.2.1 pinned. Native hardware checks and
  RPi protocol/packaging tests cover this change; RPi hardware testing is pending.

# 0.1.17

- Update both satellite-only and Tater Embedded images to Linux Satellite 1.2.1.
- Fix custom wake-model activation when startup and incoming settings trigger
  overlapping downloads. Cover NanoWakeWord, openWakeWord, custom microWakeWord
  model writes, and boundary-model caching with independent temporary files.
- Verify the concurrency regression tests and the selected MWW + NanoWakeWord
  GRU profile on a running SAT1 Raspberry Pi Zero 2 W.
- Simplify setup documentation, include Home Assistant bridge management, and
  explain wake boundaries and recommended dual-detector wake confirmation.

# 0.1.16

- Update Tater Embedded from Tater 1.1.23 to the stable Tater 3.0.9 release,
  including the refreshed TaterOS UI and current assistant and satellite
  features. Keep the remote-only edge profile for the Raspberry Pi.
- Verify edge-profile startup, WebUI, Redis, and authenticated native-satellite
  connections in an ARM64 Debian Bookworm container with a 512 MiB memory limit.

# 0.1.15

- Show an orange comet chase with amber sparkles while the voice runtime starts.
- Fix SAT1 startup on ordinary USB power when the audio SDK cannot read a
  negotiated USB-PD contract, and remove a 90-second I²C device wait.
- Prevent a login-session audio server from claiming the sound card.
- Fix automatic installation of Tater's XMOS audio firmware after switching
  from ESPHome. Keep flashrom's default write verification and verify the
  running firmware version before starting audio.
- Validate startup, wake detection, and spoken replies on a SAT1 with a
  Raspberry Pi Zero 2 W using the updated shared voice runtime.

# 0.1.14

- Update both SAT1 Raspberry Pi image flavors to Tater Linux Satellite 1.2.0.
- Include ONNX wake engines, shared wake profiles and wake-boundary support.
- Build and bundle the shared Sendspin player with stereo channel routing,
  persistent player state and speech ducking through the private audio server.
- Replace continuous Bluetooth room-presence scanning with on-demand discovery
  and the shared GATT proxy. Pause discovery during appliance OTA as well as
  voice and media work; use BlueZ D-Bus permissions for the voice service.
- Enable the shared runtime's XMOS AEC-aware wake/playback behavior and persist
  live satellite name/room changes alongside the existing setup flow.
- Add compatibility checks against the actual pinned runtime, including an
  ARM64 Debian Bookworm Sendspin build. Physical SAT1 audio and Bluetooth
  testing remains pending.
