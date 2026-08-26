# Wi-Fi hotspot setup

Both image flavors provide the same first-boot Wi-Fi experience. If the SAT1
does not have a working Wi-Fi connection, it creates an open setup network:

```text
Tater-SAT1-Setup-XXXXXX
```

The suffix is derived from the Wi-Fi interface address so several unconfigured
SAT1 devices can be distinguished in the same room.

1. Join the `Tater-SAT1-Setup-XXXXXX` network from a phone or computer.
2. The captive setup page should open automatically. If it does not, browse to
   `http://192.168.4.1`.
3. Enter the Wi-Fi name and password.
4. On the satellite-only image, also enter the main Tater address and the
   pairing code shown under **Satellites → Add Satellite** in Tater.
5. Choose **Save and restart**. The hotspot closes and the SAT1 joins the
   selected network.

The standalone image does not ask for a server or pairing code because its
voice runtime connects to Tater locally. After it restarts, open its unique
`http://tater-sat1-xxxxxx.local:8501` address.

The setup network is intentionally open, has no route to the internet, and
exists only while the SAT1 is waiting for working Wi-Fi. Credentials and the
satellite pairing code are saved locally with owner-only permissions. If a
saved Wi-Fi profile cannot connect during boot, the recovery hotspot appears
again after approximately 45 seconds.

When Wi-Fi is supplied through Raspberry Pi Imager or baked into an image, the
SAT1 connects normally and does not start the hotspot.

Useful diagnostics over SSH are:

```sh
systemctl status tater-sat1-provisioning.service
sudo tater-sat1-setup-hotspot status
journalctl -u tater-sat1-provisioning.service
```
