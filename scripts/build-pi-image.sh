#!/usr/bin/env bash
# Build ready-to-flash Raspberry Pi OS images for Satellite1.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_LOCK="${REPO_ROOT}/packaging/image.lock"
UPSTREAMS_MANIFEST="${REPO_ROOT}/upstreams.toml"

# shellcheck disable=SC1090
source "${IMAGE_LOCK}"

PI_GEN_DIR="${PI_GEN_DIR:-${REPO_ROOT}/.cache/pi-gen-bookworm-arm64}"
PI_GEN_CONFIG="${PI_GEN_CONFIG:-${PI_GEN_DIR}/config}"
PI_IMAGE_FLAVOR="${PI_IMAGE_FLAVOR:-standalone}"
PI_IMAGE_NAME="${PI_IMAGE_NAME:-}"
PI_IMAGE_RELEASE="bookworm"
PI_IMAGE_ROOT_MARGIN_MB="${PI_IMAGE_ROOT_MARGIN_MB:-2048}"
PI_FIRST_USER_PASS_WAS_SET=0
if [ "${PI_FIRST_USER_PASS+x}" = "x" ]; then
    PI_FIRST_USER_PASS_WAS_SET=1
fi
PI_FIRST_USER_NAME="${PI_FIRST_USER_NAME:-tater}"
PI_FIRST_USER_PASS="${PI_FIRST_USER_PASS:-tater}"
PI_FIRST_USER_PUBKEY="${PI_FIRST_USER_PUBKEY:-}"
PI_PUBKEY_ONLY_SSH="${PI_PUBKEY_ONLY_SSH:-1}"
PI_ENABLE_SSH="${PI_ENABLE_SSH:-0}"
PI_WIFI_SSID="${PI_WIFI_SSID:-}"
PI_WIFI_PASSWORD="${PI_WIFI_PASSWORD:-}"
PI_WIFI_COUNTRY="${PI_WIFI_COUNTRY:-US}"
PI_TIMEZONE="${PI_TIMEZONE:-America/Chicago}"
PI_LOCALE="${PI_LOCALE:-en_US.UTF-8}"
PI_KEYBOARD="${PI_KEYBOARD:-us}"
PI_ASSET_DIR="${PI_ASSET_DIR:-${REPO_ROOT}/.cache/sat1-release-${SAT1_RELEASE_TAG}}"
PI_ALLOW_DIRTY_SOURCES="${PI_ALLOW_DIRTY_SOURCES:-0}"
PI_RELEASE_VERSION="${PI_RELEASE_VERSION:-$(git -C "${REPO_ROOT}" describe --tags --always --dirty 2>/dev/null || printf '%s' development)}"
TATER_SAT1_FIRMWARE_VERSION="tater-sat1-${PI_IMAGE_FLAVOR}-${PI_RELEASE_VERSION}"
TATER_SAT1_OTA_PRIVATE_KEY_FILE="${TATER_SAT1_OTA_PRIVATE_KEY_FILE:-${REPO_ROOT}/.secrets/tater-sat1-ota-private.pem}"
TATER_SAT1_OTA_PRIVATE_KEY_CACHE="${REPO_ROOT}/.cache/ota-signing/private.pem"

PLAN_ONLY=0
PREPARE_ONLY=0

usage() {
    cat <<'EOF'
Usage: scripts/build-pi-image.sh [--flavor standalone|satellite] [--plan] [--prepare-only]

  --flavor NAME   Build the all-in-one standalone or fleet satellite image.
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
        --flavor)
            [ "$#" -ge 2 ] || { printf '%s\n' "--flavor requires a value" >&2; exit 2; }
            PI_IMAGE_FLAVOR="$2"
            shift
            ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

case "${PI_IMAGE_FLAVOR}" in
    standalone|satellite) ;;
    *) printf 'Unknown image flavor: %s\n' "${PI_IMAGE_FLAVOR}" >&2; exit 2 ;;
esac
case "${PI_ENABLE_SSH}" in
    0|1) ;;
    *) printf 'PI_ENABLE_SSH must be 0 or 1\n' >&2; exit 2 ;;
esac
case "${PI_PUBKEY_ONLY_SSH}" in
    0|1) ;;
    *) printf 'PI_PUBKEY_ONLY_SSH must be 0 or 1\n' >&2; exit 2 ;;
