#!/usr/bin/env bash
# Build a ready-to-flash Raspberry Pi OS image for Tater + Satellite1.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_LOCK="${REPO_ROOT}/packaging/image.lock"
UPSTREAMS_MANIFEST="${REPO_ROOT}/upstreams.toml"

# shellcheck disable=SC1090
source "${IMAGE_LOCK}"

PI_GEN_DIR="${PI_GEN_DIR:-${REPO_ROOT}/.cache/pi-gen-bookworm-arm64}"
PI_GEN_CONFIG="${PI_GEN_CONFIG:-${PI_GEN_DIR}/config}"
PI_IMAGE_NAME="${PI_IMAGE_NAME:-tater-sat1-standalone}"
PI_IMAGE_RELEASE="bookworm"
PI_IMAGE_ROOT_MARGIN_MB="${PI_IMAGE_ROOT_MARGIN_MB:-2048}"
PI_FIRST_USER_NAME="${PI_FIRST_USER_NAME:-tater}"
PI_FIRST_USER_PASS="${PI_FIRST_USER_PASS-tater}"
PI_FIRST_USER_PUBKEY="${PI_FIRST_USER_PUBKEY:-}"
PI_PUBKEY_ONLY_SSH="${PI_PUBKEY_ONLY_SSH:-0}"
PI_ENABLE_SSH="${PI_ENABLE_SSH:-1}"
PI_WIFI_SSID="${PI_WIFI_SSID:-}"
PI_WIFI_PASSWORD="${PI_WIFI_PASSWORD:-}"
PI_WIFI_COUNTRY="${PI_WIFI_COUNTRY:-US}"
PI_TIMEZONE="${PI_TIMEZONE:-America/Chicago}"
PI_LOCALE="${PI_LOCALE:-en_US.UTF-8}"
PI_KEYBOARD="${PI_KEYBOARD:-us}"
PI_ASSET_DIR="${PI_ASSET_DIR:-${REPO_ROOT}/.cache/sat1-release-${SAT1_RELEASE_TAG}}"
PI_ALLOW_DIRTY_SOURCES="${PI_ALLOW_DIRTY_SOURCES:-0}"

PLAN_ONLY=0
PREPARE_ONLY=0

usage() {
    cat <<'EOF'
Usage: scripts/build-pi-image.sh [--plan] [--prepare-only]

  --plan          Print the immutable image inputs without downloading/building.
  --prepare-only  Resolve source trees and verify downloaded SAT1 packages.

The full build requires Git, curl, Docker, and enough free disk for pi-gen.
Output is written under .cache/pi-gen-bookworm-arm64/deploy/.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --plan) PLAN_ONLY=1 ;;
        --prepare-only) PREPARE_ONLY=1 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf 'Missing required command: %s\n' "$1" >&2
        exit 1
    fi
}

if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN=python3.11
else
    PYTHON_BIN=python3
fi

manifest_value() {
    "${PYTHON_BIN}" -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))[sys.argv[2]][sys.argv[3]])' "${UPSTREAMS_MANIFEST}" "$1" "$2"
}

TATER_URL="$(manifest_value tater url)"
TATER_REVISION="$(manifest_value tater reference_revision)"
SATELLITE_URL="$(manifest_value linux_satellite url)"
SATELLITE_REVISION="$(manifest_value linux_satellite reference_revision)"
TATER_SOURCE_DIR="${TATER_SOURCE_DIR:-}"
SATELLITE_SOURCE_DIR="${SATELLITE_SOURCE_DIR:-}"

print_plan() {
    cat <<EOF
image_name=${PI_IMAGE_NAME}
base_release=${PI_IMAGE_RELEASE}
pi_gen_ref=${PI_GEN_REF}
pi_gen_revision=${PI_GEN_REVISION}
sat1_release=${SAT1_RELEASE_TAG}
tater_revision=${TATER_REVISION}
linux_satellite_revision=${SATELLITE_REVISION}
compression=xz
first_boot_token=unique
output=${PI_GEN_DIR}/deploy
EOF
}

if [ "${PLAN_ONLY}" = "1" ]; then
    print_plan
    exit 0
fi

require_cmd git
require_cmd curl
require_cmd "${PYTHON_BIN}"

case "${REPO_ROOT}:${PI_GEN_DIR}" in
    *" "*)
        printf 'pi-gen paths must not contain spaces: %s\n' "${REPO_ROOT}:${PI_GEN_DIR}" >&2
        exit 1
        ;;
esac

sha256_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

fetch_asset() {
    local filename="$1"
    local expected="$2"
    local target="${PI_ASSET_DIR}/${filename}"
    local actual=""

    if [ -f "${target}" ]; then
        actual="$(sha256_file "${target}")"
    fi
    if [ "${actual}" != "${expected}" ]; then
        rm -f "${target}"
        curl -fL --retry 3 --connect-timeout 20 \
            "${SAT1_RELEASE_BASE}/${filename}" -o "${target}"
        actual="$(sha256_file "${target}")"
    fi
    if [ "${actual}" != "${expected}" ]; then
        printf 'Checksum mismatch for %s: expected %s, got %s\n' "${filename}" "${expected}" "${actual}" >&2
        exit 1
    fi
    printf 'verified %s\n' "${filename}"
}

