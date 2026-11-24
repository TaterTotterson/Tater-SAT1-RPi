# Wi-Fi hotspot setup

Both image flavors provide the same first-boot Wi-Fi experience. If the SAT1
does not have a working Wi-Fi connection, it creates an open setup network:

```text
Tater-SAT1-Setup-XXXXXX
```

The suffix is derived from the Wi-Fi interface address so several unconfigured
SAT1 devices can be distinguished in the same room.

While this setup network is active, the SAT1 ring shows the ESP firmware's
warm-white provisioning twinkle. The animation clears automatically when the
hotspot closes and the normal connection and voice animations take over.

1. Join the `Tater-SAT1-Setup-XXXXXX` network from a phone or computer.
2. The captive setup page should open automatically. If it does not, browse to
   `http://192.168.4.1`.
3. Choose the satellite name and optional room shown inside Tater, then enter
   the Wi-Fi name and password.
4. On the satellite-only image, also enter the main Tater address and the
   pairing code shown under **Satellites → Add Satellite** in Tater.
5. Choose **Save and connect**. The hotspot closes, control of Wi-Fi returns to
   NetworkManager, and the SAT1 joins the selected network without rebooting.

The standalone image does not ask for a server or pairing code because its
voice runtime connects to Tater locally. After it connects, open its unique
`http://tater-sat1-xxxxxx.local:8501` address.

The setup network is intentionally open, has no route to the internet, and
exists only while the SAT1 is waiting for working Wi-Fi. Credentials,
satellite identity, room, and the satellite pairing code are saved locally
with owner-only permissions and survive signed appliance updates. If a saved
Wi-Fi profile cannot connect, the recovery hotspot appears again after
approximately 45 seconds.

When Wi-Fi is supplied through Raspberry Pi Imager or baked into an image, the
SAT1 connects normally and does not start the hotspot.

## Reset setup with the action button

Click the center/action button five times quickly, then press it a sixth time
and keep holding for five seconds. The ring fills amber as clicks are counted
and shows an orange countdown during the hold. Releasing early cancels it.

The gesture clears saved Wi-Fi profiles, satellite name/room and, on the
satellite-only image, the saved Tater address and pairing token. It stops voice
and opens `Tater-SAT1-Setup-XXXXXX` again. Re-enter Wi-Fi and a fresh pairing
code through the setup page. The installed image, embedded Tater settings and
application data remain in place.

Recovery reads the physical action button directly on Pi BCM7, so it works
while the voice runtime is disconnected or pairing is invalid, and even when
ring output is disabled. It is blocked while an appliance update is pending
or running. The button must be released after startup before the gesture can
be entered; simply holding it at power-on does not reset setup.

New images reserve BCM7 with `dtoverlay=spi0-1cs`. Older cards receiving this
support through OTA get that boot setting on startup; reboot once more after
the update if the action button is still reserved as `spi0 CS1`.

Useful diagnostics over SSH are:

```sh
systemctl status tater-sat1-provisioning.service
sudo tater-sat1-setup-hotspot status
journalctl -u tater-sat1-provisioning.service
```
