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
