#!/bin/bash -e

IMAGE_FLAVOR="${TATER_SAT1_IMAGE_FLAVOR:-standalone}"
FIRMWARE_VERSION="${TATER_SAT1_FIRMWARE_VERSION:-tater-sat1-${IMAGE_FLAVOR}-development}"
RELEASE_VERSION="${TATER_SAT1_RELEASE_VERSION:-development}"
PRIVATE_KEY="${TATER_SAT1_OTA_PRIVATE_KEY:-/tater-sat1-ota-private.pem}"
SOURCE_ROOT="${TATER_SAT1_SOURCE_DIR:-/tater-sat1-src}"
OUTPUT="${DEPLOY_DIR}/tater-sat1-${IMAGE_FLAVOR}-${RELEASE_VERSION}-ota.sat1"
CHROOT_KEY="${ROOTFS_DIR}/tmp/tater-sat1-ota-private.pem"
CHROOT_OUTPUT="${ROOTFS_DIR}/tmp/tater-sat1-update.sat1"

cleanup() {
    rm -f "${CHROOT_KEY}" "${CHROOT_OUTPUT}" "${ROOTFS_DIR}/tmp/tater-sat1-firmware-version"
    rm -rf "${ROOTFS_DIR}/opt/tater-sat1-standalone-src"
}
trap cleanup EXIT

test -r "${PRIVATE_KEY}"
test -d "${SOURCE_ROOT}"
install -m 0600 "${PRIVATE_KEY}" "${CHROOT_KEY}"
on_chroot <<EOF
python3 /opt/tater-sat1-standalone-src/script/build_ota_bundle.py \
    --rootfs / \
    --flavor "${IMAGE_FLAVOR}" \
    --version "${FIRMWARE_VERSION}" \
    --private-key /tmp/tater-sat1-ota-private.pem \
    --output /tmp/tater-sat1-update.sat1
EOF

mv "${CHROOT_OUTPUT}" "${OUTPUT}"
