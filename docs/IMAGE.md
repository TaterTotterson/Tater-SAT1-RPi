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
- a private PulseAudio service for capture and playback, with normalized SAT1
  microphone gain and automatic stalled-stream recovery
- the 24-pixel SAT1 ring through the XMOS controller, with animations matching
  the ESP32 firmware
- a first-boot and recovery Wi-Fi hotspot with a captive setup portal
- Wi-Fi power saving disabled for reliable local Tater and satellite connections
- zram sized to 50 percent of RAM
- signed SAT1 appliance updates with a post-boot rollback health check

The standalone flavor additionally includes full Tater with its remote-only
`edge` dependency profile and enables the Tater web interface at boot.

The hardware packages, pi-gen base, and Linux Satellite source are pinned.
For the standalone flavor, every build resolves the newest commit on Tater's
`main` branch and records that exact commit in the release `.info` file. This
keeps newly built embedded systems current without making an in-progress build
change underneath itself. `packaging/image.lock` contains the image and
hardware hashes; `upstreams.toml` contains the source policy and tested
application revisions.

Before Tater is copied into the image, the SAT1 builder adds its small
appliance-only voice-settings overlay so the hardware VAD defaults can come
from the SAT1 service environment. Persisted settings in Tater still take
priority. The overlay is skipped automatically once upstream Tater contains
the same behavior.

## Build locally

Requirements:

- Git, curl, and Docker
- enough storage for a Raspberry Pi OS image build (allow roughly 20 GB)
- preferably an ARM64 Linux build host; Docker emulation on macOS is slower
- the private OTA key matching `keys/update-public.pem`

Inspect the image inputs:

```sh
./scripts/build-pi-image.sh --plan
```

For a new development trust root, generate and securely back up a key before
the first full build:

```sh
./script/generate_development_ota_key.sh
```

Download and verify the build inputs without starting pi-gen:

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
.cache/pi-gen-bookworm-arm64/deploy/tater-sat1-*-ota.sat1
```

## Tagged GitHub releases

Pushing a tag named `v*` starts the Raspberry Pi image workflow. GitHub builds
both `standalone` and `satellite`, runs the test suite, and publishes the two
flashable images, signed OTA bundles, checksums, build metadata, `latest.json`,
and the Tater firmware manifest in one release.

The release body also receives an automatic **What's Changed** section built
from the commits since the previous `v*` tag. The first release includes the
complete repository history; later releases link directly to the comparison
with the previous version.

The repository secret `TATER_SAT1_OTA_PRIVATE_KEY_PEM` must contain the private
key matching `keys/update-public.pem`. Do not rotate this key after images are
distributed without a signed transition release.

Tater checks the release's `latest.json`, matches a connected SAT1 Pi by its
standalone or satellite board identity, and offers the newer signed bundle in
the Firmware tab. No release is created from an ordinary branch push.

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
7. Join `Tater-SAT1-Setup-XXXXXX` and complete the captive setup page. If it
   does not open automatically, browse to `http://192.168.4.1`.
8. For standalone, open the unique `tater-sat1-xxxxxx.local:8501` hostname or
   use the Pi's IP address. The satellite-only portal also collects its Tater
   address and pairing code.

Wi-Fi may still be customized in Raspberry Pi Imager or baked in with the
builder variables. When that connection works, the image skips the hotspot.
See [Wi-Fi hotspot setup](PROVISIONING.md) for the complete flow.

The first-boot service derives a unique hostname and device ID on every Pi. In
the standalone flavor it also generates the local credential. The satellite
flavor receives a one-time code during pairing and stores the resulting
per-device credential. No credential is stored in either distributable image.

Once an OTA-capable image has been flashed, later application releases can be
installed from the connected device's firmware action in Tater. Wi-Fi,
configuration, credentials, and state are preserved, and an unhealthy update
rolls back automatically. Base OS, kernel, boot, and partition changes still
require flashing a new image. See [Signed appliance updates](OTA.md).

## What still needs hardware validation

Initial physical SAT1 bring-up has confirmed boot, Wi-Fi provisioning, XMOS
audio, wake-word playback, and the 24-pixel ring. Continue validating Pi Zero 2
W memory pressure, wake-word behavior during playback, clean restarts, DoA
orientation, control debounce, and safe speaker/LED levels before treating the
image as a release build.
