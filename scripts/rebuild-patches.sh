#!/usr/bin/env bash
# rebuild-patches.sh — Rebuild and reinstall hid-multitouch, cdc-acm, and
# yb9-kbdock kernel patches for the running kernel.
#
# Patches applied:
#   0001  hid-multitouch  — Yoga Book 9 touchscreen descriptor fixup
#   0002  cdc-acm         — INGENIC 17EF:6161 quirk (VENDOR_CLASS_DATA_IFACE +
#                           ALWAYS_POLL_CTRL)
#   0003  cdc-acm         — start bulk-IN polling when ALWAYS_POLL_CTRL is set
#   0004  yb9-kbdock      — keyboard dock detection driver (new file; copied
#                           from lenovo-yb9-kbdock.c in this directory)
#
# Usage:
#   cd ~/projects/yoga9ibook/scripts
#   bash rebuild-patches.sh

set -euo pipefail

KVER="$(uname -r)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${HOME}/kernel-src"
RPM_CACHE="${HOME}/kernel-src-rpms"

HID_PATCH="${SCRIPT_DIR}/0001-HID-multitouch-Fix-Yoga-Book-9-14IAH10-touchscreen-m.patch"
CDC_PATCH="${SCRIPT_DIR}/0002-USB-CDC-ACM-add-INGENIC-17EF-6161-quirk-for-Yoga-Book-9.patch"
CDC_PATCH3="${SCRIPT_DIR}/0003-USB-cdc-acm-ALWAYS_POLL_CTRL-also-poll-bulk-IN.patch"
KBDOCK_SRC="${SCRIPT_DIR}/lenovo-yb9-kbdock.c"

echo "==> Rebuilding patches for kernel ${KVER}"

# --------------------------------------------------------------------------
# 1. Build prerequisites
# --------------------------------------------------------------------------
echo "==> Installing build prerequisites..."
sudo dnf install -y "kernel-devel-${KVER}" rpm-build zstd

# --------------------------------------------------------------------------
# 2. Download source RPM (cached by kernel version)
# --------------------------------------------------------------------------
mkdir -p "${RPM_CACHE}"
SRC_RPM_GLOB="${RPM_CACHE}/kernel-$(echo "${KVER}" | sed 's/\.[^.]*$//').src.rpm"

if ! ls ${SRC_RPM_GLOB} &>/dev/null; then
    echo "==> Downloading kernel source RPM..."
    pushd "${RPM_CACHE}" >/dev/null
    dnf download --source "kernel-$(echo "${KVER}" | sed 's/\.[^.]*$//')"
    popd >/dev/null
else
    echo "==> Source RPM already cached: $(ls ${SRC_RPM_GLOB})"
fi

SRC_RPM="$(ls ${SRC_RPM_GLOB})"

# --------------------------------------------------------------------------
# 3. Extract kernel tarball from RPM (cached)
# --------------------------------------------------------------------------
TARBALL_DIR="${RPM_CACHE}"
if ! ls "${TARBALL_DIR}"/linux-*.tar.xz &>/dev/null; then
    echo "==> Extracting source tarball from RPM..."
    pushd "${TARBALL_DIR}" >/dev/null
    rpm2cpio "${SRC_RPM}" | cpio -idmv '*.tar.xz' 2>/dev/null
    popd >/dev/null
fi

KVER_SRC="$(ls "${TARBALL_DIR}"/linux-*.tar.xz | grep -oP 'linux-\K[0-9.]+(?=\.tar)')"
TARBALL="${TARBALL_DIR}/linux-${KVER_SRC}.tar.xz"
echo "==> Source tarball: linux-${KVER_SRC}.tar.xz"

# --------------------------------------------------------------------------
# 4. Set up build directory with fresh driver sources
# --------------------------------------------------------------------------
echo "==> Extracting fresh driver sources into ${BUILD_DIR}..."
mkdir -p "${BUILD_DIR}"

tar xf "${TARBALL}" --strip-components=3 -C "${BUILD_DIR}" \
    "linux-${KVER_SRC}/drivers/hid/hid-multitouch.c" \
    "linux-${KVER_SRC}/drivers/hid/hid-ids.h" \
    "linux-${KVER_SRC}/drivers/hid/hid-haptic.h"

