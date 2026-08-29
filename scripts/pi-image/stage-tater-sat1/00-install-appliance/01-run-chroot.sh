#!/bin/bash -e

export DEBIAN_FRONTEND=noninteractive
IMAGE_FLAVOR="$(cat /tmp/tater-sat1-image-flavor)"
WIFI_COUNTRY="$(cat /tmp/tater-sat1-wifi-country)"
FIRMWARE_VERSION="$(cat /tmp/tater-sat1-firmware-version)"

apt-get install -y /tmp/sat1-assets/*.deb

# The v0.1.4 SDK package ships with the internal speaker disabled. This image
# is an appliance, so initialise the built-in TAS2780 speaker by default.
sed -i \
    -e 's/^enabled = false$/enabled = true/' \
    -e 's/^startup_muted = true$/startup_muted = false/' \
    /etc/satellite1.conf

# Keep PWM0 on BCM GPIO 12 available for the optional direct-GPIO LED backend.
# Production SAT1 images use the XMOS/SPI backend selected in config.toml.
if ! grep -qxF 'dtoverlay=pwm,pin=12,func=4' /boot/firmware/config.txt; then
    printf '\n%s\n' 'dtoverlay=pwm,pin=12,func=4' >> /boot/firmware/config.txt
fi

TATER_SAT1_VERSION="${FIRMWARE_VERSION}" /opt/tater-sat1-standalone-src/script/install \
    --flavor "${IMAGE_FLAVOR}" \
    --bundled-sources \
    --defer-init \
    --no-enable \
    --skip-apt

# The image owns its audio server. Linux Satellite's soundcard backend uses
# this private PulseAudio socket while mpv handles response playback through
# the same server.
sed -i \
    's|^pulse_server = .*|pulse_server = "unix:/run/tater-sat1-audio/pulse/native"|' \
    /etc/tater-sat1-standalone/config.toml
sed -i \
    "s/^TATER_SETUP_WIFI_COUNTRY=.*/TATER_SETUP_WIFI_COUNTRY=${WIFI_COUNTRY}/" \
    /etc/default/tater-sat1-setup
if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_wifi_country "${WIFI_COUNTRY}" || true
fi
systemctl disable hostapd.service 2>/dev/null || true
test -x /usr/local/sbin/tater-sat1-setup-hotspot
test -x /usr/local/sbin/tater-sat1-apply-update
test -x /usr/local/sbin/tater-sat1-update-health
test -x /opt/tater-sat1/venv/bin/tater-sat1-provisioning
test -x /opt/tater-sat1/venv/bin/tater-sat1-voice
test -x /opt/tater-sat1/venv/bin/tater-sat1-leds
test -x /opt/tater-sat1/venv/bin/tater-sat1-xmos-firmware
test -s /opt/tater-sat1/firmware/xmos/sat1_xmos_1_1_1_factory.bin
test -x /usr/sbin/flashrom
test -x /usr/local/sbin/tater-sat1-audio-watchdog
test -x /usr/local/sbin/tater-sat1-audio-hardware
test -s /etc/tater-sat1-standalone/pulse.pa
grep -qxF 'i2c-dev' /etc/modules-load.d/tater-sat1-i2c.conf
grep -qxF 'wifi.powersave = 2' /etc/NetworkManager/conf.d/90-tater-sat1-wifi-powersave.conf
grep -qxF 'dtoverlay=pwm,pin=12,func=4' /boot/firmware/config.txt
grep -q '^enabled = true$' /etc/satellite1.conf
grep -q '^startup_muted = false$' /etc/satellite1.conf
grep -q '^audio_input_device = "satellite1_input"$' /etc/tater-sat1-standalone/config.toml
grep -q '^audio_output_device = "pulse/satellite1_output"$' /etc/tater-sat1-standalone/config.toml
grep -q '^backend = "xmos"$' /etc/tater-sat1-standalone/config.toml
if [ "${IMAGE_FLAVOR}" = "standalone" ]; then
    /opt/tater/venv/bin/python -c 'import websockets'
    test -s /opt/tater/app/.tater-sat1-build.json
    test -x /opt/tater-sat1/venv/bin/tater-sat1-app-update
    test -s /etc/default/tater-sat1-app-update
