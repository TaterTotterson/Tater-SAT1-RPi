# Ready-to-flash Raspberry Pi image

The image builder follows the Tater Tube appliance pipeline: it adds a custom
stage to Raspberry Pi's `pi-gen`, installs the complete application inside the
root filesystem, and exports a compressed `.img.xz` plus a SHA-256 checksum.

## Image flavors

- `standalone` includes full Tater and connects the voice runtime over
  loopback. This remains the default.
- `satellite` omits Tater and connects the voice runtime to a paired main Tater
  over the network.

Both flavors include:

- Raspberry Pi OS Lite 64-bit Bookworm
- FutureProofHomes Satellite1 v0.1.4 custom FUSB302 kernel, overlays, ALSA
  configuration, SDK, and DAC initialization service
- Tater Linux Satellite with local wake-word detection
- a private PulseAudio service for capture and playback
- zram sized to 50 percent of RAM

The standalone flavor additionally includes full Tater with its remote-only
`edge` dependency profile and enables the Tater web interface at boot.

The hardware packages, pi-gen base, Tater source, and Linux Satellite source
are all pinned. `packaging/image.lock` contains the image and hardware hashes;
`upstreams.toml` contains the application revisions.

## Build locally

Requirements:

- Git, curl, and Docker
- enough storage for a Raspberry Pi OS image build (allow roughly 20 GB)
- preferably an ARM64 Linux build host; Docker emulation on macOS is slower

Inspect the image inputs:

```sh
./scripts/build-pi-image.sh --plan
```

Download and verify the pinned inputs without starting pi-gen:

```sh
TATER_SOURCE_DIR=../Tater ./scripts/build-pi-image.sh --prepare-only
```

Build a lab image with Wi-Fi already configured:

```sh
PI_FIRST_USER_PASS='choose-a-password' \
PI_WIFI_SSID='your-wifi' \
PI_WIFI_PASSWORD='your-wifi-password' \
PI_WIFI_COUNTRY='US' \
./scripts/build-pi-image.sh
```

Add `--flavor satellite` to build the fleet image without Tater. See
[Fleet satellite image](FLEET_IMAGE.md) for pairing instructions.

The compressed image is written under:

```text
.cache/pi-gen-bookworm-arm64/deploy/image_*.img.xz
```

If Wi-Fi is not embedded, use Raspberry Pi Imager's customization screen when
flashing. Local builds default to the temporary lab login `tater` / `tater`;
set `PI_FIRST_USER_PASS` or an SSH public key before sharing an image.

## Flash and boot

1. Open Raspberry Pi Imager.
2. Choose **Use Custom** and select `image_*.img.xz`.
3. Select a 16 GB or larger microSD card and apply Wi-Fi/login customization
   if needed.
4. Flash and verify the card.
5. Attach the Satellite1 HAT to the powered-off Pi Zero 2 W and insert the
   card.
6. Apply power and allow several minutes for the first boot.
7. For standalone, open the unique `tater-sat1-xxxxxx.local:8501` hostname or
   use the Pi's IP address. For satellite-only, follow the pairing steps in
   [Fleet satellite image](FLEET_IMAGE.md).

The first-boot service derives a unique hostname and device ID on every Pi. In
the standalone flavor it also generates the local credential. The satellite
flavor receives a one-time code during pairing and stores the resulting
per-device credential. No credential is stored in either distributable image.

## What still needs hardware validation

The image is designed to boot directly into the voice appliance, but the first
card is still a bring-up build. Validate the actual ALSA capture/playback names,
Pi Zero 2 W memory pressure, wake-word behavior during playback, and clean
restarts. The SAT1 LED ring and buttons remain a separate adapter milestone.
