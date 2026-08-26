# Tater SAT1 Standalone

Experimental all-in-one Tater appliance for the FutureProofHomes Satellite1
HAT and a Raspberry Pi.

The goal is to run the complete Tater server and its native Linux voice
satellite on the same board. Wake detection, audio, LEDs, buttons, and sensors
stay local. Resource-intensive speech recognition, language-model, and speech
synthesis work can use remote APIs.

## Status

This repository is an early runnable appliance scaffold. It currently provides:

- separate `systemd` services for Tater and the SAT1 voice runtime
- automatic creation of a shared private native-satellite token
- a loopback-only satellite connection to the local Tater server
- configuration and deterministic launch plans
- host diagnostics and unit tests
- Tater's tested remote-only `edge` dependency and runtime profile
- a pinned Raspberry Pi installer with a non-mutating dry-run mode

It does **not** yet provide a flashable image or the SAT1 LED/button hardware
adapter. Audio through the HAT's XMOS USB device still needs validation on a
physical Pi.

## Target flow

```text
SAT1 HAT -> local wake/audio service -> Tater on localhost:8501
                                      -> remote STT/LLM/TTS APIs
```

The design follows the existing Tater Reachy Standalone pattern while keeping
the two runtimes as independently supervised services.

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

The intended starting point is the experimental FutureProofHomes Satellite1
Raspberry Pi Zero 2 W image because it already contains the board-specific
kernel, USB-C PD, device-tree, and ALSA work.

Preview the complete installation without modifying the host:

```sh
./script/install --dry-run
```

On a dedicated Satellite1 Raspberry Pi image, install with:

```sh
sudo ./script/install
```

The installer places:

- the full Tater source at `/opt/tater/app`
- a remote-only Tater virtual environment at `/opt/tater/venv`
- this launcher and Tater Linux Satellite at `/opt/tater-sat1/venv`
- persistent state at `/var/lib/tater-sat1-standalone`
- configuration at `/etc/tater-sat1-standalone/config.toml`

See [Installation](docs/INSTALL.md), [Architecture](docs/ARCHITECTURE.md),
[Edge profile](docs/EDGE_PROFILE.md), [Upstream references](docs/UPSTREAMS.md),
and [Roadmap](docs/ROADMAP.md) for the implementation path.

## License

AGPL-3.0-only. The standalone appliance combines with Tater, which is licensed
under the GNU Affero General Public License v3.