esac
if [ "${PI_ENABLE_SSH}" = "1" ] && [ "${PI_FIRST_USER_PASS_WAS_SET}" != "1" ] && [ -z "${PI_FIRST_USER_PUBKEY}" ]; then
    printf '%s\n' 'PI_ENABLE_SSH=1 requires an explicit PI_FIRST_USER_PASS or PI_FIRST_USER_PUBKEY.' >&2
    exit 2
fi
if [[ ! "${PI_RELEASE_VERSION}" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$ ]]; then
    printf 'Invalid image release version: %s\n' "${PI_RELEASE_VERSION}" >&2
    exit 2
fi
TATER_SAT1_FIRMWARE_VERSION="tater-sat1-${PI_IMAGE_FLAVOR}-${PI_RELEASE_VERSION}"
if [ -z "${PI_IMAGE_NAME}" ]; then
    PI_IMAGE_NAME="tater-sat1-${PI_IMAGE_FLAVOR}"
fi

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
TATER_REFERENCE="$(manifest_value tater reference)"
TATER_UPDATE_POLICY="$(manifest_value tater update_policy)"
SATELLITE_URL="$(manifest_value linux_satellite url)"
SATELLITE_REVISION="$(manifest_value linux_satellite reference_revision)"
XMOS_VERSION="$(manifest_value tater_native_xmos version)"
XMOS_SHA256="$(manifest_value tater_native_xmos sha256)"
TATER_SOURCE_DIR="${TATER_SOURCE_DIR:-}"
SATELLITE_SOURCE_DIR="${SATELLITE_SOURCE_DIR:-}"
TATER_REVISION="${TATER_REVISION_OVERRIDE:-}"