assert_source() {
    local label="$1"
    local path="$2"
    local revision="$3"
    local actual=""

    [ -d "${path}/.git" ] || { printf '%s source is not a Git checkout: %s\n' "${label}" "${path}" >&2; exit 1; }
    actual="$(git -C "${path}" rev-parse HEAD)"
    [ "${actual}" = "${revision}" ] || {
        printf '%s source revision mismatch: expected %s, got %s\n' "${label}" "${revision}" "${actual}" >&2
        exit 1
    }
    if [ "${PI_ALLOW_DIRTY_SOURCES}" != "1" ] && [ -n "$(git -C "${path}" status --porcelain)" ]; then
        printf '%s source has uncommitted changes: %s\n' "${label}" "${path}" >&2
        exit 1
    fi
}

checkout_pinned() {
    local label="$1"
    local url="$2"
    local revision="$3"
    local destination="$4"

    if [ ! -d "${destination}/.git" ]; then
        rm -rf "${destination}"
        git clone --no-checkout "${url}" "${destination}"
    fi
    git -C "${destination}" fetch --depth 1 origin "${revision}"
    git -C "${destination}" checkout --detach FETCH_HEAD
    assert_source "${label}" "${destination}" "${revision}"
}

resolve_source() {
    local label="$1"
    local configured="$2"
    local sibling="$3"
    local url="$4"
    local revision="$5"
    local cache="$6"

    if [ -n "${configured}" ]; then
        assert_source "${label}" "${configured}" "${revision}"
        (cd "${configured}" && pwd -P)
        return
    fi
    if [ -d "${sibling}/.git" ] && [ "$(git -C "${sibling}" rev-parse HEAD 2>/dev/null || true)" = "${revision}" ]; then
        assert_source "${label}" "${sibling}" "${revision}"
        (cd "${sibling}" && pwd -P)
        return
    fi
    checkout_pinned "${label}" "${url}" "${revision}" "${cache}" >&2
    (cd "${cache}" && pwd -P)
}

mkdir -p "${PI_ASSET_DIR}" "${REPO_ROOT}/.cache/upstreams"
fetch_asset "${SAT1_KERNEL_FILE}" "${SAT1_KERNEL_SHA256}"
fetch_asset "${SAT1_SETUP_FILE}" "${SAT1_SETUP_SHA256}"
fetch_asset "${SAT1_SDK_FILE}" "${SAT1_SDK_SHA256}"

TATER_SOURCE_DIR="$(resolve_source Tater "${TATER_SOURCE_DIR}" "${REPO_ROOT}/../Tater" "${TATER_URL}" "${TATER_REVISION}" "${REPO_ROOT}/.cache/upstreams/Tater")"
SATELLITE_SOURCE_DIR="$(resolve_source "Linux Satellite" "${SATELLITE_SOURCE_DIR}" "${REPO_ROOT}/../Tater-Linux-Satellite" "${SATELLITE_URL}" "${SATELLITE_REVISION}" "${REPO_ROOT}/.cache/upstreams/Tater-Linux-Satellite")"

if [ "${PI_ALLOW_DIRTY_SOURCES}" != "1" ] && [ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]; then
    printf 'Standalone source has uncommitted changes: %s\n' "${REPO_ROOT}" >&2
    exit 1
fi

if [ "${PREPARE_ONLY}" = "1" ]; then
    print_plan
    printf 'tater_source=%s\n' "${TATER_SOURCE_DIR}"
    printf 'linux_satellite_source=%s\n' "${SATELLITE_SOURCE_DIR}"
    printf 'sat1_assets=%s\n' "${PI_ASSET_DIR}"
    exit 0
fi

require_cmd docker

mkdir -p "$(dirname "${PI_GEN_DIR}")" "$(dirname "${PI_GEN_CONFIG}")"
if [ ! -d "${PI_GEN_DIR}/.git" ]; then
    git clone --no-checkout "${PI_GEN_REPOSITORY}" "${PI_GEN_DIR}"
fi
git -C "${PI_GEN_DIR}" fetch --depth 1 origin "${PI_GEN_REF}"
git -C "${PI_GEN_DIR}" checkout --detach FETCH_HEAD
[ "$(git -C "${PI_GEN_DIR}" rev-parse HEAD)" = "${PI_GEN_REVISION}" ] || {
    printf 'pi-gen revision did not match image.lock\n' >&2
    exit 1
}

