#!/usr/bin/bash
# Apply the OS identity to the Hummingbird base after all packages and
# system-files overlays are present. The identity -- name, id, codename,
# registry namespace and URLs -- comes from config/identity.json, installed at
# /usr/share/utah/identity.json; nothing here spells it out, so a rename is an
# edit to that one file.

set -eoux pipefail

IDENTITY_FILE="${IDENTITY_FILE:-/usr/share/utah/identity.json}"
identity() {
    python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' \
        "${IDENTITY_FILE}" "$1"
}

IMAGE_PRETTY_NAME="$(identity name)"
IMAGE_LIKE="fedora"
IMAGE_NAME="${IMAGE_NAME:-$(identity id)}"
# Canonical OS identity is always the plain id, regardless of which image
# repository name a flavor was published under (<id>-nvidia, <id>-gaming, ...).
# Universal Blue tooling and the desktop contract read IMAGE_ID and image-name;
# the flavor lives in image-flavor, not in the identity.
IMAGE_ID="${IMAGE_ID:-$(identity id)}"
IMAGE_VENDOR="${IMAGE_VENDOR:-$(identity vendor)}"
IMAGE_FLAVOR="${IMAGE_FLAVOR:-main}"
VERSION="${VERSION:-testing}"
SHA_HEAD_SHORT="${SHA_HEAD_SHORT:-unknown}"
BASE_IMAGE_NAME="${BASE_IMAGE_NAME:-hummingbird}"
FEDORA_MAJOR_VERSION="${FEDORA_MAJOR_VERSION:-$(rpm -E %fedora)}"
UBLUE_IMAGE_TAG="${UBLUE_IMAGE_TAG:-${VERSION}}"
IMAGE_INFO="/usr/share/ublue-os/image-info.json"

install -d -m0755 /usr/share/ublue-os

# Keep image-info compatible with Universal Blue tooling while preserving the
# published image name and flavor.
cat >"${IMAGE_INFO}" <<EOF
{
  "image-name": "${IMAGE_ID}",
  "image-flavor": "${IMAGE_FLAVOR}",
  "image-vendor": "${IMAGE_VENDOR}",
  "image-ref": "ostree-image-signed:docker://ghcr.io/${IMAGE_VENDOR}/${IMAGE_NAME}",
  "image-tag": "${UBLUE_IMAGE_TAG}",
  "base-image-name": "${BASE_IMAGE_NAME}",
  "fedora-version": "${FEDORA_MAJOR_VERSION}"
}
EOF

# Replace Hummingbird/Fedora identity without assuming a particular ordering of
# os-release keys. All values are deliberately shell-quoted as os-release data.
set_os_release() {
    local key="$1" value="$2"
    if grep -q "^${key}=" /usr/lib/os-release; then
        sed -i "s|^${key}=.*|${key}=\"${value}\"|" /usr/lib/os-release
    else
        printf '%s="%s"\n' "${key}" "${value}" >> /usr/lib/os-release
    fi
}

set_os_release NAME "${IMAGE_PRETTY_NAME}"
set_os_release VARIANT_ID "${IMAGE_ID}"
set_os_release PRETTY_NAME "${IMAGE_PRETTY_NAME} (Version: ${VERSION})"
set_os_release ID "${IMAGE_ID}"
set_os_release ID_LIKE "${IMAGE_LIKE}"
set_os_release VERSION_ID "${FEDORA_MAJOR_VERSION}"
set_os_release CPE_NAME "cpe:/o:${IMAGE_VENDOR}:${IMAGE_ID}"
set_os_release HOME_URL "$(identity home_url)"
set_os_release DOCUMENTATION_URL "$(identity documentation_url)"
set_os_release SUPPORT_URL "$(identity support_url)"
set_os_release BUG_REPORT_URL "$(identity bug_report_url)"
set_os_release DEFAULT_HOSTNAME "${IMAGE_ID}"
set_os_release VERSION_CODENAME "$(identity codename)"
set_os_release VERSION "${VERSION} (${BASE_IMAGE_NAME^})"
set_os_release OSTREE_VERSION "${VERSION}"
set_os_release IMAGE_ID "${IMAGE_ID}"
set_os_release IMAGE_VERSION "${VERSION}"
set_os_release BUILD_ID "${SHA_HEAD_SHORT}"

# Fedora's bootloader helper still keys its vendor directory off EFIDIR after
# the distribution ID changes.
if [ -f /usr/sbin/grub2-switch-to-blscfg ]; then
    sed -i 's|^EFIDIR=.*|EFIDIR="fedora"|' /usr/sbin/grub2-switch-to-blscfg
fi

# These files are intentionally placeholders. The common stats timer
# refreshes them after first boot; keeping them present avoids a blank fastfetch
# and matches the files shipped by Bluefin.
printf '…\n' >/usr/share/ublue-os/fastfetch-user-count
printf '…\n' >/usr/share/ublue-os/bazaar-install-count

printf '%s branding configured for %s (flavor %s)\n' "${IMAGE_PRETTY_NAME}" "${IMAGE_NAME}" "${IMAGE_FLAVOR}"
