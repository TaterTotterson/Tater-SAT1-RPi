<div align="center">
  <a href="https://taterassistant.com">
    <img src="images/tater-sat1-rpi-logo.png" alt="Tater SAT1 Raspberry Pi Images" width="720"/>
  </a>
</div>

<p align="center">
  <a href="https://taterassistant.com">
    <img alt="Visit Tater Assistant" src="https://img.shields.io/badge/Tater%20Assistant-Visit%20Website-F28C28?style=for-the-badge&amp;logo=googlechrome&amp;logoColor=white" />
  </a>
  <a href="https://discord.gg/w52namKyXT">
    <img alt="Join the Tater Assistant Discord" src="https://img.shields.io/badge/Discord-Join%20the%20Community-5865F2?style=for-the-badge&amp;logo=discord&amp;logoColor=white" />
  </a>
</p>

# Tater SAT1 Raspberry Pi Images

Ready-to-flash Tater appliances for the FutureProofHomes Satellite1 HAT and a
Raspberry Pi.

The repository builds two flavors from one pinned hardware and audio base. The
full image is the **Tater Embedded** experience; its artifact identifier remains
`standalone` so installed devices retain a stable OTA identity:

- `standalone` (**Tater Embedded**) runs the complete Tater server and native
  Linux voice satellite together on the SAT1 Pi.
- `satellite` runs only the native Linux voice satellite and pairs with a main
  Tater server elsewhere on the network.

Wake detection and audio stay on the SAT1 device. Resource-intensive speech
recognition, language-model, and speech synthesis work runs on Tater or its
configured remote APIs.

## Status

This repository is an early runnable appliance scaffold. It currently provides:

- separate `systemd` services for Tater, SAT1 audio, and the voice runtime
- microphone level normalization and automatic recovery if the experimental
  SAT1 I2S capture stream stalls
- automatic creation of a shared private native-satellite token
- a loopback-only satellite connection to the local Tater server
- configuration and deterministic launch plans
- host diagnostics and unit tests
- Tater's tested remote-only `edge` dependency and runtime profile
- an installer that pins the manually selected Tater `v1.1.16` release plus
  the tested Linux Satellite and hardware revisions
- a Tater Tube-style `pi-gen` pipeline that exports a flashable `.img.xz`
- a fleet satellite flavor that contains no Tater application or Redis service
- unique hostnames and device IDs derived on first boot
- one-time pairing with durable per-device native-satellite credentials
- a shared first-boot Wi-Fi hotspot and captive setup portal for network,
  satellite name, room, and satellite-only pairing
- Tater's optional second-STT wake verification, including Observe, Enabled,
  and fail-open behavior matching the ESP firmware
- signed, flavor-specific appliance OTA through Tater with automatic rollback
- Tater updates carried inside manually published signed appliance OTA releases
- the verified Tater Native XMOS `1.1.1` image on both flavors, with an
  automatic version check before audio and no rewrite when it already matches
- four-microphone talker tracking, DoA, fractional-delay beamforming,
  microphone calibration/fallback, AEC, noise suppression, and AGC on XMOS
- the SAT1 24-pixel ring, driven through its XMOS controller, with the voice,
  timer, volume, mute, and connection animations used by the ESP32 firmware
- XMOS direction-of-arrival input for the warm-tipped listening beam and saved
  reply direction
- real speaker-monitor levels for the direction-anchored reactive reply ring
- SAT1 volume buttons and hardware microphone-mute switch bridged into Tater

The image has completed initial boot, audio, wake-word, and LED bring-up on
physical SAT1 hardware. Environmental sensor telemetry is not included yet.

## Runtime flows

```text
SAT1 HAT -> local wake/audio service -> Tater on localhost:8501
                                      -> remote STT/LLM/TTS APIs

SAT1 HAT -> local wake/audio service -> main Tater over the LAN
```

The design follows the existing Tater Reachy Standalone pattern while keeping
the runtimes as independently supervised services.

## Development

Run the tests without installing the package:

```sh
./script/test
```

Inspect the commands that would run with the example configuration:

```sh
./script/plan
./script/plan config/config.toml.example satellite
```

The plan command always redacts credentials.

## Pi installation direction

The primary installation path is now a complete image containing Raspberry Pi
OS, the pinned FutureProofHomes board packages, and the newest Tater available
when the image build begins.

Build the standalone image with:

```sh
./scripts/build-pi-image.sh
```

Build the fleet satellite image with:

```sh
./scripts/build-pi-image.sh --flavor satellite
```

Flash the resulting `.img.xz` using Raspberry Pi Imager's **Use Custom**
option. SSH is disabled in the image by default. If remote shell access is
needed, explicitly enable it in Raspberry Pi Imager and supply a unique
password or public key, keeping the appliance username `tater`. On first boot,
join the unique
`Tater-SAT1-Setup-XXXXXX` hotspot and follow the captive page; SSH is not
required for normal setup. See
[Wi-Fi hotspot setup](docs/PROVISIONING.md) and
[Image building and flashing](docs/IMAGE.md).

Preview the complete installation without modifying the host:

```sh
./script/install --dry-run
```

On a dedicated Satellite1 Raspberry Pi image, install with:

```sh
sudo ./script/install
```

The installer places:

- the full Tater source and edge environment under `/opt/tater` for standalone
- this launcher and Tater Linux Satellite at `/opt/tater-sat1/venv`
- persistent state at `/var/lib/tater-sat1-standalone`
- configuration at `/etc/tater-sat1-standalone/config.toml`

The Tater Embedded flavor does not download Tater releases independently.
Refresh the bundled Tater revision when preparing this repository, then publish
it through the signed SAT1 appliance OTA. A failed appliance health check
restores the previous known-good release. See
[Signed appliance updates](docs/OTA.md).

See [Image building and flashing](docs/IMAGE.md),
[Wi-Fi hotspot setup](docs/PROVISIONING.md),
[Fleet satellite image](docs/FLEET_IMAGE.md),
[Signed appliance updates](docs/OTA.md),
[Installation](docs/INSTALL.md), [Architecture](docs/ARCHITECTURE.md),
[Edge profile](docs/EDGE_PROFILE.md), [Upstream references](docs/UPSTREAMS.md),
and [Roadmap](docs/ROADMAP.md) for the implementation path.

## License

AGPL-3.0-only. The standalone appliance combines with Tater, which is licensed
under the GNU Affero General Public License v3.
