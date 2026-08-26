#!/bin/bash -e

IMAGE_FLAVOR="${TATER_SAT1_IMAGE_FLAVOR:-standalone}"
FIRMWARE_VERSION="${TATER_SAT1_FIRMWARE_VERSION:-tater-sat1-${IMAGE_FLAVOR}-development}"
RELEASE_VERSION="${TATER_SAT1_RELEASE_VERSION:-development}"
PRIVATE_KEY="${TATER_SAT1_OTA_PRIVATE_KEY:-/tater-sat1-ota-private.pem}"
SOURCE_ROOT="${TATER_SAT1_SOURCE_DIR:-/tater-sat1-src}"
OUTPUT="${DEPLOY_DIR}/tater-sat1-${IMAGE_FLAVOR}-${RELEASE_VERSION}-ota.sat1"

test -r "${PRIVATE_KEY}"
python3 "${SOURCE_ROOT}/script/build_ota_bundle.py" \
    --rootfs "${ROOTFS_DIR}" \
    --flavor "${IMAGE_FLAVOR}" \
    --version "${FIRMWARE_VERSION}" \
    --private-key "${PRIVATE_KEY}" \
    --output "${OUTPUT}"

rm -f "${ROOTFS_DIR}/tmp/tater-sat1-firmware-version"
