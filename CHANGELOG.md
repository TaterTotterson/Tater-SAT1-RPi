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
