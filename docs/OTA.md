# Signed appliance updates

SAT1 has one application update path: manually published, signed appliance
OTA. The standalone payload includes Tater, Linux Satellite, hardware
integration, services, and their tested dependency environment. The fleet
satellite payload omits Tater because it connects to a separate server.

The device never polls the main Tater repository or installs an app-only Tater
release. To update standalone Tater, refresh the bundled source revision in
this repository, test the complete appliance, and publish a signed SAT1 OTA.
The OTA replaces `/opt/tater` and the SAT1 application together. A failed boot
health check restores the exact previous appliance. A full microSD-card factory
reflash replaces the entire system and may erase personal state; export or
back up anything important first.

## Enabling appliance OTA

Both SAT1 image flavors support signed over-the-air appliance updates through
Tater. The first OTA-capable version must be written to the microSD card once;
after that, normal Tater and SAT1 voice-runtime releases can be installed
without removing the card.

## What happens during an update

1. Tater matches the connected device's board ID to either the `standalone` or
   `satellite` SAT1 release feed.
2. Tater sends the release URL, byte count, and SHA-256 digest over the already
   authenticated native-satellite connection.
3. The SAT downloads the bundle, rejects a wrong size or digest, and stages it
   in its persistent update directory.
4. A root-owned service verifies the bundle's RSA signature, product, flavor,
   version, payload digest, and archive paths before changing the appliance.
5. The service keeps the previous application payload as a rollback, installs
   the new payload, and reboots.
6. After boot, the checksum-pinned XMOS target is verified before audio starts;
   it is flashed only when the installed version differs. The health service
   then checks the expected appliance version and voice services. Standalone
   also checks the local Tater HTTP service. A failed check restores the
   previous appliance automatically and reboots again.

For the standalone image, Tater saves the active firmware-session handoff in
the appliance update directory before it stops itself. The already-open
Firmware page treats the temporary connection loss as a restart, reconnects to
Tater after boot, and reads the durable health result. It reports success only
after the new version passes health checks, or reports the automatic rollback
if those checks fail. This recovery mode is enabled only for the loopback SAT1
inside the standalone appliance; downstream SAT1, ThirdReality, ESP32, and
other satellite update paths keep their normal behavior.

The standalone image receives OTA from the Tater server running on the same Pi
over loopback. The satellite image receives it from the main Tater server it is
paired with. In Tater, use the connected satellite's firmware update action in
the Voice settings.

## Preserved data

An appliance update replaces the versioned application payload under
`/opt/tater-sat1`, and `/opt/tater` in standalone, plus the SAT1-owned runtime
service and helper files. The small verifier, installer, health checker, public
key, and update service remain the fixed recovery layer from the flashed image.
The update deliberately preserves:

- `/etc/tater-sat1-standalone/config.toml`
- `/var/lib/tater-sat1-standalone`, including pairing credentials, Tater state,
  models, and the update journal
- NetworkManager profiles and Wi-Fi credentials
- the hostname and first-boot identity

The OTA can carry the production XMOS target because it is part of the SAT1
appliance integration. It does not replace Raspberry Pi OS, the kernel, Pi boot
firmware, partitions, or FutureProofHomes host packages. Changes to those
layers still require flashing a newly built `.img.xz`. Keeping that boundary
narrow makes application updates recoverable without maintaining a second OS
partition on small cards.

## Signing keys

The private RSA signing key is never copied into an image or committed. Each
image contains only `keys/update-public.pem`. Every future OTA for cards made
from that image must use the matching private key.

For local development, generate a key pair once:

```sh
./script/generate_development_ota_key.sh
./script/verify_ota_key.sh
```

The private key is written below ignored `.secrets/`; the matching public key
is written to the tracked `keys/update-public.pem`. Back up the private key
securely before distributing an image. Losing it means those installed cards
cannot accept another OTA signed by this project key.

GitHub Actions expects the exact private PEM in the
`TATER_SAT1_OTA_PRIVATE_KEY_PEM` repository secret. Local builds use either
that environment variable, `TATER_SAT1_OTA_PRIVATE_KEY_FILE`, or the default
`.secrets/tater-sat1-ota-private.pem`.

Do not casually rotate the public key after distributing images. Key rotation
needs a separately signed transition release or a fresh SD-card image.

## Build and verify

The normal image command emits both artifacts from the same root filesystem:

```sh
PI_RELEASE_VERSION=v0.2.0 ./scripts/build-pi-image.sh --flavor standalone
PI_RELEASE_VERSION=v0.2.0 ./scripts/build-pi-image.sh --flavor satellite
```

Outputs under the pi-gen deploy directory include an `image_*.img.xz` and a
`tater-sat1-<flavor>-<version>-ota.sat1`. Verify a bundle without installing:

```sh
PYTHONPATH=src python3 -m tater_sat1_standalone.update_installer \
  --verify path/to/update.sat1 \
  --flavor standalone \
  --public-key keys/update-public.pem
```

Tagged GitHub builds publish both images, both OTA bundles, checksums,
`latest.json`, and the Tater-compatible release manifest.
