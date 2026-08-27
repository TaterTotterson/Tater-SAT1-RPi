# Install on a Satellite1 Raspberry Pi

The recommended path is the ready-to-flash image described in [IMAGE.md](IMAGE.md).
This installer remains useful when developing on an existing Raspberry Pi OS
installation or repairing an image without reflashing it.

## Before installing

- Boot the Satellite1 Pi image and confirm networking works.
- Confirm the XMOS microphone and desired output device appear in ALSA or
  PipeWire/PulseAudio.
- Clone this repository onto the Pi.
- Keep at least 2 GB of free storage for source trees, virtual environments,
  logs, and future updates.

Inspect every planned command first:

```sh
./script/install --dry-run
```

Install the pinned Tater and Linux Satellite revisions:

```sh
sudo ./script/install
```

Install only the fleet satellite runtime:

```sh
sudo ./script/install --flavor satellite
```

Use `--no-enable` to install without starting services, or `--skip-apt` when
the required Debian packages are already present.

## What it installs

- `/opt/tater/app` and `/opt/tater/venv`: full Tater source plus its
  remote-only `edge` environment in the standalone flavor only
- `/opt/tater-sat1/linux-satellite`: pinned editable Linux Satellite source so
  its bundled wake words and sound files remain available
- `/opt/tater-sat1/venv`: Linux Satellite and appliance launcher environment
- `/var/lib/tater-sat1-standalone`: Redis, Tater, satellite, and credential
  state owned by the unprivileged `tater` service account
- `/etc/tater-sat1-standalone/config.toml`: audio and appliance settings
- supervised audio and voice services, plus local Tater in standalone mode
- `tater-sat1-leds.service`: the SAT1 24-pixel ring controller
- `tater-sat1-provisioning.service`: Wi-Fi fallback hotspot and local portal

The generated native-satellite token is owner-only and is shared only through
the local state directory. The satellite connects to Tater through loopback;
the Tater web interface listens on port 8501 for LAN setup and use.

On an unconfigured system, join `Tater-SAT1-Setup-XXXXXX` and use the captive
page. For a satellite-only manual install that already has Wi-Fi, create a
pairing code in the main Tater and run:

```sh
sudo tater-sat1-pair --url http://MAIN_TATER_ADDRESS:8501 PAIRING_CODE
```

## Select the SAT1 audio devices

Stop the voice service while discovering devices:

```sh
sudo systemctl stop tater-sat1-voice.service
/opt/tater-sat1/venv/bin/linux-voice-assistant --list-input-devices
/opt/tater-sat1/venv/bin/linux-voice-assistant --list-output-devices
```

Copy the exact XMOS input and speaker output names into
`/etc/tater-sat1-standalone/config.toml`, then restart:

```sh
sudo systemctl restart tater-sat1-tater.service tater-sat1-voice.service
```

Inspect health and logs with:

```sh
curl http://127.0.0.1:8501/api/health
sudo journalctl -u tater-sat1-tater.service -u tater-sat1-voice.service -f
```

## SAT1 LED ring

The LED controller follows the production ESP32 SAT1 firmware: slow waiting
spin, fast listening spin, opposing thinking pulse, reverse replying spin,
volume arc, timer arc/ring, microphone and speaker mute markers, error pulse,
and disconnected red twinkle. It receives the same voice events from the
Linux Satellite peripheral API in either image flavor.

The defaults are a 24-pixel GRB WS2812 ring on BCM GPIO 12. If a hardware
revision routes the ring differently, edit `[leds]` in
`/etc/tater-sat1-standalone/config.toml`, then restart and inspect the service:

```sh
sudo systemctl restart tater-sat1-leds.service
sudo journalctl -u tater-sat1-leds.service -f
```

Set `enabled = false` to disable ring output without rebuilding or reflashing.

## Configure remote providers

Open `http://<pi-address>:8501`, then configure:

- a remote/OpenAI-compatible LLM provider;
- a Wyoming STT server;
- either Wyoming TTS or an OpenAI-compatible TTS provider.

The appliance intentionally has no local LLM, STT, or TTS model runtime.
Wake-word inference and WebRTC VAD remain local in the Linux Satellite
process. Generic OpenAI-compatible STT is planned but is not implemented yet.

## Current hardware boundary

This milestone carries microphone capture, local wake detection, playback, the
native Tater conversation loop, and the 24-pixel LED ring. Physical buttons and
sensor/DoA telemetry are not yet installed by this repository.
