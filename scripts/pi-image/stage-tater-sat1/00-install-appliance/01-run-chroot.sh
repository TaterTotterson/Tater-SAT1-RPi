#!/bin/bash -e

export DEBIAN_FRONTEND=noninteractive

apt-get install -y /tmp/sat1-assets/*.deb

/opt/tater-sat1-standalone-src/script/install \
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

# Tater starts a private Redis instance from the packaged binary. Do not also
# run Debian's system-wide instance on a 512 MB appliance.
systemctl disable redis-server.service 2>/dev/null || true

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
systemctl enable \
    tater-sat1-firstboot.service \
    tater-sat1-audio.service \
    tater-sat1-tater.service \
    tater-sat1-voice.service

rm -rf \
    /opt/tater-sat1-standalone-src \
    /opt/tater-sat1/linux-satellite/.git \
    /tmp/sat1-assets
apt-get clean
rm -rf /var/lib/apt/lists/*