print_plan() {
    if [ "${PI_IMAGE_FLAVOR}" = "standalone" ]; then
        identity_plan="unique_local_token"
        tater_plan="${TATER_REVISION:-latest:${TATER_REFERENCE}}"
    else
        identity_plan="unique_device_pairing"
        tater_plan="not_bundled"
    fi
    cat <<EOF
image_name=${PI_IMAGE_NAME}
image_flavor=${PI_IMAGE_FLAVOR}
base_release=${PI_IMAGE_RELEASE}
pi_gen_ref=${PI_GEN_REF}
pi_gen_revision=${PI_GEN_REVISION}
sat1_release=${SAT1_RELEASE_TAG}
tater_revision=${tater_plan}
tater_update_policy=${TATER_UPDATE_POLICY}
linux_satellite_revision=${SATELLITE_REVISION}
xmos_firmware=${XMOS_VERSION}
xmos_sha256=${XMOS_SHA256}
compression=xz
release_version=${PI_RELEASE_VERSION}
firmware_version=${TATER_SAT1_FIRMWARE_VERSION}
ota_format=tater_sat1_signed_bundle_v1
first_boot_identity=${identity_plan}
ssh_enabled=${PI_ENABLE_SSH}
ssh_admin_user=${PI_FIRST_USER_NAME}
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

resolve_remote_revision() {
    local label="$1"
    local url="$2"
    local reference="$3"
    local revision=""

    git check-ref-format --branch "${reference}" >/dev/null 2>&1 || {
        printf '%s branch name is invalid: %s\n' "${label}" "${reference}" >&2
        exit 1
    }
    revision="$(git ls-remote --exit-code "${url}" "refs/heads/${reference}" | awk 'NR == 1 {print $1}')"
    [[ "${revision}" =~ ^[0-9a-f]{40}$ ]] || {
        printf 'Could not resolve %s branch %s from %s\n' "${label}" "${reference}" "${url}" >&2
        exit 1
    }
    printf '%s\n' "${revision}"
}

if [ "${PI_IMAGE_FLAVOR}" = "standalone" ] && [ -z "${TATER_REVISION}" ]; then
    TATER_REVISION="$(resolve_remote_revision Tater "${TATER_URL}" "${TATER_REFERENCE}")"
fi

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

if [ "${PI_IMAGE_FLAVOR}" = "standalone" ]; then
    TATER_SOURCE_DIR="$(resolve_source Tater "${TATER_SOURCE_DIR}" "${REPO_ROOT}/../Tater" "${TATER_URL}" "${TATER_REVISION}" "${REPO_ROOT}/.cache/upstreams/Tater")"
    TATER_PREPARED_DIR="${REPO_ROOT}/.cache/prepared/Tater-${TATER_REVISION}"
    "${PYTHON_BIN}" "${REPO_ROOT}/script/prepare_tater_source.py" \
        --source "${TATER_SOURCE_DIR}" \
        --destination "${TATER_PREPARED_DIR}" \
        --revision "${TATER_REVISION}" >&2
    TATER_SOURCE_DIR="${TATER_PREPARED_DIR}"
fi
SATELLITE_SOURCE_DIR="$(resolve_source "Linux Satellite" "${SATELLITE_SOURCE_DIR}" "${REPO_ROOT}/../Tater-Linux-Satellite" "${SATELLITE_URL}" "${SATELLITE_REVISION}" "${REPO_ROOT}/.cache/upstreams/Tater-Linux-Satellite")"

if [ "${PI_ALLOW_DIRTY_SOURCES}" != "1" ] && [ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]; then
    printf 'Standalone source has uncommitted changes: %s\n' "${REPO_ROOT}" >&2
    exit 1
fi

if [ "${PREPARE_ONLY}" = "1" ]; then
    print_plan
    if [ "${PI_IMAGE_FLAVOR}" = "standalone" ]; then
        printf 'tater_source=%s\n' "${TATER_SOURCE_DIR}"
    fi
    printf 'linux_satellite_source=%s\n' "${SATELLITE_SOURCE_DIR}"
    printf 'sat1_assets=%s\n' "${PI_ASSET_DIR}"
    exit 0
fi

require_cmd docker
require_cmd openssl

prepare_signing_key() {
    local source_key="${TATER_SAT1_OTA_PRIVATE_KEY_FILE}"
    local derived_public="${REPO_ROOT}/.cache/ota-signing/public.pem"
    mkdir -p "$(dirname "${TATER_SAT1_OTA_PRIVATE_KEY_CACHE}")"
    umask 077
    if [ -n "${TATER_SAT1_OTA_PRIVATE_KEY_PEM:-}" ]; then
        printf '%s\n' "${TATER_SAT1_OTA_PRIVATE_KEY_PEM}" > "${TATER_SAT1_OTA_PRIVATE_KEY_CACHE}"
    else
        if [[ "${source_key}" != /* ]]; then
            source_key="${REPO_ROOT}/${source_key}"
        fi
        [ -r "${source_key}" ] || {
            printf '%s\n' 'No SAT1 OTA signing key was supplied.' >&2
            printf '%s\n' 'Set TATER_SAT1_OTA_PRIVATE_KEY_PEM, TATER_SAT1_OTA_PRIVATE_KEY_FILE, or run script/generate_development_ota_key.sh.' >&2
            exit 1
        }
        cp "${source_key}" "${TATER_SAT1_OTA_PRIVATE_KEY_CACHE}"
    fi
    chmod 0600 "${TATER_SAT1_OTA_PRIVATE_KEY_CACHE}"
    openssl rsa -in "${TATER_SAT1_OTA_PRIVATE_KEY_CACHE}" -check -noout >/dev/null
    openssl pkey -in "${TATER_SAT1_OTA_PRIVATE_KEY_CACHE}" -pubout -out "${derived_public}"
    cmp -s "${derived_public}" "${REPO_ROOT}/keys/update-public.pem" || {
        printf '%s\n' 'The OTA private key does not match keys/update-public.pem.' >&2
        exit 1
    }
}

prepare_signing_key

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
if [ "${PI_IMAGE_FLAVOR}" = "satellite" ]; then
    sed -i.bak '/^redis-server$/d' "${CUSTOM_STAGE}/00-install-appliance/00-packages"
    rm -f "${CUSTOM_STAGE}/00-install-appliance/00-packages.bak"
fi
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
write_config_value FIRST_USER_PASS "${PI_FIRST_USER_PASS}"
write_config_value DISABLE_FIRST_BOOT_USER_RENAME "1"
if [ -n "${PI_FIRST_USER_PUBKEY}" ]; then
    write_config_value PUBKEY_SSH_FIRST_USER "$(load_pubkey "${PI_FIRST_USER_PUBKEY}")"
    write_config_value PUBKEY_ONLY_SSH "${PI_PUBKEY_ONLY_SSH}"
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

PIGEN_MOUNTS="${PIGEN_DOCKER_OPTS:-} --mount type=bind,source=${REPO_ROOT},target=/tater-sat1-src,readonly --mount type=bind,source=${SATELLITE_SOURCE_DIR},target=/linux-satellite-src,readonly --mount type=bind,source=${PI_ASSET_DIR},target=/sat1-assets,readonly --mount type=bind,source=${TATER_SAT1_OTA_PRIVATE_KEY_CACHE},target=/tater-sat1-ota-private.pem,readonly -e TATER_SAT1_SOURCE_DIR=/tater-sat1-src -e LINUX_SATELLITE_SOURCE_DIR=/linux-satellite-src -e SAT1_ASSET_DIR=/sat1-assets -e TATER_SAT1_IMAGE_FLAVOR=${PI_IMAGE_FLAVOR} -e TATER_SAT1_WIFI_COUNTRY=${PI_WIFI_COUNTRY} -e TATER_SAT1_FIRMWARE_VERSION=${TATER_SAT1_FIRMWARE_VERSION} -e TATER_SAT1_RELEASE_VERSION=${PI_RELEASE_VERSION} -e TATER_SAT1_OTA_PRIVATE_KEY=/tater-sat1-ota-private.pem"
if [ "${PI_IMAGE_FLAVOR}" = "standalone" ]; then
    PIGEN_MOUNTS="${PIGEN_MOUNTS} --mount type=bind,source=${TATER_SOURCE_DIR},target=/tater-src,readonly -e TATER_SOURCE_DIR=/tater-src"
fi
export PIGEN_DOCKER_OPTS="${PIGEN_MOUNTS}"

print_plan
if [ "${PI_IMAGE_FLAVOR}" = "standalone" ]; then
    printf 'Building with Tater source: %s\n' "${TATER_SOURCE_DIR}"
else
    printf '%s\n' "Building fleet satellite without a bundled Tater server"
fi
printf 'Building with Linux Satellite source: %s\n' "${SATELLITE_SOURCE_DIR}"
if [ "${PI_ENABLE_SSH}" = "1" ]; then
    printf 'SSH enabled for administrator: %s\n' "${PI_FIRST_USER_NAME}"
else
    printf '%s\n' 'SSH disabled (enable it explicitly in Raspberry Pi Imager or at build time)'
fi

(
    cd "${PI_GEN_DIR}"
    ./build-docker.sh
)

DEPLOY_DIR="${PI_GEN_DIR}/deploy"
IMAGE_FOUND=0
OTA_FOUND=0
: > "${DEPLOY_DIR}/SHA256SUMS.txt"
for image_path in "${DEPLOY_DIR}"/image_*"${PI_IMAGE_NAME}".img.xz; do
    [ -f "${image_path}" ] || continue
    IMAGE_FOUND=1
    printf '%s  %s\n' \
        "$(sha256_file "${image_path}")" \
        "$(basename "${image_path}")" >> "${DEPLOY_DIR}/SHA256SUMS.txt"
done
for ota_path in "${DEPLOY_DIR}"/tater-sat1-"${PI_IMAGE_FLAVOR}"-*-ota.sat1; do
    [ -f "${ota_path}" ] || continue
    OTA_FOUND=1
    printf '%s  %s\n' \
        "$(sha256_file "${ota_path}")" \
        "$(basename "${ota_path}")" >> "${DEPLOY_DIR}/SHA256SUMS.txt"
done
[ "${IMAGE_FOUND}" = "1" ] || {
    printf 'pi-gen completed without producing an image in %s\n' "${DEPLOY_DIR}" >&2
    exit 1
}
[ "${OTA_FOUND}" = "1" ] || {
    printf 'pi-gen completed without producing a signed OTA bundle in %s\n' "${DEPLOY_DIR}" >&2
    exit 1
}

cat > "${DEPLOY_DIR}/tater-sat1-${PI_IMAGE_FLAVOR}-${PI_RELEASE_VERSION}.info" <<EOF
release_version=${PI_RELEASE_VERSION}
firmware_version=${TATER_SAT1_FIRMWARE_VERSION}
image_flavor=${PI_IMAGE_FLAVOR}
tater_reference=${TATER_REFERENCE}
tater_revision=${TATER_REVISION:-not_bundled}
tater_update_policy=${TATER_UPDATE_POLICY}
linux_satellite_revision=${SATELLITE_REVISION}
xmos_firmware=${XMOS_VERSION}
xmos_sha256=${XMOS_SHA256}
sat1_image_revision=$(git -C "${REPO_ROOT}" rev-parse HEAD)
EOF

printf '\nImage build complete: %s/deploy\n' "${PI_GEN_DIR}"