CUSTOM_STAGE="${PI_GEN_DIR}/stage-tater-sat1"
rm -rf "${CUSTOM_STAGE}"
cp -R "${SCRIPT_DIR}/pi-image/stage-tater-sat1" "${CUSTOM_STAGE}"
chmod +x "${CUSTOM_STAGE}"/00-install-appliance/*.sh
touch "${PI_GEN_DIR}/stage2/SKIP_IMAGES"
rm -f "${CUSTOM_STAGE}/SKIP_IMAGES"

: > "${PI_GEN_CONFIG}"
write_config_value() {
    printf '%s=%q\n' "$1" "$2" >> "${PI_GEN_CONFIG}"
}
load_pubkey() {
    if [ -n "$1" ] && [ -f "$1" ]; then cat "$1"; else printf '%s' "$1"; fi
}

write_config_value IMG_NAME "${PI_IMAGE_NAME}"
write_config_value RELEASE "${PI_IMAGE_RELEASE}"
write_config_value STAGE_LIST "stage0 stage1 stage2 stage-tater-sat1"
write_config_value DEPLOY_COMPRESSION "xz"
write_config_value TARGET_HOSTNAME "tater-sat1"
write_config_value ENABLE_SSH "${PI_ENABLE_SSH}"
write_config_value FIRST_USER_NAME "${PI_FIRST_USER_NAME}"
write_config_value LOCALE_DEFAULT "${PI_LOCALE}"
write_config_value KEYBOARD_KEYMAP "${PI_KEYBOARD}"
write_config_value TIMEZONE_DEFAULT "${PI_TIMEZONE}"
if [ -n "${PI_FIRST_USER_PASS}" ]; then
    write_config_value FIRST_USER_PASS "${PI_FIRST_USER_PASS}"
    write_config_value DISABLE_FIRST_BOOT_USER_RENAME "1"
fi
if [ -n "${PI_FIRST_USER_PUBKEY}" ]; then
    write_config_value PUBKEY_SSH_FIRST_USER "$(load_pubkey "${PI_FIRST_USER_PUBKEY}")"
    write_config_value PUBKEY_ONLY_SSH "${PI_PUBKEY_ONLY_SSH}"
    write_config_value DISABLE_FIRST_BOOT_USER_RENAME "1"
fi
if [ -n "${PI_WIFI_SSID}" ]; then
    write_config_value WPA_ESSID "${PI_WIFI_SSID}"
    write_config_value WPA_PASSWORD "${PI_WIFI_PASSWORD}"
    write_config_value WPA_COUNTRY "${PI_WIFI_COUNTRY}"
fi

patch_export_margin() {
    local prerun="${PI_GEN_DIR}/export-image/prerun.sh"
    local temporary="${prerun}.tmp"
    awk -v margin="${PI_IMAGE_ROOT_MARGIN_MB}" '
        /^ROOT_MARGIN=/ {
            print "ROOT_MARGIN=\"$(echo \"($ROOT_SIZE * 0.2 + " margin " * 1024 * 1024) / 1\" | bc)\""
            next
        }
        { print }
    ' "${prerun}" > "${temporary}"
    mv "${temporary}" "${prerun}"
    chmod +x "${prerun}"
}
patch_export_margin

export PIGEN_DOCKER_OPTS="${PIGEN_DOCKER_OPTS:-} --mount type=bind,source=${REPO_ROOT},target=/tater-sat1-src,readonly --mount type=bind,source=${TATER_SOURCE_DIR},target=/tater-src,readonly --mount type=bind,source=${SATELLITE_SOURCE_DIR},target=/linux-satellite-src,readonly --mount type=bind,source=${PI_ASSET_DIR},target=/sat1-assets,readonly -e TATER_SAT1_SOURCE_DIR=/tater-sat1-src -e TATER_SOURCE_DIR=/tater-src -e LINUX_SATELLITE_SOURCE_DIR=/linux-satellite-src -e SAT1_ASSET_DIR=/sat1-assets"

print_plan
printf 'Building with Tater source: %s\n' "${TATER_SOURCE_DIR}"
printf 'Building with Linux Satellite source: %s\n' "${SATELLITE_SOURCE_DIR}"
printf 'Initial SSH login: %s (change the image password for non-lab use)\n' "${PI_FIRST_USER_NAME}"

(
    cd "${PI_GEN_DIR}"
    ./build-docker.sh
)

DEPLOY_DIR="${PI_GEN_DIR}/deploy"
IMAGE_FOUND=0
: > "${DEPLOY_DIR}/SHA256SUMS.txt"
for image_path in "${DEPLOY_DIR}"/image_*.img.xz; do
    [ -f "${image_path}" ] || continue
    IMAGE_FOUND=1
    printf '%s  %s\n' \
        "$(sha256_file "${image_path}")" \
        "$(basename "${image_path}")" >> "${DEPLOY_DIR}/SHA256SUMS.txt"
done
[ "${IMAGE_FOUND}" = "1" ] || {
    printf 'pi-gen completed without producing an image in %s\n' "${DEPLOY_DIR}" >&2
    exit 1
}

printf '\nImage build complete: %s/deploy\n' "${PI_GEN_DIR}"
