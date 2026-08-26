#!/bin/bash -e

STANDALONE_SOURCE="${TATER_SAT1_SOURCE_DIR:-/tater-sat1-src}"
TATER_SOURCE="${TATER_SOURCE_DIR:-/tater-src}"
SATELLITE_SOURCE="${LINUX_SATELLITE_SOURCE_DIR:-/linux-satellite-src}"
HARDWARE_ASSETS="${SAT1_ASSET_DIR:-/sat1-assets}"

IMAGE_FLAVOR="${TATER_SAT1_IMAGE_FLAVOR:-standalone}"

for source_path in "${STANDALONE_SOURCE}" "${SATELLITE_SOURCE}" "${HARDWARE_ASSETS}"; do
    if [ ! -d "${source_path}" ]; then
        printf 'Image input is missing: %s\n' "${source_path}" >&2
        exit 1
    fi
done
if [ "${IMAGE_FLAVOR}" = "standalone" ] && [ ! -d "${TATER_SOURCE}" ]; then
    printf 'Image input is missing: %s\n' "${TATER_SOURCE}" >&2
    exit 1
fi

copy_source() {
    local source_path="$1"
    local target_path="$2"
    local keep_git="${3:-0}"
    local git_exclude=()
    if [ "${keep_git}" != "1" ]; then
        git_exclude=(--exclude=.git)
    fi
    install -d "${target_path}"
    tar \
        "${git_exclude[@]}" \
        --exclude=.cache \
        --exclude=.venv \
        --exclude=.runtime \
        --exclude=agent_lab \
        --exclude=build \
        --exclude=dist \
        --exclude=__pycache__ \
        --exclude='*.dmg' \
        --exclude='*.img' \
        --exclude='*.img.xz' \
        -C "${source_path}" -cf - . | tar -C "${target_path}" -xf -
}

copy_source "${STANDALONE_SOURCE}" "${ROOTFS_DIR}/opt/tater-sat1-standalone-src"
if [ "${IMAGE_FLAVOR}" = "standalone" ]; then
    copy_source "${TATER_SOURCE}" "${ROOTFS_DIR}/opt/tater/app"
fi
# setuptools-scm needs Git metadata while the editable satellite package is
# installed. The chroot stage removes it after installation.
copy_source "${SATELLITE_SOURCE}" "${ROOTFS_DIR}/opt/tater-sat1/linux-satellite" 1

install -d "${ROOTFS_DIR}/tmp/sat1-assets"
cp -a "${HARDWARE_ASSETS}/." "${ROOTFS_DIR}/tmp/sat1-assets/"
printf '%s\n' "${IMAGE_FLAVOR}" > "${ROOTFS_DIR}/tmp/tater-sat1-image-flavor"
printf '%s\n' "${TATER_SAT1_WIFI_COUNTRY:-US}" > "${ROOTFS_DIR}/tmp/tater-sat1-wifi-country"
printf '%s\n' "${TATER_SAT1_FIRMWARE_VERSION:-tater-sat1-${IMAGE_FLAVOR}-development}" > "${ROOTFS_DIR}/tmp/tater-sat1-firmware-version"
