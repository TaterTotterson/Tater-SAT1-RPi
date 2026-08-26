#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY_FILE="${1:-${ROOT_DIR}/.secrets/tater-sat1-ota-private.pem}"
PUBLIC_FILE="${2:-${ROOT_DIR}/keys/update-public.pem}"

mkdir -p "$(dirname "${KEY_FILE}")" "$(dirname "${PUBLIC_FILE}")"
umask 077

if [ -e "${KEY_FILE}" ]; then
    printf 'Refusing to overwrite existing key: %s\n' "${KEY_FILE}" >&2
    exit 1
fi

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out "${KEY_FILE}"
openssl pkey -in "${KEY_FILE}" -pubout -out "${PUBLIC_FILE}"
chmod 600 "${KEY_FILE}"
chmod 644 "${PUBLIC_FILE}"

printf 'Development-only SAT1 OTA key written to: %s\n' "${KEY_FILE}"
printf 'Matching public key written to: %s\n' "${PUBLIC_FILE}"
printf '%s\n' 'Keep it private. Build images and every future OTA release with this same key.'
