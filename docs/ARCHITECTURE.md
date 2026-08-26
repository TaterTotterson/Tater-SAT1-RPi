# Architecture

The appliance deliberately keeps Tater and the voice satellite in separate
processes. This preserves the existing native satellite boundary and lets
either side restart without taking down the other.

```text
Satellite1 HAT
  XMOS / I2S / GPIO / LEDs / DAC
                |
                v
  tater-sat1-voice.service
  Tater Linux Satellite + SAT1 hardware adapter
                |
      ws://127.0.0.1:8501
                |
                v
  tater-sat1-tater.service
  Tater Web UI, Hydra, Verbas, integrations, Redis
                |
                v
  remote STT / LLM / TTS providers
```

The Tater and voice services read a private token from the appliance state directory. Tater
receives it as `TATER_NATIVE_SATELLITE_TOKEN`; the satellite receives the same
path through `--tater-token-file`. The token is created once with mode `0600`.

The image also runs `tater-sat1-audio.service`, a private PulseAudio server for
the satellite process. `tater-sat1-firstboot.service` creates the shared token
on the device's first boot so cloned SD cards never share an identity.

## Intended base system

The image composes Raspberry Pi OS Lite Bookworm with FutureProofHomes' pinned
Raspberry Pi Zero 2 W packages. Those supply the custom FUSB302 USB-C Power
Delivery kernel support and the device-tree/ALSA configuration needed by the
board.

## Process ownership

`systemd` owns the Tater, audio, and satellite processes. The satellite service
requires both Tater and audio, but Tater does not depend on the satellite. The
satellite's normal reconnect loop handles Tater startup and restarts.

## Hardware adapter

The first hardware adapter should use the FutureProofHomes Satellite1 Python
SDK for XMOS, DAC, and USB-C PD control. LED, button, mute, and sensor support
can connect through Tater Linux Satellite's peripheral WebSocket API until a
direct plugin interface is available.