fi
test -s /etc/tater-sat1-standalone/update-public.pem
test "$(cat /etc/tater-sat1-standalone/version)" = "${FIRMWARE_VERSION}"
test ! -L /etc/systemd/system/multi-user.target.wants/hostapd.service
grep -q "^TATER_SETUP_WIFI_COUNTRY=${WIFI_COUNTRY}$" /etc/default/tater-sat1-setup

if [ "${IMAGE_FLAVOR}" = "standalone" ]; then
    # Tater starts a private Redis instance from the packaged binary. Do not
    # also run Debian's system-wide instance on a 512 MB appliance.
    systemctl disable redis-server.service 2>/dev/null || true
fi

# Prefer compressed RAM swap to writes on the microSD card.
if [ -f /etc/default/zramswap ]; then
    sed -i \
        -e 's/^#\?ALGO=.*/ALGO=zstd/' \
        -e 's/^#\?PERCENT=.*/PERCENT=50/' \
        -e 's/^#\?PRIORITY=.*/PRIORITY=100/' \
        /etc/default/zramswap
fi
systemctl enable zramswap.service 2>/dev/null || true
systemctl disable dphys-swapfile.service 2>/dev/null || true

install -d /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/tater-sat1.conf <<'EOF'
[Journal]
SystemMaxUse=64M
RuntimeMaxUse=32M
MaxRetentionSec=7day
EOF

# Every flashed device creates its native-satellite credential on first boot.
test ! -e /var/lib/tater-sat1-standalone/native-satellite-token
systemctl enable satellite1-init.service 2>/dev/null || true
systemctl enable tater-sat1-update.path tater-sat1-update-health.service tater-sat1-audio-watchdog.timer tater-sat1-xmos.service
if [ "${IMAGE_FLAVOR}" = "standalone" ]; then
    grep -q '^board = "satellite1_rpi_standalone"$' /etc/tater-sat1-standalone/config.toml
    systemctl enable \
        tater-sat1-firstboot.service \
        tater-sat1-provisioning.service \
        tater-sat1-audio.service \
        tater-sat1-leds.service \
        tater-sat1-tater.service \
        tater-sat1-voice.service \
        tater-sat1-app-update.timer
else
    grep -q '^board = "satellite1_rpi_satellite"$' /etc/tater-sat1-standalone/config.toml
    test ! -e /opt/tater/app/tateros_app.py
    systemctl enable \
        tater-sat1-firstboot.service \
        tater-sat1-provisioning.service \
        tater-sat1-audio.service \
        tater-sat1-leds.service \
        tater-sat1-satellite.service
fi
test -L /etc/systemd/system/multi-user.target.wants/tater-sat1-provisioning.service
test -L /etc/systemd/system/multi-user.target.wants/tater-sat1-xmos.service
test -L /etc/systemd/system/multi-user.target.wants/tater-sat1-leds.service
test -L /etc/systemd/system/multi-user.target.wants/tater-sat1-update.path
test -L /etc/systemd/system/multi-user.target.wants/tater-sat1-update-health.service
test -L /etc/systemd/system/timers.target.wants/tater-sat1-audio-watchdog.timer
if [ "${IMAGE_FLAVOR}" = "standalone" ]; then
    test -L /etc/systemd/system/timers.target.wants/tater-sat1-app-update.timer
fi

rm -rf \
    /opt/tater-sat1/linux-satellite/.git \
    /tmp/tater-sat1-image-flavor \
    /tmp/tater-sat1-wifi-country \
    /tmp/sat1-assets
apt-get clean
rm -rf /var/lib/apt/lists/*