tar xf "${TARBALL}" --strip-components=4 -C "${BUILD_DIR}" \
    "linux-${KVER_SRC}/drivers/usb/class/cdc-acm.c" \
    "linux-${KVER_SRC}/drivers/usb/class/cdc-acm.h"

# yb9-kbdock is a new driver not present in the upstream tree; copy from here.
cp "${KBDOCK_SRC}" "${BUILD_DIR}/yb9-kbdock.c"

# --------------------------------------------------------------------------
# 5. Write Makefile
# --------------------------------------------------------------------------
cat > "${BUILD_DIR}/Makefile" << 'EOF'
obj-m := hid-multitouch.o cdc-acm.o yb9-kbdock.o
EOF

# --------------------------------------------------------------------------
# 6. Apply patches
# --------------------------------------------------------------------------
echo "==> Applying hid-multitouch patch (0001)..."
# git format-patch: a/drivers/hid/hid-multitouch.c → strip 3 components
pushd "${BUILD_DIR}" >/dev/null
patch -p3 < "${HID_PATCH}"
popd >/dev/null

echo "==> Applying cdc-acm patch (0002)..."
# ed-format diff; patch detects the format automatically
pushd "${BUILD_DIR}" >/dev/null
patch cdc-acm.c < "${CDC_PATCH}"
popd >/dev/null

echo "==> Applying cdc-acm patch (0003)..."
# git format-patch: a/drivers/usb/class/cdc-acm.c → strip 4 components
pushd "${BUILD_DIR}" >/dev/null
patch -p4 < "${CDC_PATCH3}"
popd >/dev/null

# --------------------------------------------------------------------------
# 7. Build
# --------------------------------------------------------------------------
echo "==> Building modules against /usr/src/kernels/${KVER}..."
make -C "/usr/src/kernels/${KVER}" M="${BUILD_DIR}" modules

# --------------------------------------------------------------------------
# 8. Install hid-multitouch
# --------------------------------------------------------------------------
echo "==> Installing hid-multitouch.ko.zst..."
pushd "${BUILD_DIR}" >/dev/null
zstd -f -19 hid-multitouch.ko -o hid-multitouch.ko.zst
sudo cp hid-multitouch.ko.zst \
    "/lib/modules/${KVER}/kernel/drivers/hid/hid-multitouch.ko.zst"
popd >/dev/null

# --------------------------------------------------------------------------
# 9. Install cdc-acm
# --------------------------------------------------------------------------
echo "==> Installing cdc-acm.ko.zst..."
pushd "${BUILD_DIR}" >/dev/null

# The original .xz shadows .zst — move it aside if still present
CDC_XZ="/lib/modules/${KVER}/kernel/drivers/usb/class/cdc-acm.ko.xz"
if [ -f "${CDC_XZ}" ]; then
    echo "    Moving original cdc-acm.ko.xz aside (shadows .zst)..."
    sudo mv "${CDC_XZ}" "${BUILD_DIR}/cdc-acm.ko.xz.orig"
fi

zstd -f -19 cdc-acm.ko -o cdc-acm.ko.zst
sudo cp cdc-acm.ko.zst \
    "/lib/modules/${KVER}/kernel/drivers/usb/class/cdc-acm.ko.zst"
popd >/dev/null

# --------------------------------------------------------------------------
# 10. Install yb9-kbdock
# --------------------------------------------------------------------------
echo "==> Installing yb9-kbdock.ko.zst..."
pushd "${BUILD_DIR}" >/dev/null
sudo install -d "/lib/modules/${KVER}/extra"
zstd -f -19 yb9-kbdock.ko -o yb9-kbdock.ko.zst
sudo cp yb9-kbdock.ko.zst "/lib/modules/${KVER}/extra/yb9-kbdock.ko.zst"
popd >/dev/null

# --------------------------------------------------------------------------
# 11. Update module dependencies
# --------------------------------------------------------------------------
echo "==> Running depmod -a..."
sudo depmod -a

# --------------------------------------------------------------------------
echo ""
echo "==> Done. Patches installed for ${KVER}."
echo ""
echo "    Reload without rebooting:"
echo "      sudo rmmod hid_multitouch && sudo modprobe hid_multitouch"
echo "      sudo modprobe -r cdc_acm && sudo modprobe cdc_acm"
echo "      sudo rmmod yb9_kbdock lenovo_yb9_kbdock 2>/dev/null; sudo modprobe yb9_kbdock"
echo ""
echo "    Or reboot."
