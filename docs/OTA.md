# Signed appliance updates

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
6. After boot, a health service checks the expected version and voice services.
   Standalone also checks the local Tater HTTP service. A failed check restores
   the previous appliance automatically and reboots again.

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

The OTA does not replace Raspberry Pi OS, the kernel, boot firmware,
partitions, or FutureProofHomes hardware packages. Changes to those layers
still require flashing a newly built `.img.xz`. Keeping that boundary narrow
makes application updates recoverable without maintaining a second OS
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
