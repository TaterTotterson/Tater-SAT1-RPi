# Architecture

The standalone flavor deliberately keeps Tater and the voice satellite in
separate processes. The fleet flavor omits the local Tater process while
reusing the same SAT1 hardware, audio, and voice layers.

```text
Satellite1 HAT
  XMOS / I2S / DAC --------------------+
  24-pixel GRB ring on GPIO 12         |
                |                      |
                v                      v
  tater-sat1-leds.service     tater-sat1-voice.service
                ^             Tater Linux Satellite
                |                      |
       peripheral events on            |
          127.0.0.1:6055 <--------------+
                                       |
      ws://127.0.0.1:8501
                                       |
                                       v
  tater-sat1-tater.service
  Tater Web UI, Hydra, Verbas, integrations, Redis
                |
                v
  remote STT / LLM / TTS providers

Fleet satellite flavor:

  tater-sat1-satellite.service
  Tater Linux Satellite + SAT1 hardware adapter
                |
       Wi-Fi / native WebSocket
                |
                v
       main Tater server
```

In standalone mode, Tater and the voice services read one private local token
from the appliance state directory. In fleet mode, the token file initially
contains a short pairing code and Linux Satellite replaces it with Tater's
durable per-device credential after the first successful connection.

The image also runs `tater-sat1-audio.service`, a private PulseAudio server for
the satellite process. `tater-sat1-firstboot.service` derives a hostname and
device ID from the Pi serial so cloned SD cards never share an identity. It
also creates the local token when the image flavor is standalone.

`tater-sat1-provisioning.service` checks NetworkManager at boot. With working
Wi-Fi it exits without changing the network. Otherwise it temporarily places
`wlan0` in access-point mode, runs hostapd and an isolated dnsmasq instance,
and serves the local setup page at `192.168.4.1`. Saving creates a private,
autoconnecting NetworkManager profile and reboots. The satellite flavor also
stores its one-time Tater pairing code before rebooting.

`tater-sat1-update.path` watches the persistent state directory for bundles
downloaded through the authenticated native-satellite connection. The updater
verifies a release signature before replacing the immutable application roots.
On the next boot, `tater-sat1-update-health.service` accepts the release or
restores its rollback. Configuration, Wi-Fi, pairing credentials, and runtime
state live outside the replaced roots.

## Intended base system

The image composes Raspberry Pi OS Lite Bookworm with FutureProofHomes' pinned
Raspberry Pi Zero 2 W packages. Those supply the custom FUSB302 USB-C Power
Delivery kernel support and the device-tree/ALSA configuration needed by the
board.

## Process ownership

`systemd` owns the Tater, audio, LED, and satellite processes. The LED service
runs as root because the Raspberry Pi WS281x PWM/DMA driver requires direct
hardware access. The standalone voice service requires local Tater and audio.
The fleet voice service requires audio and network availability, then
reconnects to the main Tater automatically.

## Hardware adapter

The FutureProofHomes Satellite1 Python SDK supplies XMOS, DAC, and USB-C PD
control. `tater-sat1-leds.service` listens to Tater Linux Satellite's local
peripheral WebSocket API and reproduces the 24-pixel effects and state priority
from `Satellite1-ESPHome/sat1/led_ring.yaml`. The ring defaults to BCM GPIO 12,
800 kHz, GRB ordering, DMA channel 10, and PWM channel 0; all except ordering
are configurable. Physical buttons, mute input, and sensors remain separate
adapter work.
