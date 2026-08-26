# Fleet satellite image

The `satellite` flavor is for SAT1 devices that connect to one main Tater over
the local network. It includes the SAT1 kernel, SDK, private audio service,
local wake-word runtime, and native Tater transport. It does not contain the
Tater application, Tater virtual environment, or Redis.

## Build and flash

```sh
PI_FIRST_USER_PASS='choose-a-password' \
PI_WIFI_SSID='your-wifi' \
PI_WIFI_PASSWORD='your-wifi-password' \
./scripts/build-pi-image.sh --flavor satellite
```

Flash `image_*tater-sat1-satellite.img.xz` to a 16 GB or larger microSD card
with Raspberry Pi Imager. The lab build defaults to the SSH login
`tater` / `tater`; set a real password or SSH public key before distributing
images.

## Unique identity

On first boot the appliance derives a stable suffix from the Raspberry Pi
serial number. A Pi ending in `a1b2c3` becomes:

```text
hostname:  tater-sat1-a1b2c3
device ID: tater-sat1-a1b2c3
name:      Tater SAT1 A1B2C3
```

This prevents cloned cards from colliding on the network or inside Tater.

## Pair with the main Tater

The normal flow does not require SSH:

1. Open the main Tater interface and create a short code under
   **Satellites → Add Satellite**.
2. Join the SAT1's `Tater-SAT1-Setup-XXXXXX` Wi-Fi network.
3. In the captive page, enter the destination Wi-Fi, main Tater address, and
   pairing code, then choose **Save and restart**.

If the image already has working Wi-Fi, the equivalent SSH command remains
available:

```sh
sudo tater-sat1-pair \
  --url http://MAIN_TATER_ADDRESS:8501 \
  PAIRING_CODE
```

The command restarts the voice service. On its first successful connection,
the one-time pairing code is replaced by an owner-only durable device token.
The satellite reconnects automatically whenever Wi-Fi or the main Tater
restarts.

See [Wi-Fi hotspot setup](PROVISIONING.md) for recovery behavior and security
details.

Useful checks:

```sh
hostname
systemctl status tater-sat1-satellite.service
journalctl -u tater-sat1-satellite.service -f
```

To pair with a different Tater later, run `tater-sat1-pair` again with a new
pairing code and URL.
