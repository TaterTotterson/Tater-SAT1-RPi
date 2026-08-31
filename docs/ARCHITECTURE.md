# Architecture

The standalone flavor deliberately keeps Tater and the voice satellite in
separate processes. The fleet flavor omits the local Tater process while
reusing the same SAT1 hardware, audio, and voice layers.

```text
Satellite1 HAT
  XMOS / I2S / DAC --------------------+
  24-pixel ring behind XMOS/SPI        |
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
the satellite process. A lightweight timer detects the experimental I2S
driver's stalled-latency condition and restarts only the audio and active voice
path. `tater-sat1-firstboot.service` derives a hostname and device ID from the
Pi serial so cloned SD cards never share an identity. It also creates the local
token when the image flavor is standalone.

`tater-sat1-provisioning.service` checks NetworkManager at boot. With working
Wi-Fi it exits without changing the network. Otherwise it temporarily places
`wlan0` in access-point mode, runs hostapd and an isolated dnsmasq instance,
and serves the local setup page at `192.168.4.1`. Saving creates a private,
autoconnecting NetworkManager profile, closes the hotspot, and hands `wlan0`
back to NetworkManager without rebooting. The satellite flavor also stores its
one-time Tater pairing code before making that handoff. Both flavors persist
the user-selected satellite name and room outside the replaceable application
roots, then restart only their voice service so the new identity takes effect.

`tater-sat1-update.path` watches the persistent state directory for bundles
downloaded through the authenticated native-satellite connection. The updater
verifies a release signature before replacing the immutable application roots.
On the next boot, `tater-sat1-update-health.service` accepts the release or
restores its rollback. Configuration, Wi-Fi, pairing credentials, and runtime
state live outside the replaced roots.

The standalone flavor never follows main Tater releases on its own. `/opt/tater`
is refreshed only from the Tater revision included in a manually published,
signed appliance OTA. The boot health check covers both the appliance services
and local Tater, and a failed installation restores the complete previous
appliance.

## Intended base system

The image composes Raspberry Pi OS Lite Bookworm with FutureProofHomes' pinned
Raspberry Pi Zero 2 W packages. Those supply the custom FUSB302 USB-C Power
Delivery kernel support and the device-tree/ALSA configuration needed by the
board.

## Process ownership

`systemd` owns the Tater, XMOS verification, audio, LED, and satellite
processes. The XMOS and LED services run as root because they need direct
access to the Pi SPI device. The XMOS check finishes before audio starts, and
a per-boot marker prevents an audio restart from reopening SPI after the LED
service owns it. The standalone voice service requires local Tater and audio.
The fleet voice service requires audio and network availability, then
reconnects to the main Tater automatically.

## Hardware adapter

The FutureProofHomes Satellite1 Python SDK supplies XMOS, DAC, and USB-C PD
control. Before audio starts, `tater-sat1-xmos.service` reads the installed
version and compares it with the checksum-pinned Tater Native XMOS `1.1.1`
factory image. A matching device is left untouched. A missing or different
version is written with flashrom's verification pass, released from reset,
and accepted only after XMOS reports `v1.1.1` over SPI. This gives both image
flavors the same four-microphone DoA, beamforming, calibration/fallback, AEC,
noise suppression, and AGC pipeline as the Tater Native ESP32 firmware.

`tater-sat1-leds.service` listens to Tater Linux Satellite's local
peripheral WebSocket API and reproduces the 24-pixel effects and state priority
from `Satellite1-ESPHome/sat1/led_ring.yaml`. The production backend sends GRB
frames to the XMOS LED service over SPI 0.0. A configurable Raspberry Pi
PWM/GPIO backend remains available for experimental revisions. The same XMOS
link supplies microphone direction for the listening animation and the SAT1
volume/microphone-mute inputs. A low-overhead reader on the private PulseAudio
sink monitor supplies reply amplitude, allowing the ring to react to actual
playback while remaining centered on the saved microphone direction.
Environmental sensors remain separate adapter work.
