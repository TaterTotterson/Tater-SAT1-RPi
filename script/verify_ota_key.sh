#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE_KEY="${1:-${ROOT_DIR}/.secrets/tater-sat1-ota-private.pem}"
PUBLIC_KEY="${2:-${ROOT_DIR}/keys/update-public.pem}"

[ -r "${PRIVATE_KEY}" ] || { printf 'Cannot read private key: %s\n' "${PRIVATE_KEY}" >&2; exit 1; }
[ -r "${PUBLIC_KEY}" ] || { printf 'Cannot read public key: %s\n' "${PUBLIC_KEY}" >&2; exit 1; }

TEMP_PUBLIC="$(mktemp)"
trap 'rm -f "${TEMP_PUBLIC}"' EXIT
openssl rsa -in "${PRIVATE_KEY}" -check -noout >/dev/null
openssl pkey -in "${PRIVATE_KEY}" -pubout -out "${TEMP_PUBLIC}"
cmp -s "${TEMP_PUBLIC}" "${PUBLIC_KEY}" || {
    printf '%s\n' 'The OTA private key does not match keys/update-public.pem.' >&2
    exit 1
}
printf '%s\n' 'SAT1 OTA private and public keys match.'
